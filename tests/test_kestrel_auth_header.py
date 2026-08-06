"""Which host the Kestrel API key is allowed to reach.

The default endpoint moved to the public Kestrel, which needs no credentials. Environments
provisioned from the old deploy template set KESTREL_API_KEY and never set KESTREL_API_URL, so
without a host guard those upgrades would start sending an internal credential to a public
third-party host. These tests pin that guard.
"""

from unittest.mock import MagicMock, patch

import biomapper2.utils as utils
from biomapper2.config import PUBLIC_KESTREL_API_URL

INTERNAL_URL = "https://kestrel.nathanpricelab.com/api"


def _capture_headers(url: str, api_key: str | None) -> dict:
    """Run one bulk_kestrel_request against `url` with `api_key` and return the headers sent."""
    session = MagicMock()
    response = MagicMock()
    response.json.return_value = {}
    response.raise_for_status.return_value = None
    session.request.return_value = response

    utils._key_withheld_warned = False
    with (
        patch.object(utils, "KESTREL_API_URL", url),
        patch.object(utils, "get_kestrel_api_key", return_value=api_key),
    ):
        utils.bulk_kestrel_request("POST", "hybrid-search", session=session, json={})

    return session.request.call_args.kwargs["headers"]


def test_key_is_withheld_from_the_public_endpoint():
    """A retained internal key must NOT be sent to the public host (the upgrade leak path)."""
    assert "X-API-Key" not in _capture_headers(PUBLIC_KESTREL_API_URL, "internal-secret")


def test_key_is_sent_to_the_internal_endpoint():
    """The guard must not break the endpoint that actually requires authentication."""
    assert _capture_headers(INTERNAL_URL, "internal-secret")["X-API-Key"] == "internal-secret"


def test_no_key_configured_sends_no_header():
    """Keyless operation against the public endpoint is the new default path."""
    assert "X-API-Key" not in _capture_headers(PUBLIC_KESTREL_API_URL, None)


def test_public_endpoint_matched_by_host_not_exact_string():
    """A trailing slash or differing path must not defeat the guard."""
    assert "X-API-Key" not in _capture_headers("https://kestrel.krakenkg.com/api/", "internal-secret")


def test_withholding_the_key_is_warned_once():
    """Operators get told their config is stale, without a warning on every request."""
    with patch.object(utils.logging, "warning") as warn:
        utils._key_withheld_warned = False
        session = MagicMock()
        response = MagicMock()
        response.json.return_value = {}
        response.raise_for_status.return_value = None
        session.request.return_value = response
        with (
            patch.object(utils, "KESTREL_API_URL", PUBLIC_KESTREL_API_URL),
            patch.object(utils, "get_kestrel_api_key", return_value="internal-secret"),
        ):
            for _ in range(3):
                utils.bulk_kestrel_request("POST", "hybrid-search", session=session, json={})
    assert warn.call_count == 1
