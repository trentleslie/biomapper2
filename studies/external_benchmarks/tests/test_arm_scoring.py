"""Unit 4 (pure-logic) — frozen score, both metrics, refusal monotonicity, anti-pooling guard."""

from __future__ import annotations

import pytest

from studies.external_benchmarks.scorers.arm_scoring import (
    PairScore,
    PooledRateError,
    pooled_rate,
    refusal_sensitive_score,
)


def _pair(**kw) -> PairScore:
    base = dict(cohort="arivale", asserted=10, certified=8, refused=0, comparable=10,
                mode="reproduction", certifiable=True)
    base.update(kw)
    return PairScore(**base)  # type: ignore[arg-type]


def test_score_is_certified_over_comparable():
    assert refusal_sensitive_score(8, 10) == 0.8
    assert _pair().score == 0.8


def test_zero_comparable_is_zero_not_divide_error():
    assert refusal_sensitive_score(0, 0) == 0.0
    assert _pair(certified=0, comparable=0).score == 0.0


def test_refusing_uncertified_link_does_not_raise_score():
    # Move an asserted-but-uncertified link to refused: certified & comparable unchanged → same score.
    before = _pair(asserted=10, certified=8, refused=0, comparable=10).score
    after = _pair(asserted=9, certified=8, refused=1, comparable=10).score
    assert after == before  # refusing cannot raise the score (denominator fixed)


def test_refusing_certified_link_strictly_lowers_score():
    # Refusing a CERTIFIED link removes it from the numerator only → score strictly drops.
    before = _pair(certified=8, comparable=10).score
    after = _pair(certified=7, refused=1, comparable=10).score
    assert after < before


def test_both_metrics_reported_together():
    m = _pair(asserted=10, certified=8, comparable=16).metrics
    assert m["certified_over_comparable"] == 0.5
    assert m["certified_over_asserted"] == 0.8


def test_raw_counts_always_present():
    assert _pair().raw_counts == {"asserted": 10, "certified": 8, "refused": 0, "comparable": 10}


def test_pooled_rate_is_refused_positive_control():
    # The anti-pooling guard must FIRE on a mixed Arivale(reproduction)+BLSA(counts_only) aggregate.
    scores = [
        _pair(cohort="arivale", mode="reproduction"),
        _pair(cohort="blsa", mode="counts_only", certifiable=False),
    ]
    with pytest.raises(PooledRateError):
        pooled_rate(scores)


def test_mode_and_certifiable_tags_carried():
    p = _pair(cohort="blsa", mode="counts_only", certifiable=False)
    assert p.mode == "counts_only" and p.certifiable is False
