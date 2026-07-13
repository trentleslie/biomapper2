"""Unit tests for the non-circular InChIKey-connectivity auto-labeler.

The labeler is pure: given the query's independently-resolved InChIKey first block
and the candidate nodes' first blocks, it decides the gold node or defers to an
expert. No live APIs here — the live resolution is exercised by the runner.
"""

import sys
from pathlib import Path

# The study lives outside the installed package; make it importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "studies" / "shared_gold_set"))

from labeler import (  # noqa: E402
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

import json  # noqa: E402

import build_gold_set as bgs  # noqa: E402
import pytest  # noqa: E402


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
