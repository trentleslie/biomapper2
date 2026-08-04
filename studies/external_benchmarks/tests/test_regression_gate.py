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


def test_capability_resolvability_falls_back_to_blended_when_no_regime():
    # Coverage lives at the RESULT ROOT in the production score_structure_oracle output — NOT under
    # comparable_core. A regime-less result must fall back to result["coverage"], never KeyError.
    blended = {"comparable_core": {"top1_accuracy": 0.5}, "coverage": {"fraction": 0.95}}
    assert capability_resolvability(blended, regime="shorthand") == 0.95


def test_capability_resolvability_regime_less_production_shape_does_not_crash():
    # Regression for the fallback: a production-shaped result with no by_name_source_regime and
    # coverage only at the root must resolve via the root, not raise under comparable_core.
    production_like = {
        "vocab": "CHEBI",
        "comparable_core": {"metric": "top1_accuracy", "top1_accuracy": 0.5, "scored_denominator": 2},
        "coverage": {"n_predicted": 5, "total": 100, "fraction": 0.05},
    }
    assert capability_resolvability(production_like, regime="shorthand") == 0.05
    with pytest.raises(ValueError, match="regression floor"):
        assert_capability_floor(production_like, floor=0.90, regime="shorthand")


def test_assert_floor_passes_when_above():
    assert_capability_floor(_result(0.97), floor=0.90, regime="shorthand")  # no raise


def test_assert_floor_raises_when_below():
    with pytest.raises(ValueError, match="regression floor"):
        assert_capability_floor(_result(0.40), floor=0.90, regime="shorthand")
