"""Where the Kestrel API key is allowed to go, and where it must never be written.

Two distinct leak paths are pinned here:

1. **On the wire.** The default endpoint is the public keyless Kestrel. Environments provisioned
   from the old deploy template set KESTREL_API_KEY and never set KESTREL_API_URL, so without a
   host guard those upgrades would send an internal credential to a public third-party host.
2. **At rest.** ``requests_cache`` redacts a default list of secret-ish parameter names, but matches
   them CASE-SENSITIVELY -- its "X-API-KEY" entry never matched the "X-API-Key" we send, so the
   credential was persisted in cleartext into every cached record. A mock-based test cannot catch
   that, so ``test_key_is_not_written_to_the_on_disk_cache`` writes through a real CachedSession and
   inspects the database bytes.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests
import requests_cache

import biomapper2.utils as utils
from biomapper2.config import CACHE_IGNORED_PARAMETERS, PUBLIC_KESTREL_API_URL

INTERNAL_URL = "https://kestrel.nathanpricelab.com/api"
SECRET = "internal-secret-value-do-not-transmit"


@pytest.fixture(autouse=True)
def _reset_warn_flag():
    """The one-shot warning flag is process-global; restore it so tests cannot leak state."""
    with patch.object(utils, "_key_withheld_warned", False):
        yield


def _capture_headers(
    url: str, api_key: str | None, *, calls: int = 1, auth_required: bool = True
) -> dict[str, str]:
    """Run `calls` requests against `url` with `api_key`, returning the headers actually sent."""
    session = MagicMock()
    response = MagicMock()
    response.json.return_value = {}
    response.raise_for_status.return_value = None
    session.request.return_value = response

    with (
        patch.object(utils, "KESTREL_API_URL", url),
        patch.object(utils, "get_kestrel_api_key", return_value=api_key),
    ):
        for _ in range(calls):
            utils.bulk_kestrel_request(
                "POST", "hybrid-search", session=session, auth_required=auth_required, json={}
            )

    assert session.request.called, "bulk_kestrel_request never issued a request"
    return session.request.call_args.kwargs["headers"]


# --- on the wire -------------------------------------------------------------------------------


def test_key_is_withheld_from_the_public_endpoint():
    """A retained internal key must NOT be sent to the public host (the upgrade leak path)."""
    assert "X-API-Key" not in _capture_headers(PUBLIC_KESTREL_API_URL, SECRET)


def test_key_is_sent_to_the_internal_endpoint():
    """The guard must not break the endpoint that actually requires authentication."""
    assert _capture_headers(INTERNAL_URL, SECRET)["X-API-Key"] == SECRET


def test_no_key_configured_sends_no_header():
    """Keyless operation against the public endpoint is the new default path."""
    assert "X-API-Key" not in _capture_headers(PUBLIC_KESTREL_API_URL, None)


def test_auth_required_false_sends_no_header():
    """The explicit opt-out path (e.g. GET /categories) must omit the credential."""
    assert "X-API-Key" not in _capture_headers(INTERNAL_URL, SECRET, auth_required=False)


@pytest.mark.parametrize(
    "url",
    [
        "https://kestrel.krakenkg.com/api",  # exact
        "https://kestrel.krakenkg.com/api/",  # trailing slash
        "https://KESTREL.KRAKENKG.COM/api",  # uppercase host
        "https://kestrel.krakenkg.com./api",  # trailing FQDN dot -- same destination
        "https://kestrel.krakenkg.com:443/api",  # explicit default port
        "https://kestrel.krakenkg.com/other/path",  # different path, same host
    ],
)
def test_public_host_variants_all_withhold_the_key(url):
    """The guard matches on normalized host, so no spelling of the public host receives the key."""
    assert "X-API-Key" not in _capture_headers(url, SECRET)


def test_unparseable_url_fails_closed():
    """A URL with no parseable host must withhold the key rather than send it somewhere unproven."""
    assert "X-API-Key" not in _capture_headers("kestrel.krakenkg.com/api", SECRET)


def test_withholding_the_key_is_warned_once():
    """Operators get told their config is stale, without a warning on every request."""
    with patch.object(utils.logging, "warning") as warn:
        _capture_headers(PUBLIC_KESTREL_API_URL, SECRET, calls=3)
    assert warn.call_count == 1


def test_no_warning_when_the_key_is_legitimately_used():
    """A false alarm on a working internal config would train operators to ignore the warning."""
    with patch.object(utils.logging, "warning") as warn:
        _capture_headers(INTERNAL_URL, SECRET)
    assert warn.call_count == 0


def test_cross_origin_redirect_strips_the_credential():
    """`requests` strips only Authorization across origins; our custom header must go too.

    Retiring the internal host with a 301 to the public one would otherwise hand the internal key
    to a third party, bypassing the URL-level guard entirely.
    """
    session = utils._KestrelCachedSession(backend="memory")
    original = requests.Request("POST", INTERNAL_URL).prepare()
    redirected = requests.Request("POST", PUBLIC_KESTREL_API_URL).prepare()
    redirected.headers["X-API-Key"] = SECRET

    response = MagicMock()
    response.request = original
    session.rebuild_auth(redirected, response)

    assert "X-API-Key" not in redirected.headers


def test_same_origin_redirect_keeps_the_credential():
    """A redirect within the same host is not a leak and must not lose auth."""
    session = utils._KestrelCachedSession(backend="memory")
    original = requests.Request("POST", f"{INTERNAL_URL}/a").prepare()
    redirected = requests.Request("POST", f"{INTERNAL_URL}/b").prepare()
    redirected.headers["X-API-Key"] = SECRET

    response = MagicMock()
    response.request = original
    session.rebuild_auth(redirected, response)

    assert redirected.headers["X-API-Key"] == SECRET


# --- at rest -----------------------------------------------------------------------------------


@pytest.fixture
def local_json_server():
    """A real localhost HTTP server, so requests_cache actually persists a record.

    A mocked transport adapter is NOT sufficient here: with a mock, nothing is written to the
    database at all, so an assertion about absent bytes passes whether or not redaction works. The
    first version of this test made exactly that mistake. Verified against this fixture, the
    library default leaks 1 cleartext copy of the secret and ``CACHE_IGNORED_PARAMETERS`` leaks 0.
    """
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 -- BaseHTTPRequestHandler's required spelling
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            body = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # keep pytest output clean
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/api"
    finally:
        server.shutdown()
        server.server_close()


def _cleartext_occurrences(cache_dir, base_url, ignored_parameters) -> int:
    """POST through a real CachedSession and count cleartext copies of SECRET on disk."""
    session = requests_cache.CachedSession(
        str(cache_dir / "kestrel_http"),
        allowable_methods=["GET", "POST"],
        ignored_parameters=ignored_parameters,
    )
    session.post(f"{base_url}/hybrid-search", headers={"X-API-Key": SECRET}, json={"q": 1})
    written = [p for p in cache_dir.iterdir() if p.is_file()]
    assert written, "cache wrote no file, so this test would prove nothing"
    return sum(p.read_bytes().count(SECRET.encode()) for p in written)


def test_key_is_not_written_to_the_on_disk_cache(tmp_path, local_json_server):
    """The credential must not reach the cache database in cleartext."""
    assert _cleartext_occurrences(tmp_path, local_json_server, CACHE_IGNORED_PARAMETERS) == 0


def test_the_library_default_would_leak_the_key(tmp_path, local_json_server):
    """Pins the bug this fix exists for, so the guard above cannot silently become vacuous.

    requests_cache's default ``ignored_parameters`` lists "X-API-KEY" and is matched
    case-sensitively, so the "X-API-Key" spelling we send is never redacted. If this test ever
    starts failing, the library fixed its casing and our explicit list may be redundant -- verify
    before removing it.
    """
    assert _cleartext_occurrences(tmp_path, local_json_server, ["X-API-KEY"]) > 0


def test_redaction_list_covers_the_casing_we_actually_send():
    """The header spelling used at the call site must be in the redaction list, exactly."""
    assert utils._KESTREL_KEY_HEADER in CACHE_IGNORED_PARAMETERS
