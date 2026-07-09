"""Tests for regimes.py — retrievability + divergence tagging.

All tests are pure/synthetic: no network calls, no CSV on disk.
"""
import pytest

from studies.annotation_reranking.models_data import Candidate, EvalCase
from studies.annotation_reranking.regimes import (
    classify_regime,
    is_retrievable,
    target_id,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _c(cid: str, score: float = 1.0) -> Candidate:
    return Candidate(id=cid, score=score, name=cid)


def _case(
    refmet_id: str = "12345",
    correct_id: str | None = None,
    name: str = "test_compound",
) -> EvalCase:
    return EvalCase(
        name=name,
        level="",
        refmet_id=refmet_id,
        refmet_name="",
        biomapper_ids=[],
        biomapper_name="",
        category="",
        correct_id=correct_id,
        label_source="refmet_agreement",
    )


# ---------------------------------------------------------------------------
# target_id tests
# ---------------------------------------------------------------------------


def test_target_id_uses_correct_id_when_set():
    case = _case(refmet_id="99999", correct_id="CHEBI:00042")
    assert target_id(case) == "CHEBI:00042"


def test_target_id_falls_back_to_refmet_when_correct_id_none():
    case = _case(refmet_id="28683", correct_id=None)
    assert target_id(case) == "CHEBI:28683"


def test_target_id_strips_whitespace_from_refmet_id():
    case = _case(refmet_id="  28683  ", correct_id=None)
    assert target_id(case) == "CHEBI:28683"


def test_target_id_correct_id_takes_precedence_over_refmet():
    """correct_id wins even if refmet_id is also set."""
    case = _case(refmet_id="99999", correct_id="CHEBI:00007")
    assert target_id(case) == "CHEBI:00007"


# ---------------------------------------------------------------------------
# is_retrievable tests
# ---------------------------------------------------------------------------


def test_is_retrievable_true_when_target_present():
    case = _case(refmet_id="28683")
    candidates = [_c("CHEBI:100"), _c("CHEBI:28683"), _c("CHEBI:200")]
    assert is_retrievable(case, candidates) is True


def test_is_retrievable_false_when_target_absent():
    case = _case(refmet_id="28683")
    candidates = [_c("CHEBI:100"), _c("CHEBI:999")]
    assert is_retrievable(case, candidates) is False


def test_is_retrievable_false_when_candidates_empty():
    case = _case(refmet_id="28683")
    assert is_retrievable(case, []) is False


def test_is_retrievable_uses_correct_id_over_refmet():
    """correct_id != refmet — only correct_id matters for retrievability."""
    case = _case(refmet_id="28683", correct_id="CHEBI:99999")
    # CHEBI:28683 is present but CHEBI:99999 is not
    candidates = [_c("CHEBI:28683"), _c("CHEBI:100")]
    assert is_retrievable(case, candidates) is False


def test_is_retrievable_true_with_correct_id():
    case = _case(refmet_id="28683", correct_id="CHEBI:99999")
    candidates = [_c("CHEBI:99999"), _c("CHEBI:28683")]
    assert is_retrievable(case, candidates) is True


# ---------------------------------------------------------------------------
# classify_regime tests
# ---------------------------------------------------------------------------


def test_classify_regime_retrievable():
    case = _case(refmet_id="28683")
    candidates = [_c("CHEBI:28683"), _c("CHEBI:100")]
    assert classify_regime(case, candidates) == "retrievable"


def test_classify_regime_not_retrieved():
    case = _case(refmet_id="28683")
    candidates = [_c("CHEBI:100"), _c("CHEBI:200")]
    assert classify_regime(case, candidates) == "not_retrieved"


def test_classify_regime_empty_candidates_is_not_retrieved():
    case = _case(refmet_id="28683")
    assert classify_regime(case, []) == "not_retrieved"


def test_classify_regime_uses_correct_id():
    """classify_regime delegates to is_retrievable which uses target_id."""
    case = _case(refmet_id="28683", correct_id="CHEBI:55555")
    candidates = [_c("CHEBI:55555")]
    assert classify_regime(case, candidates) == "retrievable"
