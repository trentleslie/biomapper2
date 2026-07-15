"""Shared competitor infrastructure: rate limit, cache, retry/backoff, chunking, response."""

from __future__ import annotations

import pytest

from studies.external_benchmarks.competitors.base import (
    CompetitorOutageError,
    HttpResponse,
    InMemoryCache,
    RateLimiter,
    TransientHttpError,
    cache_key,
    chunked,
    with_retries,
)
from studies.external_benchmarks.tests.competitor_fakes import json_response, no_sleep


def test_http_response_ok_and_json():
    r = HttpResponse(status_code=200, json_body={"a": 1})
    assert r.ok is True
    assert r.json() == {"a": 1}
    assert HttpResponse(status_code=500).ok is False


def test_http_response_json_from_text():
    r = HttpResponse(status_code=200, text='{"x": 2}')
    assert r.json() == {"x": 2}


def test_rate_limiter_sleeps_to_enforce_interval():
    clock = {"t": 0.0}
    slept: list[float] = []
    rl = RateLimiter(1.0, now=lambda: clock["t"], sleep=lambda s: slept.append(s))
    rl.acquire()  # first call: no wait
    assert slept == []
    rl.acquire()  # immediately after: must wait the full interval
    assert slept == [pytest.approx(1.0)]


def test_rate_limiter_zero_interval_never_sleeps():
    slept: list[float] = []
    rl = RateLimiter(0.0, now=lambda: 0.0, sleep=lambda s: slept.append(s))
    rl.acquire()
    rl.acquire()
    assert slept == []


def test_in_memory_cache_roundtrip():
    c = InMemoryCache()
    assert c.get("k") is None
    c.set("k", [1, 2])
    assert c.get("k") == [1, 2]


def test_cache_key_is_order_independent_and_deduped():
    a = cache_key("tool", "SYMBOL", "ENSG", ["BRCA1", "TP53", "BRCA1"])
    b = cache_key("tool", "SYMBOL", "ENSG", ["TP53", "BRCA1"])
    assert a == b


def test_chunked_splits_and_rejects_nonpositive():
    assert list(chunked(["a", "b", "c"], 2)) == [["a", "b"], ["c"]]
    with pytest.raises(ValueError):
        list(chunked(["a"], 0))


def test_with_retries_returns_first_success():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return json_response({"ok": True})

    resp = with_retries(fn, sleep=no_sleep)
    assert resp.json() == {"ok": True}
    assert calls["n"] == 1


def test_with_retries_retries_transient_then_succeeds():
    seq = [TransientHttpError("timeout"), json_response({}, status=503), json_response({"ok": 1})]

    def fn():
        item = seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    resp = with_retries(fn, sleep=no_sleep)
    assert resp.json() == {"ok": 1}


def test_with_retries_raises_outage_after_exhaustion():
    def fn():
        return json_response({}, status=503)

    with pytest.raises(CompetitorOutageError):
        with_retries(fn, max_attempts=3, sleep=no_sleep)


def test_with_retries_returns_nonretryable_4xx_as_is():
    resp = with_retries(lambda: json_response({"err": "bad"}, status=400), sleep=no_sleep)
    assert resp.status_code == 400  # a client error is the client's to read, not an outage


def test_supported_targets_accepts_optional_source_ns():
    """The base split stays per-target and back-compatible; the optional ``source_ns`` is a hook for
    source-aware subclasses (UniProt) and must not change the default behavior."""
    from studies.external_benchmarks.competitors.base import CompetitorClient

    class _Tool(CompetitorClient):
        name = "t"

        def source_code(self, source_ns):
            return source_ns

        def target_code(self, target_ns):
            return target_ns if target_ns in {"ENSEMBL", "UniProtKB"} else None

        def map_batch(self, ids, source_ns, target_ns):  # pragma: no cover - unused here
            raise NotImplementedError

    t = _Tool(transport=None)  # type: ignore[arg-type]
    assert t.supported_targets(("ENSEMBL", "NCBIGene", "UniProtKB")) == (["ENSEMBL", "UniProtKB"], ["NCBIGene"])
    # passing a source_ns is accepted and (for the base impl) does not change the split
    assert t.supported_targets(("ENSEMBL", "NCBIGene"), "SYMBOL") == (["ENSEMBL"], ["NCBIGene"])
