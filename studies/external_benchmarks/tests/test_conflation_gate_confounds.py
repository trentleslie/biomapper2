"""Unit F confound controls (units 1-4) — pure/offline; live observation injected.

An autouse socket block makes any stray dev-API/oracle call FAIL the test rather than silently hit
the network: the whole confound layer is pure, so these tests pass under the block, proving isolation.
The confounds each carry a positive control that MUST fire (the guard is worthless if it can't fail).
"""

from __future__ import annotations

import socket

import pytest

from studies.external_benchmarks.conflation_gate import (
    ArmReplicates,
    Prereg,
    Thresholds,
    canary_ok,
    confound_gate,
    noise_floor,
    refmet_parity,
)
from studies.external_benchmarks.cross_cohort_devapi_sweep import ArmScore
from studies.external_benchmarks.scorers.cross_cohort_overlap import OverlapResult
from studies.external_benchmarks.scorers.independent_link_certificate_overlap import CertifiedOverlap


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _blocked(*a, **k):
        raise AssertionError("network access in a Unit-F confound test — must be pure/offline")

    monkeypatch.setattr(socket.socket, "connect", _blocked)


_EMPTY_OV = OverlapResult(links=(), n_links=0, n_a_linked=0, n_b_linked=0, n_a_comparable=0, n_b_comparable=0)


def _score(certified: int, refuted: int, refused: int, per_link=()) -> ArmScore:
    return ArmScore(
        curie=_EMPTY_OV,
        stability=_EMPTY_OV,
        certified=CertifiedOverlap(certified=certified, refuted=refuted, refused=refused, per_link=tuple(per_link)),
    )


def _arm(name, reps, canary="COLD_abc", refmet_mask=None) -> ArmReplicates:
    return ArmReplicates(
        name=name,
        replicates=tuple(reps),
        canary_reading=canary,
        refmet_mask=refmet_mask or {},
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


# --- Unit 1: noise floor from replicates -----------------------------------------------------------


def test_noise_floor_is_the_replicate_range_per_metric():
    reps = [_score(10, 1, 0), _score(12, 1, 0), _score(11, 2, 0)]
    floor = noise_floor(_arm("baseline", reps))
    assert floor == {"certified": 2, "refuted": 1, "refused": 0}


def test_noise_floor_raises_below_three_replicates():
    # Positive control for unit 1: fewer than 3 replicates cannot establish a floor -> caller ABSTAINs.
    with pytest.raises(ValueError):
        noise_floor(_arm("baseline", [_score(10, 1, 0), _score(11, 1, 0)]))


# --- Unit 2: RefMet parity filter ------------------------------------------------------------------


def test_refmet_parity_excludes_a_flipped_mask_pair():
    # Positive control for unit 2: the one pair whose RefMet-hit mask flipped across arms is excluded.
    base_mask = {("a", "b"): frozenset({"a"}), ("c", "d"): frozenset()}
    treat_mask = {("a", "b"): frozenset({"b"}), ("c", "d"): frozenset()}
    base = _arm("baseline", [_score(1, 0, 0)] * 3, refmet_mask=base_mask)
    treat = _arm("treatment", [_score(1, 0, 0)] * 3, refmet_mask=treat_mask)
    kept, excluded = refmet_parity(base, treat)
    assert excluded == frozenset({("a", "b")})
    assert kept == frozenset({("c", "d")})


def test_refmet_parity_keeps_all_matching_masks():
    mask = {("a", "b"): frozenset({"a"}), ("c", "d"): frozenset({"c", "d"})}
    base = _arm("baseline", [_score(1, 0, 0)] * 3, refmet_mask=dict(mask))
    treat = _arm("treatment", [_score(1, 0, 0)] * 3, refmet_mask=dict(mask))
    kept, excluded = refmet_parity(base, treat)
    assert excluded == frozenset()
    assert kept == frozenset(mask)


# --- Unit 3: cold-cache canary ---------------------------------------------------------------------


def test_canary_rejects_a_warm_reading():
    # Positive control for unit 3: a warm reading (!= the pre-registered cold value) is refused.
    assert canary_ok(_arm("treatment", [_score(1, 0, 0)] * 3, canary="WARM_xyz"), _prereg()) is False


def test_canary_accepts_the_cold_reading():
    assert canary_ok(_arm("treatment", [_score(1, 0, 0)] * 3, canary="COLD_abc"), _prereg()) is True


# --- Unit 4: confound gate composition -------------------------------------------------------------


def test_confound_gate_passes_clean_arms_and_each_confound_forces_abstain():
    prereg = _prereg()
    base = _arm("baseline", [_score(5, 1, 0)] * 3)
    treat = _arm("treatment", [_score(5, 1, 0)] * 3)

    clean, kept, excluded = confound_gate(prereg, base, treat)
    assert clean is None  # no confound -> pass through

    # (1) insufficient replicates
    thin = _arm("treatment", [_score(5, 1, 0), _score(5, 1, 0)])
    res, _, _ = confound_gate(prereg, base, thin)
    assert res is not None and res.decision == "ABSTAIN"

    # (3) warm canary
    warm = _arm("treatment", [_score(5, 1, 0)] * 3, canary="WARM_xyz")
    res, _, _ = confound_gate(prereg, base, warm)
    assert res.decision == "ABSTAIN"

    # (2) RefMet mask mismatch wiping out every comparable pair
    bm = _arm("baseline", [_score(5, 1, 0)] * 3, refmet_mask={("a", "b"): frozenset({"a"})})
    tm = _arm("treatment", [_score(5, 1, 0)] * 3, refmet_mask={("a", "b"): frozenset({"b"})})
    res, kept2, excl2 = confound_gate(prereg, bm, tm)
    assert res.decision == "ABSTAIN"
    assert ("a", "b") in excl2

    # (4) byte-identical arm caches (shared-KG-cache confound)
    rows = {"x": {"chosen_kg_id": "CHEBI:1", "kg_equivalent_ids": {}}}
    res, _, _ = confound_gate(prereg, base, treat, caches={"baseline": rows, "treatment": dict(rows)})
    assert res.decision == "ABSTAIN"
