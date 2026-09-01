"""Unit 3 — Arm-B baseline reconstruction (offline, fixture name lists + refmet maps)."""

from __future__ import annotations

import pytest

from studies.external_benchmarks.scorers.arm_b_baseline import (
    arm_b_overlap,
    name_match_overlap,
    refmet_join_overlap,
)


def test_name_match_case_insensitive():
    m = name_match_overlap(["Glucose", "Citrate"], ["glucose", "urea"], case_sensitive=False)
    assert m == {"glucose"}


def test_name_match_case_sensitive_does_not_fold():
    m = name_match_overlap(["Glucose"], ["glucose"], case_sensitive=True)
    assert m == set()


def test_refmet_drops_non_standardizing_before_join():
    # "mystery" has no RefMet mapping → dropped before the join, cannot match.
    a = ["alpha-D-glucose", "mystery"]
    b = ["D-glucose", "mystery"]
    refmet = {"alpha-D-glucose": "Glucose", "D-glucose": "Glucose"}  # "mystery" absent → dropped
    assert refmet_join_overlap(a, b, refmet) == {"glucose"}


def test_refmet_matches_via_shared_standard_name():
    a, b = ["raw_a"], ["raw_b"]
    refmet = {"raw_a": "Taurine", "raw_b": "Taurine"}
    assert refmet_join_overlap(a, b, refmet) == {"taurine"}


def test_dispatch_selects_method_per_cohort():
    r_ar = arm_b_overlap("arivale", ["Glucose"], ["glucose"])  # case-insensitive name
    r_xu = arm_b_overlap("xuetal", ["Glucose"], ["glucose"])  # case-sensitive name
    r_llfs = arm_b_overlap("llfs", ["a"], ["b"], refmet_map={"a": "X", "b": "X"})  # refmet
    assert r_ar.count == 1 and "case-insensitive" in r_ar.method
    assert r_xu.count == 0 and "case-sensitive" in r_xu.method
    assert r_llfs.count == 1 and "RefMet" in r_llfs.method


def test_unknown_cohort_fails_loud():
    with pytest.raises(ValueError):
        arm_b_overlap("mystery_cohort", ["a"], ["a"])


def test_refmet_cohort_without_map_fails_loud():
    with pytest.raises(ValueError):
        arm_b_overlap("llfs", ["a"], ["a"])  # no refmet_map


def test_gap_to_monti_published_is_recorded():
    r = arm_b_overlap("arivale", ["Glucose"], ["glucose"])
    assert r.published == 615 and r.gap == 1 - 615  # the error bar recovery must exceed
