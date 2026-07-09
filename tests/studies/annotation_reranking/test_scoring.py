import math
import pytest
from studies.annotation_reranking.scoring import wilson_ci, mcnemar_exact, min_discordant_for_sig, accuracy
from studies.annotation_reranking.models_data import RerankResult


def _make_result(is_correct, regime):
    return RerankResult(
        case_name="x", reranker="r", model=None,
        selected_id="CHEBI:1", correct_id="CHEBI:1",
        label_source="independent_biomapper_error",
        regime=regime, is_correct=is_correct,
        cost_usd=0.0, latency_s=0.0,
    )


def test_wilson_ci_bounds_are_ordered_and_in_unit_interval():
    lo, hi = wilson_ci(1, 13)
    assert 0.0 <= lo < hi <= 1.0


def test_mcnemar_all_discordant_one_direction_is_significant():
    a = [True]*6 + [False]*7   # model A correct on 6 where B wrong
    b = [False]*6 + [False]*7
    b01, b10, p = mcnemar_exact(a, b)
    assert b10 == 6 and b01 == 0
    assert p < 0.05


def test_mcnemar_small_delta_not_significant():
    a = [True, True, False, False]
    b = [False, True, True, False]   # 1 vs 1 discordant
    _, _, p = mcnemar_exact(a, b)
    assert p > 0.05


def test_min_discordant_threshold_matches_doc_claim():
    # the "≥6 discordant pairs to clear p<0.05" fact the design doc cites
    assert min_discordant_for_sig(6) <= 6
    assert min_discordant_for_sig(4) > 4   # 4 discordant can't reach significance


def test_accuracy_retrievable_only_filters_non_retrievable():
    """retrievable_only=True must exclude non-retrievable cases from the denominator."""
    # 3 scored cases: 1 correct+retrievable, 1 wrong+retrievable, 1 wrong+not_in_top_n
    results = [
        _make_result(True,  "retrievable"),      # correct & retrievable
        _make_result(False, "retrievable"),      # wrong & retrievable
        _make_result(False, "not_in_top_n"),     # wrong & non-retrievable
        _make_result(None,  "retrievable"),      # unscored — always excluded
    ]
    # Without retrievable_only: 1 correct out of 3 scored = 1/3
    point_all, _ = accuracy(results)
    assert point_all == pytest.approx(1 / 3)

    # With retrievable_only: non-retrievable wrong case excluded → 1 correct out of 2 = 0.5
    point_retr, _ = accuracy(results, retrievable_only=True)
    assert point_retr == 0.5

    # Also verify: non-retrievable correct case is excluded when flag is set.
    results_with_unreachable = results + [_make_result(True, "not_in_top_n")]
    point_all2, _ = accuracy(results_with_unreachable)
    assert point_all2 == pytest.approx(2 / 4)   # 2 correct out of 4 scored

    point_retr2, _ = accuracy(results_with_unreachable, retrievable_only=True)
    assert point_retr2 == 0.5   # non-retrievable correct case excluded; still 1/2
