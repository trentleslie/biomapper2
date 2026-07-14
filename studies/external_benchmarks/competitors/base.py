"""Shared competitor-client infrastructure: transport, cache, rate limit, retries, base class.

The HTTP layer is isolated behind ``HttpTransport`` so every client is fully unit-testable on a
scripted fake — the offline test suite NEVER hits a live API. Resilience (rate limiting, response
caching, bounded retry with backoff) lives here once and is shared by all three clients:

  - ``RateLimiter`` enforces a minimum interval between calls (injectable clock/sleep so tests
    don't actually wait).
  - ``ResponseCache`` (protocol) + ``InMemoryCache`` memoize identical batch calls so a re-run or
    an overlapping batch never re-hits the service.
  - ``with_retries`` retries transient failures (timeouts, connection errors, 5xx, 429) with
    exponential backoff, then FAILS LOUD (``CompetitorOutageError``). An outage is never scored as
    a zero — that would misrepresent the tool's real coverage.
"""

from __future__ import annotations

import json as _json
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# Statuses that indicate a *transient* server-side problem worth retrying (vs a client error).
RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


class CompetitorError(RuntimeError):
    """Base class for competitor-client failures."""


class CompetitorOutageError(CompetitorError):
    """A batch call permanently failed after exhausting retries (network/5xx).

    Raised fail-loud so an outage is never silently scored as 0% coverage. Distinct from a row
    that a *reachable* tool simply returns no mapping for (that is an honest miss, not an error).
    """


class CompetitorConfigError(CompetitorError):
    """A client was asked for something it cannot express (e.g. an unknown source namespace)."""


class TransientHttpError(RuntimeError):
    """Internal signal that a transport call hit a retryable condition. Never leaves this module."""


@dataclass(frozen=True)
class HttpResponse:
    """A transport-agnostic HTTP response. Fakes construct this directly in tests."""

    status_code: int
    text: str = ""
    headers: Mapping[str, str] = field(default_factory=dict)
    json_body: Any = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> Any:
        if self.json_body is not None:
            return self.json_body
        return _json.loads(self.text) if self.text else None


@runtime_checkable
class HttpTransport(Protocol):
    """The single HTTP seam every client depends on. Tests inject a scripted fake."""

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        allow_redirects: bool = True,
    ) -> HttpResponse: ...


class RequestsTransport:
    """Live transport backed by ``requests`` (only used by the gated run, never in tests)."""

    def __init__(self, session: Any | None = None, *, default_timeout: float = 60.0) -> None:
        if session is None:
            import requests  # imported lazily so the offline suite needs no live session

            session = requests.Session()
        self._session = session
        self._default_timeout = default_timeout

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        allow_redirects: bool = True,
    ) -> HttpResponse:
        import requests

        try:
            resp = self._session.request(
                method,
                url,
                params=params,
                data=data,
                json=json,
                headers=headers,
                timeout=timeout or self._default_timeout,
                allow_redirects=allow_redirects,
            )
        except requests.RequestException as exc:  # timeouts / connection resets are retryable
            raise TransientHttpError(str(exc)) from exc
        return HttpResponse(
            status_code=resp.status_code,
            text=resp.text,
            headers=dict(resp.headers),
            json_body=None,
        )


class RateLimiter:
    """Enforce a minimum interval between calls. Clock/sleep injectable for deterministic tests."""

    def __init__(
        self,
        min_interval_s: float,
        *,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval_s = max(0.0, min_interval_s)
        self._now = now
        self._sleep = sleep
        self._last: float | None = None

    def acquire(self) -> None:
        if self.min_interval_s <= 0:
            return
        now = self._now()
        if self._last is not None:
            wait = self.min_interval_s - (now - self._last)
            if wait > 0:
                self._sleep(wait)
                now = self._now()
        self._last = now


@runtime_checkable
class ResponseCache(Protocol):
    """Minimal cache seam — a persistent disk cache can satisfy this for the live run."""

    def get(self, key: str) -> Any | None: ...
    def set(self, key: str, value: Any) -> None: ...


class InMemoryCache:
    """Default process-local cache (dict-backed). Good enough for a single benchmark run."""

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def get(self, key: str) -> Any | None:
        return self._store.get(key)

    def set(self, key: str, value: Any) -> None:
        self._store[key] = value


def cache_key(tool: str, source_ns: str, target_code: str, ids: Iterable[str]) -> str:
    """Stable cache key for a batch: tool + direction + the sorted, de-duplicated id set."""
    ids_norm = ",".join(sorted({str(i).strip() for i in ids if str(i).strip()}))
    return f"{tool}|{source_ns}->{target_code}|{ids_norm}"


def with_retries(
    fn: Callable[[], HttpResponse],
    *,
    max_attempts: int = 4,
    base_backoff_s: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
) -> HttpResponse:
    """Call ``fn`` with bounded exponential backoff on transient failures; else fail loud.

    Retries ``TransientHttpError`` (timeouts/connection) and retryable HTTP statuses. A response
    with a non-retryable 4xx is returned as-is (the client decides how to read it). After
    ``max_attempts``, a ``CompetitorOutageError`` is raised — an outage is never a silent zero.
    """
    last_detail = ""
    for attempt in range(1, max_attempts + 1):
        try:
            resp = fn()
        except TransientHttpError as exc:
            last_detail = f"transport error: {exc}"
        else:
            if resp.status_code not in RETRYABLE_STATUSES:
                return resp
            last_detail = f"HTTP {resp.status_code}"
        if attempt < max_attempts:
            sleep(base_backoff_s * (2 ** (attempt - 1)))
    raise CompetitorOutageError(
        f"batch call failed after {max_attempts} attempts ({last_detail}). Refusing to score an "
        f"outage as zero coverage."
    )


def chunked(items: Sequence[str], size: int) -> Iterable[list[str]]:
    """Yield ``size``-length chunks of a query list (batch endpoints, respect rate limits)."""
    if size <= 0:
        raise ValueError("chunk size must be positive")
    for i in range(0, len(items), size):
        yield list(items[i : i + size])


class CompetitorClient(ABC):
    """Base class: caching + rate limiting + retry are shared; parsing/direction is per tool.

    Subclasses implement ``map_batch`` (one reachable batch call -> ``{query -> set[CURIE]}``) and
    declare their per-namespace support via ``target_code``/``source_code``. ``map_ids`` fans a full
    query list out over chunks, one target namespace at a time, and merges the per-namespace CURIE
    sets — so every namespace a tool CAN express is queried and the rest are recorded as
    ``unsupported`` protocol deltas by the runner.
    """

    name: str = "competitor"
    #: max queries per HTTP call (batch endpoints); tuned conservatively for hosted rate limits.
    batch_size: int = 250

    def __init__(
        self,
        transport: HttpTransport,
        *,
        rate_limiter: RateLimiter | None = None,
        cache: ResponseCache | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 4,
    ) -> None:
        self.transport = transport
        self.rate_limiter = rate_limiter or RateLimiter(0.0)
        self.cache = cache or InMemoryCache()
        self._sleep = sleep
        self._max_attempts = max_attempts

    # --- per-tool namespace support -------------------------------------------------------------

    @abstractmethod
    def source_code(self, source_ns: str) -> str | None:
        """Tool-specific code for the SOURCE namespace, or None if the tool can't accept it."""

    @abstractmethod
    def target_code(self, target_ns: str) -> str | None:
        """Tool-specific code for a TARGET namespace, or None if the tool can't emit it."""

    def supported_targets(self, target_namespaces: Iterable[str]) -> tuple[list[str], list[str]]:
        """Split requested targets into (supported, unsupported) for this tool."""
        supported, unsupported = [], []
        for ns in target_namespaces:
            (supported if self.target_code(ns) is not None else unsupported).append(ns)
        return supported, unsupported

    # --- one reachable batch call ---------------------------------------------------------------

    @abstractmethod
    def map_batch(self, ids: list[str], source_ns: str, target_ns: str) -> dict[str, set[str]]:
        """Map one chunk to ONE target namespace. Returns ``{query -> set[CURIE]}``.

        MUST return canonical, gold-convention CURIEs (see ``namespaces.to_curie``). A query with no
        mapping is simply absent / maps to an empty set (an honest miss — never an exception).
        """

    # --- shared fan-out -------------------------------------------------------------------------

    def map_ids(self, queries: Sequence[str], source_ns: str, target_namespaces: Iterable[str]) -> dict[str, set[str]]:
        """Map every query to every SUPPORTED target namespace; merge the CURIE sets per query.

        Deterministic order; de-duplicates queries per batch; caches each (chunk, target) call.
        Unsupported target namespaces are skipped here (the runner records them as protocol deltas).
        """
        if self.source_code(source_ns) is None:
            raise CompetitorConfigError(f"{self.name}: source namespace {source_ns!r} is not expressible by this tool.")
        supported, _ = self.supported_targets(target_namespaces)
        merged: dict[str, set[str]] = {q: set() for q in queries}
        # Preserve first-seen query order but de-duplicate for the wire.
        unique_queries = list(dict.fromkeys(q for q in queries if str(q).strip()))
        for target_ns in supported:
            code = self.target_code(target_ns)
            assert code is not None  # supported by construction
            for chunk in chunked(unique_queries, self.batch_size):
                key = cache_key(self.name, source_ns, code, chunk)
                cached = self.cache.get(key)
                if cached is not None:
                    batch_out = {q: set(v) for q, v in cached.items()}
                else:
                    self.rate_limiter.acquire()
                    batch_out = self.map_batch(chunk, source_ns, target_ns)
                    self.cache.set(key, {q: sorted(v) for q, v in batch_out.items()})
                for q, curies in batch_out.items():
                    if q in merged:
                        merged[q] |= curies
        return merged

    def _request_with_retries(self, method: str, url: str, **kwargs: Any) -> HttpResponse:
        """Rate-limited, retried single request. Callers own reading the (possibly 4xx) response."""
        return with_retries(
            lambda: self.transport.request(method, url, **kwargs),
            max_attempts=self._max_attempts,
            sleep=self._sleep,
        )
