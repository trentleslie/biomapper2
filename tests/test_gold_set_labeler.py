"""Unit tests for the non-circular InChIKey-connectivity auto-labeler.

The labeler is pure: given the query's independently-resolved InChIKey first block
and the candidate nodes' first blocks, it decides the gold node or defers to an
expert. No live APIs here — the live resolution is exercised by the runner.
"""

import json
from typing import cast

import pytest

from studies.shared_gold_set import build_gold_set as bgs
from studies.shared_gold_set.labeler import (
    EXPERT,
    INCHIKEY_AUTO,
    Candidate,
    adjudicate,
    eligibility,
    rm_blinded_view,
)


def _c(arm, curie, block):
    return Candidate(arm=arm, curie=curie, block=block)


def test_query_matches_refmet_only_labels_refmet():
    adj = adjudicate(
        "BRMWTNUJHUMWMS", [_c("A", "CHEBI:70958", "BRMWTNUJHUMWMS"), _c("B", "CHEBI:25569", "ZZZZZZZZZZZZZZ")]
    )
    assert adj.gold_curie == "CHEBI:70958"
    assert adj.adjudication_method == INCHIKEY_AUTO


def test_query_matches_biomapper_only_labels_biomapper():
    adj = adjudicate("AAAAAAAAAAAAAA", [_c("A", "CHEBI:1", "QQQQQQQQQQQQQQ"), _c("B", "CHEBI:2", "AAAAAAAAAAAAAA")])
    assert adj.gold_curie == "CHEBI:2"
    assert adj.adjudication_method == INCHIKEY_AUTO


def test_shared_connectivity_is_expert_residual():
    # Both candidates share the query's 2-D skeleton (stereo/charge/positional variant):
    # first-block connectivity cannot pick a winner -> expert.
    adj = adjudicate(
        "BRMWTNUJHUMWMS", [_c("A", "CHEBI:70958", "BRMWTNUJHUMWMS"), _c("B", "CHEBI:27596", "BRMWTNUJHUMWMS")]
    )
    assert adj.gold_curie is None
    assert adj.adjudication_method == EXPERT
    assert adj.difficulty_flag == "ambiguous_shared_connectivity"


def test_no_candidate_matches_query_is_expert():
    adj = adjudicate("BRMWTNUJHUMWMS", [_c("A", "CHEBI:1", "XXXXXXXXXXXXXX"), _c("B", "CHEBI:2", "YYYYYYYYYYYYYY")])
    assert adj.gold_curie is None
    assert adj.adjudication_method == EXPERT
    assert adj.difficulty_flag == "no_candidate_matches_query"


def test_unresolvable_query_is_expert():
    adj = adjudicate(None, [_c("A", "CHEBI:1", "XXXXXXXXXXXXXX"), _c("B", "CHEBI:2", "YYYYYYYYYYYYYY")])
    assert adj.gold_curie is None
    assert adj.adjudication_method == EXPERT
    assert adj.difficulty_flag == "query_unresolvable"


def test_multi_id_biomapper_both_match_is_expert():
    # biomapper ambiguous set "27596|50599" — both N-methyl-histidine isomers share the block.
    adj = adjudicate(
        "BRMWTNUJHUMWMS",
        [
            _c("A", "CHEBI:70958", "ZZZZZZZZZZZZZZ"),
            _c("B", "CHEBI:27596", "BRMWTNUJHUMWMS"),
            _c("B", "CHEBI:50599", "BRMWTNUJHUMWMS"),
        ],
    )
    assert adj.gold_curie is None
    assert adj.difficulty_flag == "ambiguous_shared_connectivity"
    assert adj.matched_arms == ["B"]


def test_eligibility_tracks_gated_on_auto_and_retrievable():
    assert eligibility(INCHIKEY_AUTO, True) == ["tier1", "ablation", "tbench"]
    assert eligibility(INCHIKEY_AUTO, False) == ["tier1"]  # hard-case slice but not retrievable
    assert eligibility(EXPERT, True) == []  # awaits expert adjudication


def test_rm_blinded_view_strips_refmet_identity():
    view = rm_blinded_view("1 methylhistidine", ["CHEBI:70958", "CHEBI:27596"], refmet_name="1-Methylhistidine")
    assert view["query_name"] == "1 methylhistidine"
    assert sorted(view["candidates"]) == ["CHEBI:27596", "CHEBI:70958"]  # order-independent, arm identity gone
    assert "1-Methylhistidine" not in str(view)  # RefMet canonical name withheld
    assert "A" not in view and "B" not in view  # no arm labels reveal which node is RefMet's


# --- Runner-level regressions (Greptile PR #12 review) -------------------------------------------


def test_retrievable_uses_bm_rank_when_gold_is_bm_node():
    # Gold is the BioMapper-arm node -> use bm_rank, not refmet_rank.
    probe = {"refmet_node": "CHEBI:100", "refmet_rank": 5, "bm_node": "CHEBI:200", "bm_rank": 1}
    assert bgs._retrievable("CHEBI:200", probe) is True


def test_retrievable_uses_refmet_rank_when_gold_is_refmet_node():
    probe = {"refmet_node": "CHEBI:100", "refmet_rank": 3, "bm_node": "CHEBI:200", "bm_rank": 1}
    assert bgs._retrievable("CHEBI:100", probe) is True


def test_retrievable_false_when_gold_matches_neither_probed_node():
    # Multi-ID row: adjudicated gold is a candidate the probe never ranked (probe bm_node is an
    # RM: identifier). Must NOT silently borrow refmet_rank and claim retrievable.
    probe = {"refmet_node": "CHEBI:100", "refmet_rank": 2, "bm_node": "RM:0162041", "bm_rank": 4}
    assert bgs._retrievable("CHEBI:50599", probe) is False


def test_retrievable_false_when_gold_rank_exceeds_window():
    probe = {"refmet_node": "CHEBI:100", "refmet_rank": 999, "bm_node": "CHEBI:200", "bm_rank": None}
    assert bgs._retrievable("CHEBI:100", probe) is False


def test_retrievable_false_without_probe_or_gold():
    assert bgs._retrievable("CHEBI:1", None) is False
    assert bgs._retrievable(None, {"refmet_node": "CHEBI:1", "refmet_rank": 1}) is False


def test_build_records_rejects_negative_limit():
    # Must raise before any resolver construction / network I/O.
    with pytest.raises(ValueError, match="limit must be >= 0"):
        bgs.build_records(limit=-1)


def test_write_outputs_empty_run_emits_valid_header_only_csv(tmp_path):
    # --limit 0 is now a legitimate empty run; outputs must be valid, not partial/crashed.
    bgs.write_outputs([], tmp_path, limit=0)

    csv_text = (tmp_path / "gold_set.csv").read_text()
    header = csv_text.splitlines()[0].split(",")
    assert header == bgs._CSV_FIELDNAMES  # stable header, no IndexError on flat[0]
    assert len(csv_text.splitlines()) == 1  # header only, zero data rows

    assert (tmp_path / "gold_set.jsonl").read_text() == ""
    prov = json.loads((tmp_path / "provenance.json").read_text())
    assert prov["limit"] == 0 and prov["n_pairs"] == 0  # provenance describes the actual dataset
    assert (tmp_path / "report.md").exists()  # report renders without ZeroDivisionError


# --- Package importability (Greptile PR #16: bare `import labeler` broke package import) ----------


def test_runner_imports_as_a_package_without_syspath_hacks():
    # Importing the runner via its dotted package path must succeed on its own — no sys.path
    # mutation. A bare top-level `import labeler` would raise ModuleNotFoundError here.
    import importlib

    mod = importlib.import_module("studies.shared_gold_set.build_gold_set")
    # Its labeler dependency resolved (as a package member, not a bare top-level module).
    assert mod.INCHIKEY_AUTO == "inchikey_auto"
    assert mod.EXPERT == "expert"


# --- Resolution-outage fail-loud guard (Greptile PR #16: outage silently -> fake gold set) --------


class _FakeLinker:
    """No-op stand-in so build_records does no KG network I/O in tests."""

    def __init__(self, *a, **k):
        pass

    @staticmethod
    def get_node_records(curies):
        return {}


def _fake_resolver_factory(block_for):
    """Build a StructureResolver stand-in whose inchikey_block returns block_for(node_name)."""

    class _FakeResolver:
        def __init__(self, *a, **k):
            pass

        def inchikey_block(self, node_id, node_name, records=None):
            return block_for(node_name)

    return _FakeResolver


def test_resolution_canary_raises_on_service_outage():
    # Every lookup returns None (services down) -> canary must abort with an actionable message.
    resolver = _fake_resolver_factory(lambda name: None)()
    with pytest.raises(RuntimeError, match="canary FAILED"):
        bgs._resolution_canary(cast(bgs.StructureResolver, resolver))


def test_resolution_canary_passes_when_known_metabolite_resolves():
    # Caffeine resolves to its known first block -> canary is silent (no raise).
    resolver = _fake_resolver_factory(
        lambda name: bgs.CANARY_INCHIKEY_BLOCK if name == bgs.CANARY_NAME else None
    )()
    bgs._resolution_canary(cast(bgs.StructureResolver, resolver))  # must not raise


def test_build_records_aborts_and_writes_nothing_on_resolution_outage(monkeypatch, tmp_path):
    # Simulated outage: the canary fails, so build_records raises BEFORE producing records and
    # main() never reaches write_outputs -> no gold set is persisted.
    monkeypatch.setattr(bgs, "Linker", _FakeLinker)
    monkeypatch.setattr(bgs, "StructureResolver", _fake_resolver_factory(lambda name: None))

    with pytest.raises(RuntimeError, match="ABORTING before writing"):
        bgs.build_records(limit=3)

    # Nothing was written (build_records aborted; write_outputs was never called).
    assert list(tmp_path.iterdir()) == []


def test_healthy_run_with_genuinely_unresolvable_pairs_still_succeeds(monkeypatch, tmp_path):
    # Canary passes (caffeine resolves) but the real pairs are genuinely unresolvable. This is a
    # legitimate expert-residual outcome, NOT an outage: build_records must succeed (not abort) and
    # write_outputs must emit a valid gold set. Distinguishes 'service down' from 'hard pair'.
    monkeypatch.setattr(bgs, "Linker", _FakeLinker)
    monkeypatch.setattr(
        bgs,
        "StructureResolver",
        _fake_resolver_factory(lambda name: bgs.CANARY_INCHIKEY_BLOCK if name == bgs.CANARY_NAME else None),
    )

    records = bgs.build_records(limit=3)
    assert len(records) == 3
    # Every pair is a genuine expert residual, not a crash.
    assert all(r["adjudication_method"] == EXPERT for r in records)
    assert all(r["difficulty_flag"] == "query_unresolvable" for r in records)

    bgs.write_outputs(records, tmp_path, limit=3)
    assert len((tmp_path / "gold_set.jsonl").read_text().splitlines()) == 3
    assert (tmp_path / "report.md").exists()
