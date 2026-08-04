import pytest

from studies.external_benchmarks.config import LMSD
from studies.external_benchmarks.scorers.regression import (
    assert_capability_floor,
    capability_resolvability,
)


def _result(shorthand_fraction):
    return {
        "comparable_core": {"top1_accuracy": 0.5, "coverage": {"fraction": shorthand_fraction}},
        "by_name_source_regime": {
            "shorthand": {"coverage": {"fraction": shorthand_fraction, "n_predicted": 90, "total": 100}},
            "common_systematic": {"coverage": {"fraction": 1.0}},
        },
    }


def test_lmsd_is_relabelled_capability_regression():
    assert LMSD.role == "capability_regression"
    assert LMSD.regression_floor == 0.90


def test_capability_resolvability_reads_shorthand_regime():
    assert capability_resolvability(_result(0.97), regime="shorthand") == 0.97


def test_capability_resolvability_is_none_when_regime_absent():
    # The capability gate is regime-specific: a regime-less result must NOT fall back to blended
    # coverage (a high non-shorthand number could otherwise satisfy the shorthand floor). It returns
    # None ("no observations"), even when a high blended coverage is present at the result root.
    blended_only = {
        "vocab": "CHEBI",
        "comparable_core": {"metric": "top1_accuracy", "top1_accuracy": 0.5, "scored_denominator": 2},
        "coverage": {"n_predicted": 95, "total": 100, "fraction": 0.95},
    }
    assert capability_resolvability(blended_only, regime="shorthand") is None


def test_capability_resolvability_is_none_when_regime_empty():
    # A present-but-zero-observation shorthand regime is also "no observations".
    empty_regime = {
        "by_name_source_regime": {"shorthand": {"coverage": {"fraction": 0.0, "n_predicted": 0, "total": 0}}},
        "coverage": {"fraction": 0.95},
    }
    assert capability_resolvability(empty_regime, regime="shorthand") is None


def test_gate_fails_closed_when_no_shorthand_observations():
    # Greptile P1: high blended (non-shorthand) coverage must NOT satisfy the shorthand floor when
    # the shorthand regime is absent — the capability arm measured nothing in its target class.
    blended_only = {
        "vocab": "CHEBI",
        "comparable_core": {"metric": "top1_accuracy", "top1_accuracy": 0.5, "scored_denominator": 2},
        "coverage": {"n_predicted": 95, "total": 100, "fraction": 0.95},
    }
    with pytest.raises(ValueError, match="no 'shorthand' observations"):
        assert_capability_floor(blended_only, floor=0.90, regime="shorthand")


def test_assert_floor_passes_when_above():
    assert_capability_floor(_result(0.97), floor=0.90, regime="shorthand")  # no raise


def test_assert_floor_raises_when_below():
    with pytest.raises(ValueError, match="regression floor"):
        assert_capability_floor(_result(0.40), floor=0.90, regime="shorthand")
