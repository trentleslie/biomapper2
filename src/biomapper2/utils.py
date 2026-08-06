"""
Utility functions for biomapper2.

Provides logging setup and mathematical helpers for metric calculations.
"""

import logging
import time
from collections.abc import Iterator
from datetime import timedelta
from typing import Any, Literal, TypeGuard
from urllib.parse import urlparse

import requests
import requests_cache

from .config import (
    CACHE_DIR,
    KESTREL_API_URL,
    KESTREL_BATCHING_ENABLED,
    LOG_LEVEL,
    PUBLIC_KESTREL_API_URL,
    get_kestrel_api_key,
)
from .models import AssignedIDsDict as AssignedIDsDict  # Re-export for backward compatibility

# Type hint for annotation mode
AnnotationMode = Literal["all", "missing", "none"]

VALIDATOR_PROP = "validator"
CLEANER_PROP = "cleaner"
ALIASES_PROP = "aliases"


def chunk_list(items: list, chunk_size: int) -> Iterator[list]:
    """
    Split a list into chunks of specified size.

    Args:
        items: List to split
        chunk_size: Maximum size of each chunk

    Yields:
        List chunks of at most chunk_size items
    """
    for i in range(0, len(items), chunk_size):
        yield items[i : i + chunk_size]


def setup_logging():
    """Configure logging based on LOG_LEVEL in config.py."""
    if not logging.getLogger().hasHandlers():  # Skip setup if it's already been done
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        level = LOG_LEVEL.upper()

        if level not in valid_levels:
            print(f"Invalid log level '{LOG_LEVEL}', defaulting to INFO")
            level = "INFO"

        logging.basicConfig(
            level=getattr(logging, level), format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )


def text_is_not_empty(value: Any) -> TypeGuard[str]:
    """Check if a name/text field value is a valid non-empty string."""
    return isinstance(value, str) and value.strip() != ""


def to_list(item: Any) -> list[Any]:
    if item is None:
        return []
    elif isinstance(item, list):
        return item
    elif isinstance(item, (str, int, float)):
        return [item]
    else:
        return list(item)


def to_set(item: Any) -> set[Any]:
    if item is None:
        return set()
    elif isinstance(item, set):
        return item
    elif isinstance(item, (str, int, float)):
        return {item}
    else:
        return set(item)


def safe_divide(numerator, denominator) -> float | None:
    """
    Divide two numbers, returning None if denominator is zero.

    Args:
        numerator: Numerator value
        denominator: Denominator value

    Returns:
        Result of division, or None if denominator is zero
    """
    # Cast to float to handle potential numpy types
    numerator = float(numerator)
    denominator = float(denominator)

    if denominator == 0.0:
        # Return None, which will be serialized as 'null' in JSON.
        # This is more accurate for metrics like 'accuracy'
        # where a 0 denominator means 'not applicable'.
        return None

    result = numerator / denominator
    return result


_key_withheld_warned = False


def _accepts_credentials(url: str) -> bool:
    """False for the public Kestrel, which needs no key and must never receive one.

    Compared by hostname so a trailing slash or a different path does not defeat the check.
    """
    return urlparse(url).hostname != urlparse(PUBLIC_KESTREL_API_URL).hostname


def _warn_key_withheld_once() -> None:
    """Say once that a configured key is deliberately not being sent to the public endpoint."""
    global _key_withheld_warned
    if _key_withheld_warned:
        return
    _key_withheld_warned = True
    logging.warning(
        f"KESTREL_API_KEY is set but KESTREL_API_URL points at the public endpoint "
        f"({KESTREL_API_URL}), which needs no key — withholding the credential rather than "
        "sending it to a public host. Unset KESTREL_API_KEY, or set KESTREL_API_URL to the "
        "endpoint the key was issued for."
    )


def bulk_kestrel_request(
    method: str,
    endpoint: str,
    session: requests.Session | None = None,
    auth_required: bool = True,
    *,
    max_retries: int = 3,
    retry_backoff_base: float = 2.0,
    **kwargs,
) -> Any:
    """
    Make a single Kestrel API request with the full payload.

    This is the low-level function that sends one request. For batching support,
    use kestrel_request() instead.

    Transient server-side failures (HTTP 5xx) and connection/timeout errors are
    retried with exponential backoff; client errors (4xx) are raised immediately
    since they will not self-heal. A single Kestrel blip therefore no longer kills
    a long batch run.

    Args:
        method: HTTP method ('GET' or 'POST')
        endpoint: API endpoint path
        session: Optional requests session (defaults to cached session)
        auth_required: Whether to include the API key header. When False, the
            request is sent without authentication (e.g. for GET /categories).
            Default is True to preserve existing behavior.
        max_retries: Number of retries on transient errors (5xx / connection /
            timeout) before giving up. 0 disables retrying.
        retry_backoff_base: Base for exponential backoff; the delay before retry
            ``attempt`` (0-indexed) is ``retry_backoff_base ** attempt`` seconds.
        **kwargs: Additional arguments to pass to requests (json, params, etc.)

    Returns:
        JSON response from API

    Raises:
        requests.exceptions.HTTPError: If API returns error status (after retries
            for 5xx; immediately for 4xx)
        requests.exceptions.RequestException: If request fails after retries
    """
    # Sort search_text in json payload for consistent cache keys (if handling a batch)
    if "json" in kwargs and isinstance(kwargs["json"], dict):
        payload = kwargs["json"]
        if "search_text" in payload and isinstance(payload["search_text"], list):
            payload["search_text"].sort()

    if session is None:
        session = requests_cache.CachedSession(
            CACHE_DIR / "kestrel_http",
            expire_after=timedelta(hours=1),
            allowable_methods=["GET", "POST"],
        )

    headers: dict[str, str] = {}
    api_key = get_kestrel_api_key() if auth_required else None
    if api_key and _accepts_credentials(KESTREL_API_URL):
        headers["X-API-Key"] = api_key
    elif api_key:
        _warn_key_withheld_once()

    url = f"{KESTREL_API_URL}/{endpoint}"
    transient = (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.ChunkedEncodingError,
    )
    for attempt in range(max_retries + 1):
        try:
            response = session.request(method, url, headers=headers, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            status = getattr(e.response, "status_code", None)
            # Retry only transient server errors (5xx); 4xx (auth, bad payload) won't self-heal.
            if status is not None and 500 <= status < 600 and attempt < max_retries:
                delay = retry_backoff_base**attempt
                logging.warning(
                    f"Kestrel API {status} on {endpoint} "
                    f"(attempt {attempt + 1}/{max_retries + 1}); retrying in {delay:.1f}s"
                )
                time.sleep(delay)
                continue
            if status in (401, 403) and not api_key:
                logging.error(
                    f"Kestrel API {status} on {endpoint} and no KESTREL_API_KEY is set. "
                    f"{KESTREL_API_URL} requires authentication; set KESTREL_API_KEY, or point "
                    "KESTREL_API_URL at the public endpoint (https://kestrel.krakenkg.com/api), "
                    "which needs no key."
                )
                raise
            logging.error(f"Kestrel API HTTP error ({endpoint}): {e}", exc_info=True)
            raise
        except transient as e:
            if attempt < max_retries:
                delay = retry_backoff_base**attempt
                logging.warning(
                    f"Kestrel API transient error on {endpoint} ({type(e).__name__}) "
                    f"(attempt {attempt + 1}/{max_retries + 1}); retrying in {delay:.1f}s"
                )
                time.sleep(delay)
                continue
            logging.error(f"Kestrel API request failed ({endpoint}): {e}", exc_info=True)
            raise
        except requests.exceptions.RequestException as e:
            logging.error(f"Kestrel API request failed ({endpoint}): {e}", exc_info=True)
            raise


def kestrel_request(
    method: str,
    endpoint: str,
    batch_field: str,
    batch_items: list,
    batch_size: int,
    session: requests.Session | None = None,
    **kwargs,
) -> dict:
    """
    Make Kestrel API requests with automatic batching for large payloads.

    Splits batch_items into chunks, makes separate API calls for each chunk,
    and merges the results. Assumes API returns dict keyed by input items.

    When KESTREL_BATCHING_ENABLED is False, sends all items in a single request
    (useful for performance testing).

    Args:
        method: HTTP method ('GET' or 'POST')
        endpoint: API endpoint path
        batch_field: JSON field name for batch items (e.g., 'search_text', 'curies')
        batch_items: List of items to batch
        batch_size: Maximum items per request (ignored if batching disabled)
        session: Optional requests session
        **kwargs: Additional arguments (json, params, etc.)

    Returns:
        Merged dict of results from all batches
    """
    if not batch_items:
        return {}

    json_payload = kwargs.pop("json", {})

    # If batching is disabled, send all items in a single request
    if not KESTREL_BATCHING_ENABLED:
        full_payload = {**json_payload, batch_field: batch_items}
        result = bulk_kestrel_request(method, endpoint, session=session, json=full_payload, **kwargs)
        return result if isinstance(result, dict) else {}

    # Batch the request
    chunks = list(chunk_list(batch_items, batch_size))
    num_chunks = len(chunks)

    if num_chunks > 1:
        logging.info(f"Batching {len(batch_items)} items into {num_chunks} chunks of {batch_size} for {endpoint}")

    merged_results: dict = {}
    for chunk in chunks:
        chunk_payload = {**json_payload, batch_field: chunk}
        chunk_results = bulk_kestrel_request(method, endpoint, session=session, json=chunk_payload, **kwargs)

        if isinstance(chunk_results, dict):
            merged_results.update(chunk_results)

    return merged_results
