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
    blended = {"comparable_core": {"coverage": {"fraction": 0.95}}}
    assert capability_resolvability(blended, regime="shorthand") == 0.95


def test_assert_floor_passes_when_above():
    assert_capability_floor(_result(0.97), floor=0.90, regime="shorthand")  # no raise


def test_assert_floor_raises_when_below():
    with pytest.raises(ValueError, match="regression floor"):
        assert_capability_floor(_result(0.40), floor=0.90, regime="shorthand")
