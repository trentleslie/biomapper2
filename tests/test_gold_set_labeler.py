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
