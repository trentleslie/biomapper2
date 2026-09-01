"""Unit A1 — ``decide`` refused-rise tripwire (the lipid-conflation false-clean guard) — pure/offline.

The #60 risk class is lipid conflation: a fix can quietly push links out of the adjudicable
population (into ``refused``) while the certified/refuted headline barely moves. Before A1 that read
as NOOP/PASS. A1 makes a material ``refused`` rise (beyond its noise floor) with a flat ``certified``
return ABSTAIN — "the adjudicable population shrank, the verdict is untrustworthy". A ``refused`` rise
PAIRED with a ``refuted`` rise is already a FAIL (checked first), and a real net gain (certified also
rose beyond floor) is NOT tripped.
"""

from __future__ import annotations

from studies.external_benchmarks.conflation_gate import Thresholds, decide
from studies.external_benchmarks.cross_cohort_devapi_sweep import ArmScore
from studies.external_benchmarks.scorers.cross_cohort_overlap import OverlapResult
from studies.external_benchmarks.scorers.independent_link_certificate_overlap import CertifiedOverlap

_EMPTY_OV = OverlapResult(links=(), n_links=0, n_a_linked=0, n_b_linked=0, n_a_comparable=0, n_b_comparable=0)
_FLOOR = {"certified": 1, "refuted": 1, "refused": 1}


def _score(certified: int, refuted: int, refused: int, per_link=()) -> ArmScore:
    return ArmScore(
        curie=_EMPTY_OV,
        stability=_EMPTY_OV,
        certified=CertifiedOverlap(certified=certified, refuted=refuted, refused=refused, per_link=tuple(per_link)),
    )


def test_refused_rose_with_certified_flat_abstains():
    # Positive control: refused +5 (beyond floor 1), certified flat -> the adjudicable population
    # shrank. Previously NOOP/PASS; now ABSTAIN.
    res = decide(_score(20, 2, 3), _score(20, 2, 8), _FLOOR, kept_pairs=(), thresholds=Thresholds())
    assert res.decision == "ABSTAIN"
    assert any("adjudicable population shrank" in r for r in res.reasons)
    assert res.deltas["refused"] == 5


def test_refused_within_floor_does_not_abstain():
    # refused +1 is inside the floor -> no tripwire, the verdict is the ordinary NOOP.
    res = decide(_score(20, 2, 3), _score(20, 2, 4), _FLOOR, kept_pairs=(), thresholds=Thresholds())
    assert res.decision == "NOOP"


def test_refused_rise_paired_with_refuted_rise_is_fail_not_abstain():
    # refuted +4 beyond floor -> FAIL fires first (a conflation that also flips good links). The
    # tripwire must not downgrade a FAIL to ABSTAIN.
    res = decide(_score(20, 2, 3), _score(20, 6, 8), _FLOOR, kept_pairs=(), thresholds=Thresholds())
    assert res.decision == "FAIL"


def test_refused_rise_with_certified_gain_is_pass_not_abstain():
    # A genuine net improvement: certified +5 beyond floor even though refused rose -> the population
    # did not shrink (more got adjudicated AND certified), so PASS, not ABSTAIN.
    res = decide(_score(20, 2, 3), _score(25, 2, 8), _FLOOR, kept_pairs=(), thresholds=Thresholds())
    assert res.decision == "PASS"


def test_refused_rise_scoped_to_kept_links_abstains_via_orchestrated_population():
    # Same tripwire measured over the RefMet-retained links only: refused rises on the kept link,
    # certified flat -> ABSTAIN. Guards against a coverage swing on excluded links masking it.
    base = _score(1, 0, 1, per_link=(("a1", "b1", "certified"), ("a2", "b2", "refused")))
    treat = _score(1, 0, 4, per_link=(
        ("a1", "b1", "certified"),
        ("a2", "b2", "refused"), ("a3", "b3", "refused"), ("a4", "b4", "refused"), ("a5", "b5", "refused"),
    ))
    kept = {("a2", "b2"), ("a3", "b3"), ("a4", "b4"), ("a5", "b5"), ("a1", "b1")}
    res = decide(base, treat, _FLOOR, kept_pairs=kept, thresholds=Thresholds())
    assert res.decision == "ABSTAIN"
