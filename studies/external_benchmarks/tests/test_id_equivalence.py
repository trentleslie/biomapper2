"""UniChem client + ID-equivalence judge — offline (fake requests.Session)."""

from __future__ import annotations

import json

from studies.external_benchmarks.scorers.id_equivalence import (
    UniChemClient,
    UniChemIdEquivalenceJudge,
    _first_block,
)


class FakeResp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    """Records requests and replays canned responses keyed by (method, url)."""

    def __init__(self, routes):
        self._routes = routes  # {(method, url_substr): FakeResp | list[FakeResp]}
        self.calls = []

    def _match(self, method, url):
        for (m, sub), resp in self._routes.items():
            if m == method and sub in url:
                if isinstance(resp, list):
                    return resp.pop(0) if resp else FakeResp(500)
                return resp
        return FakeResp(404)

    def get(self, url, timeout=None, headers=None):
        self.calls.append(("GET", url))
        return self._match("GET", url)

    def post(self, url, json=None, timeout=None, headers=None):
        self.calls.append(("POST", url, json))
        return self._match("POST", url)


_SOURCES = {
    "sources": [
        {"id": 7, "shortName": "chebi"},
        {"id": 2, "shortName": "hmdb"},
        {"id": 22, "shortName": "pubchem"},
        {"id": 6, "shortName": "kegg_ligand"},
    ]
}

# Glucose: UCI 12345, standard InChIKey WQZGKKKJIJFFOK-GASJEMHNSA-N, cross-refs to HMDB0000122.
_COMPOUNDS_CHEBI_4167 = {
    "compounds": [
        {
            "uci": "12345",
            "standardInchiKey": "WQZGKKKJIJFFOK-GASJEMHNSA-N",
            "sources": [
                {"shortName": "chebi", "compoundId": "4167"},
                {"shortName": "hmdb", "compoundId": "HMDB0000122"},
                {"shortName": "pubchem", "compoundId": "5793"},
            ],
        }
    ]
}


def _client():
    session = FakeSession(
        {
            ("GET", "/sources/"): FakeResp(200, _SOURCES),
            ("POST", "/api/v1/compounds"): FakeResp(200, _COMPOUNDS_CHEBI_4167),
        }
    )
    return UniChemClient(session=session, cache_path=None), session


def test_first_block_helper():
    assert _first_block("WQZGKKKJIJFFOK-GASJEMHNSA-N") == "WQZGKKKJIJFFOK"
    assert _first_block(None) is None
    assert _first_block("") is None


def test_lookup_returns_uci_block_and_normalized_sources():
    client, _ = _client()
    rec = client.lookup("CHEBI:4167")
    assert rec is not None
    assert rec["uci"] == "12345"
    assert rec["block"] == "WQZGKKKJIJFFOK"
    # sources normalized to canonical CURIE prefixes (PUBCHEM/KEGG folded by normalize_curie)
    assert "HMDB:HMDB0000122" in rec["sources"]
    assert "PUBCHEM:5793" in rec["sources"]


def test_lookup_is_cached_one_call_per_unique_id():
    client, session = _client()
    client.lookup("CHEBI:4167")
    client.lookup("CHEBI:4167")
    post_calls = [c for c in session.calls if c[0] == "POST"]
    assert len(post_calls) == 1  # second lookup served from cache


def test_lookup_fail_soft_on_non_200():
    session = FakeSession(
        {
            ("GET", "/sources/"): FakeResp(200, _SOURCES),
            ("POST", "/api/v1/compounds"): FakeResp(503),
        }
    )
    client = UniChemClient(session=session, cache_path=None)
    assert client.lookup("CHEBI:4167") is None


def test_transient_compound_failure_is_not_cached_and_recovers():
    # A 503 must NOT poison the cache: a later lookup after recovery re-requests and resolves.
    session = FakeSession(
        {
            ("GET", "/sources/"): FakeResp(200, _SOURCES),
            ("POST", "/api/v1/compounds"): [
                FakeResp(503),  # transient outage
                FakeResp(200, _COMPOUNDS_CHEBI_4167),  # service recovered
            ],
        }
    )
    client = UniChemClient(session=session, cache_path=None)
    assert client.lookup("CHEBI:4167") is None  # fail-soft on the outage
    rec = client.lookup("CHEBI:4167")  # retried, not served from a poisoned cache
    assert rec is not None and rec["uci"] == "12345"


def test_genuine_no_match_is_cached_one_post():
    # A 200 with no compounds is a real negative and SHOULD be cached (no retry storm).
    session = FakeSession(
        {
            ("GET", "/sources/"): FakeResp(200, _SOURCES),
            ("POST", "/api/v1/compounds"): FakeResp(200, {"compounds": []}),
        }
    )
    client = UniChemClient(session=session, cache_path=None)
    assert client.lookup("CHEBI:4167") is None
    assert client.lookup("CHEBI:4167") is None
    post_calls = [c for c in session.calls if c[0] == "POST"]
    assert len(post_calls) == 1  # negative served from cache the second time


def test_transient_source_registry_failure_recovers():
    # A failed /sources/ registry fetch must not disable resolution for the client lifetime.
    session = FakeSession(
        {
            ("GET", "/sources/"): [FakeResp(503), FakeResp(200, _SOURCES)],
            ("POST", "/api/v1/compounds"): FakeResp(200, _COMPOUNDS_CHEBI_4167),
        }
    )
    client = UniChemClient(session=session, cache_path=None)
    assert client.lookup("CHEBI:4167") is None  # registry down -> transient, uncached
    rec = client.lookup("CHEBI:4167")  # registry recovered -> resolves
    assert rec is not None and rec["uci"] == "12345"


def test_incomplete_source_registry_is_not_memoized_and_recovers():
    # A 200 registry missing some sources must not be pinned for the client lifetime: a later
    # lookup re-fetches and, once the registry is complete, resolves the previously-missing source.
    incomplete = {"sources": [{"id": 2, "shortName": "hmdb"}]}  # missing chebi/pubchem/kegg
    session = FakeSession(
        {
            ("GET", "/sources/"): [FakeResp(200, incomplete), FakeResp(200, _SOURCES)],
            ("POST", "/api/v1/compounds"): FakeResp(200, _COMPOUNDS_CHEBI_4167),
        }
    )
    client = UniChemClient(session=session, cache_path=None)
    assert client.lookup("CHEBI:4167") is None  # chebi absent from the partial registry
    rec = client.lookup("CHEBI:4167")  # registry re-fetched, now complete
    assert rec is not None and rec["uci"] == "12345"


def test_persisted_null_cache_entry_is_ignored_and_retried(tmp_path):
    # A null on disk (possibly a stale transient failure from an older client) is dropped on load
    # and re-resolved, rather than returned as an unrecoverable miss.
    cache = tmp_path / "unichem_cache.json"
    cache.write_text(json.dumps({"CHEBI:4167": None}))
    session = FakeSession(
        {
            ("GET", "/sources/"): FakeResp(200, _SOURCES),
            ("POST", "/api/v1/compounds"): FakeResp(200, _COMPOUNDS_CHEBI_4167),
        }
    )
    client = UniChemClient(session=session, cache_path=str(cache))
    rec = client.lookup("CHEBI:4167")
    assert rec is not None and rec["uci"] == "12345"


def test_genuine_negative_is_not_persisted_to_disk(tmp_path):
    # Negatives are cached in memory for the session but never written to disk, so they can't
    # harden into a cross-run poison entry indistinguishable from a transient failure.
    cache = tmp_path / "unichem_cache.json"
    session = FakeSession(
        {
            ("GET", "/sources/"): FakeResp(200, _SOURCES),
            ("POST", "/api/v1/compounds"): FakeResp(200, {"compounds": []}),
        }
    )
    client = UniChemClient(session=session, cache_path=str(cache))
    assert client.lookup("CHEBI:4167") is None
    assert "CHEBI:4167" not in json.loads(cache.read_text())  # null not persisted


def test_judge_uci_equivalence_same_uci_across_namespaces():
    # gold HMDB:HMDB0000122, prediction CHEBI:4167 -> both resolve to UCI 12345 (glucose).
    hmdb_rec = {
        "compounds": [
            {
                "uci": "12345",
                "standardInchiKey": "WQZGKKKJIJFFOK-GASJEMHNSA-N",
                "sources": [],
            }
        ]
    }
    session = FakeSession(
        {
            ("GET", "/sources/"): FakeResp(200, _SOURCES),
            # both POSTs hit the same endpoint; replay by call order: chebi first, hmdb second.
            ("POST", "/api/v1/compounds"): [
                FakeResp(200, _COMPOUNDS_CHEBI_4167),
                FakeResp(200, hmdb_rec),
            ],
        }
    )
    client = UniChemClient(session=session, cache_path=None)
    judge = UniChemIdEquivalenceJudge(client)
    assert judge.uci_equivalent({"HMDB:HMDB0000122"}, {"CHEBI:4167"}) is True


def test_judge_uci_equivalence_via_sources_membership():
    # gold HMDB:HMDB0000122 is IN the prediction's (CHEBI:4167) UniChem sources set.
    session = FakeSession(
        {
            ("GET", "/sources/"): FakeResp(200, _SOURCES),
            ("POST", "/api/v1/compounds"): [
                FakeResp(200, _COMPOUNDS_CHEBI_4167),  # prediction, sources include HMDB0000122
                FakeResp(404),  # gold lookup fails, but sources already matched
            ],
        }
    )
    client = UniChemClient(session=session, cache_path=None)
    judge = UniChemIdEquivalenceJudge(client)
    assert judge.uci_equivalent({"HMDB:HMDB0000122"}, {"CHEBI:4167"}) is True


def test_judge_uci_needs_verification_when_lookup_fails_and_no_match():
    session = FakeSession(
        {
            ("GET", "/sources/"): FakeResp(200, _SOURCES),
            ("POST", "/api/v1/compounds"): FakeResp(503),  # everything fails
        }
    )
    client = UniChemClient(session=session, cache_path=None)
    judge = UniChemIdEquivalenceJudge(client)
    assert judge.uci_equivalent({"HMDB:HMDB0000122"}, {"CHEBI:4167"}) is None


def test_judge_block_bridge_matches_on_first_block():
    # Both resolve to the same InChIKey first-block via UniChem standardInchiKey.
    session = FakeSession(
        {
            ("GET", "/sources/"): FakeResp(200, _SOURCES),
            ("POST", "/api/v1/compounds"): FakeResp(200, _COMPOUNDS_CHEBI_4167),
        }
    )
    client = UniChemClient(session=session, cache_path=None)
    judge = UniChemIdEquivalenceJudge(client)
    # prediction and gold both map to WQZGKKKJIJFFOK
    assert judge.block_equivalent({"CHEBI:4167"}, {"CHEBI:4167"}) is True


def test_judge_block_bridge_falls_back_to_pubchem_resolver():
    class FakePubChem:
        def block_for_pubchem(self, cid):
            return "WQZGKKKJIJFFOK" if cid == "5793" else None

        def block_for_hmdb(self, hmdb):
            return "WQZGKKKJIJFFOK" if hmdb == "HMDB0000122" else None

    # UniChem returns no block (empty), so the judge must fall back to PubChem for the block.
    empty = {"compounds": [{"uci": "9", "standardInchiKey": "", "sources": []}]}
    session = FakeSession(
        {
            ("GET", "/sources/"): FakeResp(200, _SOURCES),
            ("POST", "/api/v1/compounds"): FakeResp(200, empty),
        }
    )
    client = UniChemClient(session=session, cache_path=None)
    judge = UniChemIdEquivalenceJudge(client, pubchem_resolver=FakePubChem())
    assert judge.block_equivalent({"HMDB:HMDB0000122"}, {"PUBCHEM:5793"}) is True
