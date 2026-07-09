import math
from studies.annotation_reranking.scoring import wilson_ci, mcnemar_exact, min_discordant_for_sig


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
