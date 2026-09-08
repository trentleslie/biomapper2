"""Units A2 + A3 — confounds fire THROUGH the orchestrator, not only in ``confound_gate`` in isolation.

A2 revives the byte-identical-cache guard on the orchestrated path: ``evaluate_conflation_gate`` now
threads per-arm caches into ``confound_gate``, so a shared-KG-cache confound ABSTAINs end-to-end
(previously the guard was dead on this path — caches were never forwarded). A3 makes an absent/partial
RefMet mask over the prereg-declared adjudicable population ABSTAIN (fail closed) instead of silently
falling back to the full aggregate. Each carries a positive control that must fire.
"""

from __future__ import annotations

from studies.external_benchmarks.conflation_gate import (
    ArmReplicates,
    Prereg,
    Thresholds,
    confound_gate,
    evaluate_conflation_gate,
)
from studies.external_benchmarks.cross_cohort_devapi_sweep import ArmScore
from studies.external_benchmarks.scorers.cross_cohort_overlap import OverlapResult
from studies.external_benchmarks.scorers.independent_link_certificate_overlap import CertifiedOverlap

_EMPTY_OV = OverlapResult(links=(), n_links=0, n_a_linked=0, n_b_linked=0, n_a_comparable=0, n_b_comparable=0)


def _score(certified: int, refuted: int, refused: int, per_link=()) -> ArmScore:
    return ArmScore(
        curie=_EMPTY_OV,
        stability=_EMPTY_OV,
        certified=CertifiedOverlap(certified=certified, refuted=refuted, refused=refused, per_link=tuple(per_link)),
    )


def _arm(name, reps, canary="COLD_abc", refmet_mask=None) -> ArmReplicates:
    return ArmReplicates(name=name, replicates=tuple(reps), canary_reading=canary, refmet_mask=refmet_mask or {})


def _prereg(adjudicable_pairs=()) -> Prereg:
    return Prereg(
        pair_ids=("necs__xuetal",),
        thresholds=Thresholds(),
        positive_control_arm="kg_reresolution",
        positive_control_required="FAIL",
        deployed_commit="deadbeef",
        metagraph_fingerprint="build-2.0.1:abc",
        cold_canary_expected="COLD_abc",
        adjudicable_pairs=tuple(adjudicable_pairs),
    )


def _rows(chosen):
    return {n: {"chosen_kg_id": c, "kg_equivalent_ids": {}} for n, c in chosen.items()}


# --- A2: byte-identical caches abstain THROUGH evaluate_conflation_gate ----------------------------


def test_evaluate_abstains_on_byte_identical_caches():
    # Positive control for A2: the shared-cache confound now fires on the orchestrated path.
    prereg = _prereg()
    baseline = _arm("baseline", [_score(20, 5, 3)] * 3)
    treatment = _arm("treatment", [_score(20, 2, 3)] * 3)
    plant = _arm("kg_reresolution", [_score(20, 9, 3)] * 3)
    arms = {"baseline": baseline, "treatment": treatment, "kg_reresolution": plant}
    rows = _rows({"x": "CHEBI:1", "y": "CHEBI:2"})
    caches = {"baseline": rows, "treatment": dict(rows)}  # byte-identical chosen ids
    assert evaluate_conflation_gate(prereg, arms, caches=caches).decision == "ABSTAIN"


def test_evaluate_proceeds_on_distinct_caches():
    prereg = _prereg()
    baseline = _arm("baseline", [_score(20, 5, 3)] * 3)
    treatment = _arm("treatment", [_score(20, 2, 3)] * 3)
    plant = _arm("kg_reresolution", [_score(20, 9, 3)] * 3)
    arms = {"baseline": baseline, "treatment": treatment, "kg_reresolution": plant}
    caches = {"baseline": _rows({"x": "CHEBI:1"}), "treatment": _rows({"x": "CHEBI:9"})}
    assert evaluate_conflation_gate(prereg, arms, caches=caches).decision == "PASS"


def test_evaluate_without_caches_keeps_backcompat():
    # caches=None (the pure unit path) => no cache check, exactly as before A2.
    prereg = _prereg()
    baseline = _arm("baseline", [_score(20, 5, 3)] * 3)
    treatment = _arm("treatment", [_score(20, 2, 3)] * 3)
    plant = _arm("kg_reresolution", [_score(20, 9, 3)] * 3)
    arms = {"baseline": baseline, "treatment": treatment, "kg_reresolution": plant}
    assert evaluate_conflation_gate(prereg, arms).decision == "PASS"


# --- A3: fail closed when a RefMet mask is absent over the declared adjudicable population ----------


def test_confound_gate_abstains_when_treatment_mask_absent_over_adjudicable():
    # Positive control for A3: the prereg declares (a,b) adjudicable; the treatment arm has NO mask
    # over it -> ABSTAIN (previously it silently used the full aggregate and could PASS).
    prereg = _prereg(adjudicable_pairs=[("a", "b")])
    mask = {("a", "b"): frozenset({"a"})}
    base = _arm("baseline", [_score(1, 0, 0)] * 3, refmet_mask=mask)
    treat = _arm("treatment", [_score(1, 0, 0)] * 3, refmet_mask={})
    res, _, _ = confound_gate(prereg, base, treat)
    assert res is not None and res.decision == "ABSTAIN"
    assert any("RefMet parity mask" in r for r in res.reasons)


def test_confound_gate_proceeds_when_both_arms_cover_adjudicable():
    prereg = _prereg(adjudicable_pairs=[("a", "b")])
    mask = {("a", "b"): frozenset({"a"})}
    base = _arm("baseline", [_score(1, 0, 0)] * 3, refmet_mask=dict(mask))
    treat = _arm("treatment", [_score(1, 0, 0)] * 3, refmet_mask=dict(mask))
    clean, kept, _ = confound_gate(prereg, base, treat)
    assert clean is None
    assert ("a", "b") in kept


def test_confound_gate_abstains_on_partial_mask_coverage():
    # Adjudicable = {small-mol, lipid}; masks cover only the small-mol pair -> partial -> ABSTAIN.
    prereg = _prereg(adjudicable_pairs=[("smallmol_a", "smallmol_b"), ("lipid_a", "lipid_b")])
    mask = {("smallmol_a", "smallmol_b"): frozenset({"smallmol_a"})}
    base = _arm("baseline", [_score(1, 0, 0)] * 3, refmet_mask=dict(mask))
    treat = _arm("treatment", [_score(1, 0, 0)] * 3, refmet_mask=dict(mask))
    res, _, _ = confound_gate(prereg, base, treat)
    assert res is not None and res.decision == "ABSTAIN"
