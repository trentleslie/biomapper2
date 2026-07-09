"""Tests for deterministic rerankers: top1, rm_anchor, source_weight_guard."""
from unittest.mock import MagicMock

import pytest

from studies.annotation_reranking.models_data import Candidate, EvalCase
from studies.annotation_reranking.rerankers.deterministic import (
    RmAnchorReranker,
    SourceWeightGuardReranker,
    Top1Reranker,
)


def _c(cid, score, rm):
    return Candidate(id=cid, score=score, name=cid, equivalent_ids=(["RM:1"] if rm else []))


def _case(refmet_id, refmet_name=""):
    return EvalCase(
        name="test",
        level="",
        refmet_id=refmet_id,
        refmet_name=refmet_name,
        biomapper_ids=[],
        biomapper_name="",
        category="",
        correct_id=None,
        label_source="",
    )


# ---------------------------------------------------------------------------
# top1 tests
# ---------------------------------------------------------------------------


def test_top1_picks_highest_score():
    cands = [_c("CHEBI:2", 4.9, False), _c("CHEBI:9", 3.1, True)]
    assert Top1Reranker().select(cands)[0] == "CHEBI:2"


def test_top1_empty_returns_none():
    selected_id, review_flag = Top1Reranker().select([])
    assert selected_id is None and review_flag is None


def test_top1_returns_none_review_flag():
    cands = [_c("CHEBI:2", 4.9, False)]
    selected_id, review_flag = Top1Reranker().select(cands)
    assert review_flag is None


def test_top1_ignores_case():
    cands = [_c("CHEBI:2", 4.9, False), _c("CHEBI:9", 3.1, True)]
    case = _case("28683")
    assert Top1Reranker().select(cands, case=case)[0] == "CHEBI:2"


# ---------------------------------------------------------------------------
# rm_anchor tests
# ---------------------------------------------------------------------------


def test_rm_anchor_prefers_rm_bearing_even_if_lower_score():
    cands = [_c("CHEBI:2", 4.9, False), _c("CHEBI:9", 3.1, True)]
    assert RmAnchorReranker().select(cands)[0] == "CHEBI:9"


def test_rm_anchor_falls_back_to_top_score_when_no_rm():
    cands = [_c("CHEBI:2", 4.9, False), _c("CHEBI:3", 3.1, False)]
    assert RmAnchorReranker().select(cands)[0] == "CHEBI:2"


def test_rm_anchor_breaks_ties_deterministically():
    # two RM-bearing candidates → lowest CURIE string wins (stable, reproducible)
    cands = [_c("CHEBI:50", 2.0, True), _c("CHEBI:27", 2.0, True)]
    assert RmAnchorReranker().select(cands)[0] == "CHEBI:27"


def test_rm_anchor_empty_returns_none():
    selected_id, review_flag = RmAnchorReranker().select([])
    assert selected_id is None and review_flag is None


def test_rm_anchor_returns_none_review_flag():
    cands = [_c("CHEBI:2", 4.9, False), _c("CHEBI:9", 3.1, True)]
    selected_id, review_flag = RmAnchorReranker().select(cands)
    assert review_flag is None


def test_rm_anchor_ignores_case():
    cands = [_c("CHEBI:2", 4.9, False), _c("CHEBI:9", 3.1, True)]
    case = _case("28683")
    assert RmAnchorReranker().select(cands, case=case)[0] == "CHEBI:9"


# ---------------------------------------------------------------------------
# source_weight_guard tests
# ---------------------------------------------------------------------------


def test_swg_empty_candidates():
    mock_fn = MagicMock()
    r = SourceWeightGuardReranker(mock_fn)
    result = r.select([])
    assert result == (None, "empty_candidates")
    mock_fn.assert_not_called()


def test_swg_refmet_not_among_candidates():
    """refmet_id present in case but no matching CURIE in candidates → return majority, no flag."""
    mock_fn = MagicMock()
    r = SourceWeightGuardReranker(mock_fn)
    cands = [_c("CHEBI:100", 4.0, False), _c("CHEBI:200", 3.0, False)]
    case = _case("999")  # CHEBI:999 not in candidates
    result = r.select(cands, case=case)
    assert result == ("CHEBI:100", None)
    mock_fn.assert_not_called()


def test_swg_connectivity_true_returns_refmet_no_flag():
    """refmet present, connectivity returns True → silent refmet preference."""
    mock_fn = MagicMock(return_value=True)
    r = SourceWeightGuardReranker(mock_fn)
    cands = [_c("CHEBI:100", 4.9, False), _c("CHEBI:28683", 3.1, False)]
    case = _case("28683")  # refmet_id → CHEBI:28683
    result = r.select(cands, case=case)
    assert result == ("CHEBI:28683", None)


def test_swg_connectivity_false_returns_refmet_with_flag():
    """refmet present, connectivity returns False → flag divergent_refmet."""
    mock_fn = MagicMock(return_value=False)
    r = SourceWeightGuardReranker(mock_fn)
    cands = [_c("CHEBI:100", 4.9, False), _c("CHEBI:28683", 3.1, False)]
    case = _case("28683")
    result = r.select(cands, case=case)
    assert result == ("CHEBI:28683", "divergent_refmet")


def test_swg_connectivity_none_returns_majority_with_flag():
    """refmet present, connectivity returns None → keep majority + conflict flag."""
    mock_fn = MagicMock(return_value=None)
    r = SourceWeightGuardReranker(mock_fn)
    cands = [_c("CHEBI:100", 4.9, False), _c("CHEBI:28683", 3.1, False)]
    case = _case("28683")
    result = r.select(cands, case=case)
    assert result == ("CHEBI:100", "conflict_no_structure")


def test_swg_case_none_returns_majority_no_connectivity_call():
    """case=None → return majority, never call connectivity_fn."""
    mock_fn = MagicMock()
    r = SourceWeightGuardReranker(mock_fn)
    cands = [_c("CHEBI:100", 4.9, False), _c("CHEBI:200", 3.0, False)]
    result = r.select(cands, case=None)
    assert result == ("CHEBI:100", None)
    mock_fn.assert_not_called()


def test_swg_refmet_is_majority_returns_majority_no_connectivity_call():
    """refmet present and IS the highest-scoring → return majority, no connectivity call."""
    mock_fn = MagicMock()
    r = SourceWeightGuardReranker(mock_fn)
    # CHEBI:28683 has highest score — it's both refmet and majority
    cands = [_c("CHEBI:28683", 4.9, False), _c("CHEBI:100", 3.0, False)]
    case = _case("28683")
    result = r.select(cands, case=case)
    assert result == ("CHEBI:28683", None)
    mock_fn.assert_not_called()


def test_swg_refmet_id_with_whitespace_matches_candidate():
    """Padded refmet_id (raw CSV field) still matches via .strip() before CURIE build."""
    mock_fn = MagicMock(return_value=True)
    r = SourceWeightGuardReranker(mock_fn)
    cands = [_c("CHEBI:100", 4.9, False), _c("CHEBI:28683", 3.1, False)]
    # refmet_id has leading/trailing whitespace — simulates raw CSV field
    case = _case(" 28683 ")
    result = r.select(cands, case=case)
    assert result == ("CHEBI:28683", None)
