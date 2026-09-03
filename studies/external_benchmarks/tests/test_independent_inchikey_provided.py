"""Unit 1 — the provided-id lipid oracle (resolves curator HMDB/PubChem/InChIKey ids, tagged).

Metabolon shorthand lipids don't resolve by name, but the cohort source carries curator cross-
reference ids. ``block_for_provided`` resolves them KG-independently and tags provenance so the
certificate can enforce disjointness (Unit 2). Fetch is faked — no live call. A transient
``lookup_failed`` must be distinguishable from a genuine ``clean_miss`` (KD4), else a network blip
would masquerade as new coverage. Each miss/failure case is a positive control that can fail.
"""

from __future__ import annotations

from studies.external_benchmarks.scorers.independent_inchikey import PubChemInChIKeyResolver


class _Resp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


class _RoutedSession:
    """Fake session returning a per-endpoint response keyed by URL substring; counts calls."""

    def __init__(self, routes: dict[str, _Resp]):
        self._routes = routes  # substring -> response
        self.calls = 0

    def get(self, url: str, timeout: float | None = None) -> _Resp:
        self.calls += 1
        for frag, resp in self._routes.items():
            if frag in url:
                return resp
        return _Resp(404, "")


def test_provided_inchikey_is_offline_and_authoritative():
    sess = _RoutedSession({})
    r = PubChemInChIKeyResolver(session=sess)
    out = r.block_for_provided(inchikey="FHQVHHIBKUMWTI-OTMQOFQ-N", hmdb="HMDB0005320")
    assert (out.block, out.source, out.status) == ("FHQVHHIBKUMWTI", "provided-inchikey", "success")
    assert sess.calls == 0  # never hit the network when the InChIKey is provided


def test_falls_through_to_hmdb_when_no_inchikey():
    sess = _RoutedSession({"xref/RegistryID": _Resp(200, "FHQVHHIBKUMWTI-OTMQOFQ-N\n")})
    out = PubChemInChIKeyResolver(session=sess).block_for_provided(hmdb="HMDB0005320")
    assert (out.block, out.source, out.status) == ("FHQVHHIBKUMWTI", "provided-hmdb", "success")


def test_hmdb_clean_miss_falls_through_to_pubchem():
    sess = _RoutedSession(
        {"xref/RegistryID": _Resp(404, ""), "compound/cid": _Resp(200, "BSNJSZUDOMPYIR-DMDPBSJ-N\n")}
    )
    out = PubChemInChIKeyResolver(session=sess).block_for_provided(hmdb="HMDB9", pubchem="46891795")
    assert (out.block, out.source, out.status) == ("BSNJSZUDOMPYIR", "provided-pubchem", "success")


def test_lookup_failed_is_distinct_from_clean_miss():
    # HMDB returns 500 (transient), no other id resolves -> must be lookup_failed, NOT clean_miss.
    sess = _RoutedSession({"xref/RegistryID": _Resp(500, "")})
    out = PubChemInChIKeyResolver(session=sess).block_for_provided(hmdb="HMDB0005320")
    assert out.block is None and out.status == "lookup_failed"


def test_all_sources_absent_is_clean_miss():
    sess = _RoutedSession({"xref/RegistryID": _Resp(404, ""), "compound/name": _Resp(404, "")})
    out = PubChemInChIKeyResolver(session=sess).block_for_provided(hmdb="X", name="1,2-dilinoleoyl-GPC (18:2/18:2)")
    assert out.block is None and out.status == "clean_miss" and out.source == "none"


def test_name_is_last_fallback():
    sess = _RoutedSession({"compound/name": _Resp(200, "WHUUTDBJXJRKMK-VKHMYHEASA-N\n")})
    out = PubChemInChIKeyResolver(session=sess).block_for_provided(name="glutamate")
    assert (out.block, out.source) == ("WHUUTDBJXJRKMK", "pubchem-name")


def test_lookup_failed_is_not_cached_and_retries():
    # A transient 5xx must NOT be cached: a second call after the service "recovers" retries and succeeds.
    class _Flaky:
        def __init__(self):
            self.n = 0

        def get(self, url, timeout=None):
            self.n += 1
            return _Resp(500, "") if self.n == 1 else _Resp(200, "FHQVHHIBKUMWTI-OTMQOFQ-N\n")

    r = PubChemInChIKeyResolver(session=_Flaky())
    first = r.block_for_provided(hmdb="HMDB0005320")
    assert first.status == "lookup_failed" and first.block is None
    second = r.block_for_provided(hmdb="HMDB0005320")
    assert second.status == "success" and second.block == "FHQVHHIBKUMWTI"


def test_provided_resolution_is_cached():
    sess = _RoutedSession({"xref/RegistryID": _Resp(200, "FHQVHHIBKUMWTI-OTMQOFQ-N\n")})
    r = PubChemInChIKeyResolver(session=sess)
    r.block_for_provided(hmdb="HMDB0005320")
    r.block_for_provided(hmdb="HMDB0005320")
    assert sess.calls == 1  # repeated id costs one fetch
