"""Case-robust name lookup: spellings that differ only in case must resolve identically.

The defect: RefMet ``/match`` and Goslin read metabolite names case-sensitively, so NECS's lower-cased
"acetylcarnitine (c2)" and Xu's "acetylcarnitine (C2)" received different annotator votes, resolved to
different KG nodes, and never linked across cohorts (21 Monti pairs in the pinned 1.5.3 / kg 2.3.0 run).

Offline only: RefMet ``/match`` answers are replayed from ``fixtures/case_split_monti_pairs.json``
(recorded live), and Goslin runs locally.
"""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from circuitbreaker import CircuitBreakerMonitor

from biomapper2.core.annotators.base import AVAILABILITY_NO_MATCH, AVAILABILITY_UNAVAILABLE, AVAILABILITY_VOTED
from biomapper2.core.annotators.goslin_lipid import GoslinLipidAnnotator
from biomapper2.core.annotators.metabolomics_workbench import MetabolomicsWorkbenchAnnotator
from biomapper2.core.name_case import canonical_case_variant, canonical_query
from biomapper2.core.resolver import Resolver
from biomapper2.core.structure_resolver import StructureResolver

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "case_split_monti_pairs.json").read_text())
PAIRS = FIXTURE["pairs"]
RECORDED = FIXTURE["refmet_match_responses"]
_BREAKER_NAME = "MetabolomicsWorkbenchAnnotator._do_refmet_request"


@pytest.fixture(autouse=True)
def _reset_breaker():
    breaker = CircuitBreakerMonitor.get(_BREAKER_NAME)
    if breaker is not None:
        breaker.reset()
    yield
    if breaker is not None:
        breaker.reset()


class _Resp:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status
        self.from_cache = False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        return self._payload


class _ReplaySession:
    """Serves recorded RefMet /match answers; an unrecorded query is a RefMet no-match ("-")."""

    NO_MATCH = {"refmet_id": "-", "refmet_name": "-"}

    def __init__(self, responses: dict[str, Any], status: int = 200) -> None:
        self._responses = responses
        self._status = status
        self.queries: list[str] = []

    def get(self, url: str, timeout: float | None = None) -> _Resp:  # noqa: ARG002
        name = urllib.parse.unquote(url.split("/refmet/match/", 1)[1])
        self.queries.append(name)
        return _Resp(self._responses.get(name, self.NO_MATCH), status=self._status)


def _mw(session: _ReplaySession, monkeypatch: pytest.MonkeyPatch) -> MetabolomicsWorkbenchAnnotator:
    ann = MetabolomicsWorkbenchAnnotator(freeze_mode="off", sleep=lambda _s: None, max_retries=0)
    monkeypatch.setattr(ann, "_session", session)
    return ann


def _refmet_id(ann: MetabolomicsWorkbenchAnnotator, name: str) -> str | None:
    result = ann._fetch_refmet_data(name)
    return (result.data or {}).get("refmet_id") if result.status == AVAILABILITY_VOTED else None


class _RecordingBinder:
    """Goslin's RefMet binder stand-in: records the canonical level names Goslin queried."""

    slug = "metabolomics-workbench"

    def __init__(self) -> None:
        self.seen: list[str] = []

    def get_annotations(self, entity, name_field, category, prefixes=None, **kwargs):  # noqa: ARG002
        self.seen.append(entity.get(name_field))
        return {self.slug: {}}


def _goslin_queries(name: str) -> list[str]:
    binder = _RecordingBinder()
    ann = GoslinLipidAnnotator(binder=binder)  # pyright: ignore[reportArgumentType]
    ann.get_annotations({"name": name}, name_field="name", category="biolink:SmallMolecule")
    return binder.seen


# -- 1. the two named examples: identical votes and the same chosen_kg_id ---------------------------


@pytest.mark.parametrize(
    "lower,upper",
    [("acetylcarnitine (c2)", "acetylcarnitine (C2)"), ("12,13-dihome", "12,13-DiHOME")],
)
def test_case_variants_get_identical_refmet_votes(lower: str, upper: str, monkeypatch: pytest.MonkeyPatch):
    ann = _mw(_ReplaySession(RECORDED), monkeypatch)
    votes_lower = ann.get_annotations({"name": lower}, name_field="name", category="biolink:SmallMolecule")
    votes_upper = ann.get_annotations({"name": upper}, name_field="name", category="biolink:SmallMolecule")
    assert votes_lower == votes_upper
    assert votes_upper[ann.slug]  # a real vote, not two empty ones


def test_dihome_case_variants_reach_the_same_goslin_parse():
    queried = _goslin_queries("12,13-DiHOME")
    assert queried  # it parsed and bound
    assert _goslin_queries("12,13-dihome") == queried


def _resolver(stereo: bool) -> Resolver:
    """Real Resolver, same connectivity for every pair, fixed stereo verdict; small molecule = True."""
    r = Resolver(linker=MagicMock(), biolink_client=MagicMock())
    r.structure_resolver = MagicMock()
    r.structure_resolver.connectivity_match.return_value = True
    r.structure_resolver.stereo_differs.return_value = stereo
    r._is_small_molecule = lambda category: category == "biolink:SmallMolecule"  # type: ignore[method-assign]
    return r


def _chosen(refmet_vote: str | None) -> tuple[str | None, str | None]:
    """Run the REAL vote with the recorded acetylcarnitine inputs.

    Kestrel hybrid search returns HMDB:HMDB0000201 for both spellings (verified live); RefMet adds its
    node only when it votes. Same connectivity, so source-weighting moves the choice to RefMet's node.
    """
    kg_ids = {"HMDB:HMDB0000201": ["HMDB:HMDB0000201"]}
    assigned: dict[str, dict[str, list[str]]] = {"kestrel-hybrid-search": {"HMDB:HMDB0000201": ["HMDB:HMDB0000201"]}}
    if refmet_vote:
        node = f"RM:{refmet_vote.removeprefix('RM')}"
        kg_ids[node] = [node]
        assigned["metabolomics-workbench"] = {node: [node]}
    return _resolver(stereo=False)._choose_best_kg_id(kg_ids, assigned, "biolink:SmallMolecule")


def test_acetylcarnitine_case_variants_choose_the_same_kg_id(monkeypatch: pytest.MonkeyPatch):
    ann = _mw(_ReplaySession(RECORDED), monkeypatch)
    chosen_lower = _chosen(_refmet_id(ann, "acetylcarnitine (c2)"))
    chosen_upper = _chosen(_refmet_id(ann, "acetylcarnitine (C2)"))
    assert chosen_lower == chosen_upper == ("RM:0154009", None)


# -- 2. case invariance over a panel, with must-not-fold negative controls --------------------------

INVARIANCE_PANEL = [
    "acetylcarnitine (c2)",
    "3-hydroxyisovalerylcarnitine (c5-oh)",
    "glutarylcarnitine (c5-dc)",
    "1-(1-enyl-palmitoyl)-gpc (p-16:0)*",
    "1-linolenoyl-gpc (18:3)*",
    "1-palmitoyl-gpe (16:0)",
    "12,13-dihome",
    "12-hete",
    "14,15-eet",
    "9-hode",
    "glucose",
]


def _case_variants(name: str) -> list[str]:
    return [name, name.upper(), name.lower(), name.title(), name.swapcase()]


@pytest.mark.parametrize("name", INVARIANCE_PANEL)
def test_every_casing_of_a_name_yields_the_same_first_query(name: str):
    first_queries = {canonical_query(v) or v for v in _case_variants(name)}
    # Either every casing sends the same canonical query, or (no recognized notation) each is sent as given.
    canon = {canonical_case_variant(v) for v in _case_variants(name)}
    assert len(canon) == 1
    if canonical_query(name) is not None:
        assert len(first_queries) == 1


MUST_NOT_FOLD = [
    "c1ccccc1",  # SMILES: lower case marks aromatic atoms
    "C1=CC=CC=C1",
    "CC(=O)OC1=CC=CC=C1C(=O)O",
    "InChI=1S/C9H17NO4/c1-7(11)14-8(5-9(12)13)6-10(2,3)4/h8H,5-6H2,1-4H3/t8-/m1/s1",
    "RDHQFKQIGNGIED-MRVPVSSYSA-N",  # InChIKey
    "HMDB:HMDB0000201",  # CURIE
    "D-glucose",  # configuration
    "L-carnitine (c2)",  # stereo marker wins over the chain notation: never rewritten
    "12(S)-HETE",
    "(2S,3R)-2-amino-3-hydroxybutanoate",
    "N-acetylglycine",  # locant
    "S-adenosylmethionine",
    "PC O-16:0/18:1",  # ether letter outside the parenthetical pattern
    "TP53",  # gene symbol
    "Trp53",
    "CoA",  # element-like case
]


@pytest.mark.parametrize("name", MUST_NOT_FOLD)
def test_case_meaningful_names_are_never_rewritten(name: str):
    assert canonical_query(name) is None


@pytest.mark.parametrize("name", ["c1ccccc1", "C1=CC=CC=C1", "RDHQFKQIGNGIED-MRVPVSSYSA-N"])
def test_a_smiles_or_inchikey_is_queried_with_its_case_exactly(name: str, monkeypatch: pytest.MonkeyPatch):
    session = _ReplaySession({})
    ann = _mw(session, monkeypatch)
    assert ann._fetch_refmet_data(name).status == AVAILABILITY_NO_MATCH
    assert session.queries == [name]


def test_the_canonical_query_is_issued_once_per_batch(monkeypatch: pytest.MonkeyPatch):
    session = _ReplaySession(RECORDED)
    ann = _mw(session, monkeypatch)
    cache = ann._fetch_all(["acetylcarnitine (c2)", "acetylcarnitine (C2)", "Acetylcarnitine (c2)"])
    assert {(r.data or {}).get("refmet_id") for r in cache.values()} == {"RM0154009"}
    assert session.queries.count("acetylcarnitine (C2)") == 1


def test_an_outage_is_not_retried_with_the_raw_spelling(monkeypatch: pytest.MonkeyPatch):
    session = _ReplaySession({}, status=503)
    ann = _mw(session, monkeypatch)
    assert ann._fetch_refmet_data("acetylcarnitine (c2)").status == AVAILABILITY_UNAVAILABLE
    assert session.queries == ["acetylcarnitine (C2)"]


# -- 3. the stereo review flag ------------------------------------------------------------------------


def _source_weighted(stereo: bool) -> tuple[str | None, str | None]:
    r = _resolver(stereo=stereo)
    kg_ids = {"HMDB:HMDB0000201": ["a", "b"], "RM:0154009": ["RM:0154009"]}
    assigned = {"metabolomics-workbench": {"RM:0154009": ["RM:0154009"]}}
    return r._choose_best_kg_id(kg_ids, assigned, "biolink:SmallMolecule")


def test_same_connectivity_different_stereo_is_flagged_and_the_choice_is_unchanged():
    assert _source_weighted(stereo=True) == ("RM:0154009", "stereo_divergent_refmet")
    assert _source_weighted(stereo=False) == ("RM:0154009", None)


def _structure_resolver(records: dict[str, list[str]]) -> StructureResolver:
    sr = StructureResolver.__new__(StructureResolver)
    sr.linker = MagicMock()
    sr.linker.get_node_records = lambda ids: {n: {"equivalent_ids": {"INCHIKEY": records.get(n, [])}} for n in ids}
    return sr


def test_stereo_differs_reads_the_first_two_inchikey_blocks():
    acetyl = {
        "HMDB:HMDB0000201": ["RDHQFKQIGNGIED-MRVPVSSYSA-N"],  # graph-asserted, recorded live
        "RM:0154009": ["RDHQFKQIGNGIED-QMMMGPOBSA-N"],
    }
    assert _structure_resolver(acetyl).stereo_differs("HMDB:HMDB0000201", "RM:0154009") is True
    shared = {"A": ["RDHQFKQIGNGIED-MRVPVSSYSA-N", "X-Y-N"], "B": ["RDHQFKQIGNGIED-MRVPVSSYSA-M"]}
    assert _structure_resolver(shared).stereo_differs("A", "B") is False  # protonation block ignored
    assert _structure_resolver({"A": ["RDHQFKQIGNGIED-MRVPVSSYSA-N"]}).stereo_differs("A", "B") is False


# -- 4. regression fixture: the 21 Monti pairs the pinned run split -----------------------------------


@pytest.mark.parametrize("pair", PAIRS, ids=[f"{p['cohort']}:{p['necs_name']}" for p in PAIRS])
def test_monti_pair_gets_the_same_refmet_answer_and_the_same_goslin_parse(pair, monkeypatch: pytest.MonkeyPatch):
    ann = _mw(_ReplaySession(RECORDED), monkeypatch)
    assert _refmet_id(ann, pair["necs_name"]) == _refmet_id(ann, pair["other_name"])
    assert _goslin_queries(pair["necs_name"]) == _goslin_queries(pair["other_name"])
