"""Regression (Greptile #62): the positive-control self-test scopes to the PLANT's own population.

The synthetic plant's forced-conflation pairs are generally NOT members of the baseline/treatment
RefMet-parity-kept set. Scoping the self-test through that kept set (the bug) drops the planted
refutations, so the gate wrongly ABORTs (or clears on a spurious certified-fall) instead of proving the
plant's refutations are detectable. This test plants a refutation on a pair OUTSIDE `kept` and asserts
the gate detects it (no ABORT) — it fails if the population fix is reverted.
"""

from __future__ import annotations

import socket

import pytest

from studies.external_benchmarks.conflation_gate import (
    ArmReplicates,
    Prereg,
    Thresholds,
    evaluate_conflation_gate,
)
from studies.external_benchmarks.cross_cohort_devapi_sweep import ArmScore
from studies.external_benchmarks.scorers.cross_cohort_overlap import OverlapResult
from studies.external_benchmarks.scorers.independent_link_certificate_overlap import CertifiedOverlap


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _blocked(*a, **k):
        raise AssertionError("network access in a pure gate test — must be offline")

    monkeypatch.setattr(socket.socket, "connect", _blocked)


_EMPTY_OV = OverlapResult(links=(), n_links=0, n_a_linked=0, n_b_linked=0, n_a_comparable=0, n_b_comparable=0)


def _score(certified: int, refuted: int, refused: int, per_link=()) -> ArmScore:
    return ArmScore(
        curie=_EMPTY_OV,
        stability=_EMPTY_OV,
        certified=CertifiedOverlap(certified=certified, refuted=refuted, refused=refused, per_link=tuple(per_link)),
    )


def _prereg() -> Prereg:
    return Prereg(
        pair_ids=("necs__xuetal",),
        noise_rule="replicate_range",
        thresholds=Thresholds(),
        positive_control_arm="kg_reresolution",
        positive_control_required="FAIL",
        deployed_commit="deadbeef",
        metagraph_fingerprint="build-2.0.1:abc",
        cold_canary_expected="COLD_abc",
    )


def test_plant_refutation_outside_kept_population_is_still_detected():
    prereg = _prereg()
    mask = {("x", "y"): frozenset({"RM:1"})}  # the only RefMet-parity-kept pair
    # baseline == treatment over the kept link -> the REAL verdict is NOOP; the plant is what matters.
    base_reps = tuple(_score(1, 0, 0, per_link=(("x", "y", "certified"),)) for _ in range(3))
    baseline = ArmReplicates("baseline", base_reps, "COLD_abc", mask)
    treatment = ArmReplicates("treatment", base_reps, "COLD_abc", mask)
    # The plant keeps baseline's kept link certified AND adds a planted refutation on a pair OUTSIDE
    # `kept`. Under the bug (scoping to kept), the plant looks unchanged vs baseline -> self-test ABORTs.
    plant_reps = tuple(
        _score(1, 1, 0, per_link=(("x", "y", "certified"), ("p1", "q1", "refuted"))) for _ in range(3)
    )
    plant = ArmReplicates("kg_reresolution", plant_reps, "COLD_abc", {})
    arms = {"baseline": baseline, "treatment": treatment, "kg_reresolution": plant}

    res = evaluate_conflation_gate(prereg, arms)
    assert res.decision != "ABORT"  # plant detected over its own population; gate not invalidated
    assert res.positive_control_ok is not False
    assert res.decision == "NOOP"  # baseline == treatment over the kept link
