"""Unit F improvement decision + self-test + end-to-end (units 5-7) — pure/offline.

The decision runs on the KG-INDEPENDENT certified counts only. Every branch is falsifiable: an
over-correction (certified fell) or a refuted regression FAILs even when the headline moved the
"right" way, and the gate self-tests against a pre-registered known-bad arm (unit 6) so a decision
core that cannot detect a plant returns ABORT rather than a bogus PASS.
"""

from __future__ import annotations

import socket

import pytest

from studies.external_benchmarks.conflation_gate import (
    ArmReplicates,
    Prereg,
    Thresholds,
    decide,
    evaluate_conflation_gate,
    positive_control_selftest,
)
from studies.external_benchmarks.cross_cohort_devapi_sweep import ArmScore
from studies.external_benchmarks.scorers.cross_cohort_overlap import OverlapResult
from studies.external_benchmarks.scorers.independent_link_certificate_overlap import CertifiedOverlap


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _blocked(*a, **k):
        raise AssertionError("network access in a Unit-F decision test — must be pure/offline")

    monkeypatch.setattr(socket.socket, "connect", _blocked)


_EMPTY_OV = OverlapResult(links=(), n_links=0, n_a_linked=0, n_b_linked=0, n_a_comparable=0, n_b_comparable=0)
_FLOOR = {"certified": 1, "refuted": 1, "refused": 1}


def _score(certified: int, refuted: int, refused: int, per_link=()) -> ArmScore:
    return ArmScore(
        curie=_EMPTY_OV,
        stability=_EMPTY_OV,
        certified=CertifiedOverlap(certified=certified, refuted=refuted, refused=refused, per_link=tuple(per_link)),
    )


def _arm(name, reps, canary="COLD_abc") -> ArmReplicates:
    return ArmReplicates(name=name, replicates=tuple(reps), canary_reading=canary, refmet_mask={})


def _prereg(required="FAIL") -> Prereg:
    return Prereg(
        pair_ids=("necs__xuetal",),
        noise_rule="replicate_range",
        thresholds=Thresholds(),
        positive_control_arm="kg_reresolution",
        positive_control_required=required,
        deployed_commit="deadbeef",
        metagraph_fingerprint="build-2.0.1:abc",
        cold_canary_expected="COLD_abc",
    )


# --- Unit 5: improvement decision (six falsifiable scenarios) ---------------------------------------


def test_refuted_down_certified_flat_passes():
    res = decide(_score(20, 5, 3), _score(20, 2, 3), _FLOOR, kept_pairs=(), thresholds=Thresholds())
    assert res.decision == "PASS"
    assert res.deltas["refuted"] == -3


def test_certified_fell_fails_as_over_correction():
    res = decide(_score(20, 5, 0), _score(15, 2, 0), _FLOOR, kept_pairs=(), thresholds=Thresholds())
    assert res.decision == "FAIL"


def test_all_within_floor_is_noop():
    res = decide(_score(20, 5, 3), _score(21, 4, 2), _FLOOR, kept_pairs=(), thresholds=Thresholds())
    assert res.decision == "NOOP"


def test_refuted_rose_fails():
    res = decide(_score(20, 2, 0), _score(20, 6, 0), _FLOOR, kept_pairs=(), thresholds=Thresholds())
    assert res.decision == "FAIL"


def test_refused_down_only_passes():
    res = decide(_score(20, 2, 5), _score(20, 2, 0), _FLOOR, kept_pairs=(), thresholds=Thresholds())
    assert res.decision == "PASS"
    assert res.deltas["refused"] == -5


def test_per_pair_refuted_regression_fails_under_a_flat_aggregate():
    # A single kept link flips certified -> refuted; a compensating refused -> certified keeps the
    # aggregate within the floor, so ONLY the per-link guard catches the regression. This is the
    # anti-pooling case: a per-artifact regression the headline hides.
    base = _score(1, 0, 1, per_link=(("a1", "b1", "certified"), ("a2", "b2", "refused")))
    treat = _score(1, 1, 0, per_link=(("a1", "b1", "refuted"), ("a2", "b2", "certified")))
    kept = {("a1", "b1"), ("a2", "b2")}
    res = decide(base, treat, _FLOOR, kept_pairs=kept, thresholds=Thresholds())
    assert res.decision == "FAIL"
    assert any("regression" in r for r in res.reasons)


def test_changes_confined_to_excluded_links_do_not_move_the_verdict():
    # Only ("a1","b1") survives RefMet parity; the a2/a3/a4 links are EXCLUDED. All the movement is on
    # the excluded links (three refuted -> certified "fixes"); the retained link is unchanged. The
    # verdict must be NOOP — an aggregate that counted the excluded links would wrongly PASS on a
    # coverage swing that says nothing about the links we are allowed to compare.
    base = _score(
        1, 3, 0,
        per_link=(
            ("a1", "b1", "certified"),
            ("a2", "b2", "refuted"), ("a3", "b3", "refuted"), ("a4", "b4", "refuted"),
        ),
    )
    treat = _score(
        4, 0, 0,
        per_link=(
            ("a1", "b1", "certified"),
            ("a2", "b2", "certified"), ("a3", "b3", "certified"), ("a4", "b4", "certified"),
        ),
    )
    res = decide(base, treat, _FLOOR, kept_pairs={("a1", "b1")}, thresholds=Thresholds())
    assert res.decision == "NOOP"
    assert res.deltas == {"certified": 0, "refuted": 0, "refused": 0}


# --- Unit 6: positive-control self-test ------------------------------------------------------------


def test_positive_control_self_test_aborts_when_plant_would_pass_and_clears_when_it_fails():
    prereg = _prereg(required="FAIL")
    baseline = _score(20, 2, 0)
    # A known-bad arm that IMPROVES the metric (refuted fell) would PASS -> the gate can't detect a
    # plant -> ABORT (gate invalid).
    plant_passes = _score(20, 0, 0)
    abort = positive_control_selftest(prereg, baseline, plant_passes, _FLOOR, kept_pairs=(), thresholds=Thresholds())
    assert abort is not None and abort.decision == "ABORT"
    assert abort.positive_control_ok is False

    # A known-bad arm that FAILs as required -> self-test clears (returns None), real verdict proceeds.
    plant_fails = _score(20, 8, 0)
    cleared = positive_control_selftest(prereg, baseline, plant_fails, _FLOOR, kept_pairs=(), thresholds=Thresholds())
    assert cleared is None


# --- Unit 7: end-to-end orchestration --------------------------------------------------------------


def test_evaluate_conflation_gate_end_to_end_pass_abstain_and_abort():
    prereg = _prereg(required="FAIL")
    baseline = _arm("baseline", [_score(20, 5, 3), _score(20, 5, 3), _score(21, 5, 3)])
    treatment = _arm("treatment", [_score(20, 2, 3), _score(20, 2, 3), _score(20, 2, 3)])
    good_plant = _arm("kg_reresolution", [_score(20, 9, 3)] * 3)  # FAILs as required
    arms = {"baseline": baseline, "treatment": treatment, "kg_reresolution": good_plant}

    passed = evaluate_conflation_gate(prereg, arms)
    assert passed.decision == "PASS"

    # ABSTAIN short-circuit: treatment ran warm -> confound gate abstains before any decision.
    warm_treatment = _arm("treatment", [_score(20, 2, 3)] * 3, canary="WARM_xyz")
    warm_arms = {"baseline": baseline, "treatment": warm_treatment, "kg_reresolution": good_plant}
    assert evaluate_conflation_gate(prereg, warm_arms).decision == "ABSTAIN"

    # ABORT short-circuit: the plant PASSes, so the gate cannot detect a known-bad arm.
    bad_plant = _arm("kg_reresolution", [_score(20, 0, 3)] * 3)
    bad_arms = {"baseline": baseline, "treatment": treatment, "kg_reresolution": bad_plant}
    assert evaluate_conflation_gate(prereg, bad_arms).decision == "ABORT"
