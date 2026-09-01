"""Unit B6 — assemble scored replicates + plant into ArmReplicates and run the HARDENED gate WITH caches.

Every verdict is reached THROUGH the orchestrator (``evaluate_conflation_gate``), never a helper in
isolation: PASS on a real improvement, ABORT when the plant would pass, and ABSTAIN via each revived
guard — byte-identical caches (A2), a missing RefMet mask (A3), the refused-rise tripwire (A1), and
too-few replicates. A live verdict REQUIRES caches (``run_gate`` asserts it). Pure/offline.
"""

from __future__ import annotations

import pytest

from studies.external_benchmarks.conflation_gate import Prereg, Thresholds
from studies.external_benchmarks.cross_cohort_devapi_sweep import ArmScore
from studies.external_benchmarks.gate_live_assemble import assemble_arms, run_gate
from studies.external_benchmarks.scorers.cross_cohort_overlap import OverlapResult
from studies.external_benchmarks.scorers.independent_link_certificate_overlap import CertifiedOverlap

_EMPTY_OV = OverlapResult(links=(), n_links=0, n_a_linked=0, n_b_linked=0, n_a_comparable=0, n_b_comparable=0)


def _score(certified, refuted, refused) -> ArmScore:
    return ArmScore(curie=_EMPTY_OV, stability=_EMPTY_OV,
                    certified=CertifiedOverlap(certified=certified, refuted=refuted, refused=refused, per_link=()))


def _prereg(adjudicable_pairs=()) -> Prereg:
    return Prereg(
        pair_ids=("necs__xuetal",),
        thresholds=Thresholds(),
        positive_control_arm="plant",
        positive_control_required="FAIL",
        deployed_commit="bbbb2222",
        metagraph_fingerprint="kestrel=9;kg_version=2.0.1;kg_commit=x",
        cold_canary_expected="COLD_x",
        adjudicable_pairs=tuple(adjudicable_pairs),
    )


def _rows(chosen):
    return {n: {"chosen_kg_id": c, "kg_equivalent_ids": {}} for n, c in chosen.items()}


def _arms(baseline, treatment, plant, masks=None):
    return assemble_arms(
        replicates_by_arm={"baseline": baseline, "treatment": treatment, "plant": plant},
        canary_by_arm={"baseline": "COLD_x", "treatment": "COLD_x", "plant": "COLD_x"},
        masks_by_arm=masks or {},
    )


# a FAILing plant (refuted rises vs baseline) so the self-test clears and the real verdict is reached
_GOOD_PLANT = [_score(3, 5, 1)] * 3
_DISTINCT = {"baseline": _rows({"x": "CHEBI:1"}), "treatment": _rows({"x": "CHEBI:2"})}


def test_improvement_passes_through_the_orchestrator():
    arms = _arms([_score(3, 2, 1)] * 3, [_score(3, 0, 1)] * 3, _GOOD_PLANT)
    assert run_gate(_prereg(), arms, caches=_DISTINCT).decision == "PASS"


def test_plant_that_would_pass_aborts():
    # Positive control: a plant that IMPROVES the metric (refuted fell) would PASS -> the gate cannot
    # detect a known-bad arm -> ABORT.
    arms = _arms([_score(3, 2, 1)] * 3, [_score(3, 0, 1)] * 3, [_score(3, 0, 1)] * 3)
    assert run_gate(_prereg(), arms, caches=_DISTINCT).decision == "ABORT"


def test_byte_identical_caches_abstain():
    arms = _arms([_score(3, 2, 1)] * 3, [_score(3, 0, 1)] * 3, _GOOD_PLANT)
    same = _rows({"x": "CHEBI:1"})
    assert run_gate(_prereg(), arms, caches={"baseline": same, "treatment": dict(same)}).decision == "ABSTAIN"


def test_missing_refmet_mask_abstains():
    # A3: prereg declares (a,b) adjudicable; treatment carries no mask -> fail closed -> ABSTAIN.
    masks = {"baseline": {("a", "b"): frozenset({"a"})}, "treatment": {}}
    arms = _arms([_score(3, 2, 1)] * 3, [_score(3, 0, 1)] * 3, _GOOD_PLANT, masks=masks)
    assert run_gate(_prereg(adjudicable_pairs=[("a", "b")]), arms, caches=_DISTINCT).decision == "ABSTAIN"


def test_refused_rise_tripwire_abstains():
    # A1: treatment refused rises (1->6) with certified flat and refuted flat -> ABSTAIN.
    arms = _arms([_score(3, 2, 1)] * 3, [_score(3, 2, 6)] * 3, _GOOD_PLANT)
    assert run_gate(_prereg(), arms, caches=_DISTINCT).decision == "ABSTAIN"


def test_too_few_replicates_abstains():
    arms = _arms([_score(3, 2, 1)] * 2, [_score(3, 0, 1)] * 3, _GOOD_PLANT)
    assert run_gate(_prereg(), arms, caches=_DISTINCT).decision == "ABSTAIN"


def test_plant_that_abstains_still_aborts():
    # Edge: a plant whose self-test decision is ABSTAIN (refused rose, certified flat) != required FAIL
    # -> ABORT (the self-test is conservative: anything but the required verdict invalidates the gate).
    abstaining_plant = [_score(3, 2, 9)] * 3
    arms = _arms([_score(3, 2, 1)] * 3, [_score(3, 0, 1)] * 3, abstaining_plant)
    assert run_gate(_prereg(), arms, caches=_DISTINCT).decision == "ABORT"


def test_run_gate_requires_caches_for_a_live_verdict():
    # R-Core / A2: a live verdict without the cache guard is not trustworthy -> refuse to produce one.
    arms = _arms([_score(3, 2, 1)] * 3, [_score(3, 0, 1)] * 3, _GOOD_PLANT)
    with pytest.raises(ValueError, match="cache"):
        run_gate(_prereg(), arms, caches=None)
