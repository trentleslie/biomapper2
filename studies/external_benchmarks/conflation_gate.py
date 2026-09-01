"""Unit F — conflation benchmark gate: falsifiable, confound-controlled improvement decision.

The question this gate answers is narrow and pre-registered: did a KG-conflation fix (re-resolution of
shared generic nodes) *actually* reduce wrong-molecule links WITHOUT destroying good ones — measured on
the KG-INDEPENDENT certificate (``CertifiedOverlap``, Unit C), never on the KG's own InChIKey. Because
this project's failure mode is that aggregate rates collapse while per-artifact claims survive, every
guard here is falsifiable and carries a positive control that MUST be able to fail:

  * **Noise floor** (unit 1) is the replicate range, so a delta smaller than run-to-run jitter is NOOP,
    not a win. <3 replicates cannot establish a floor -> ABSTAIN.
  * **RefMet parity** (unit 2) drops any link whose RefMet-hit mask differs across arms — a treatment
    that changes coverage, not correctness, must not be counted as a correctness win.
  * **Cold-cache canary** (unit 3) refuses a warm reading: a re-served KG cache is exactly the
    shared-cache confound that invalidated an earlier sweep. A process restart is NOT accepted; only the
    canary reading is.
  * **Byte-identical arm caches** (``arms_look_confounded``, reused) catch total cache degeneracy.
  * **Improvement decision** (unit 5) applies over-correction / refuted-regression FAIL bounds BEFORE it
    can PASS, and a **per-link** refuted-regression FAIL fires even when the aggregate stays within the
    floor — the anti-pooling guard.
  * **Positive-control self-test** (unit 6) runs the decision on a pre-registered KNOWN-BAD arm; if the
    core cannot detect the plant (does not return the required FAIL/ABSTAIN), the whole gate is invalid
    -> ABORT.

The pure decision core (units 1-7) is unit-tested offline on mock ``ArmScore`` replicates. The LIVE run
(``run_conflation_gate``) is a supervised operator step, never in pytest; it mirrors ``gate.py``'s
inject-observation split — the arms are observed live, the decision is the same pure code the tests
cover, and it persists ``prereg.json`` then ``result.json`` by default (R23).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from .cross_cohort_devapi_sweep import ArmScore, ResolvedRows, arms_look_confounded

# A cross-cohort link identifier: (a_name, b_name). Matches ``CertifiedOverlap.per_link`` keys.
Pair = tuple[str, str]

# Extends the independent-structure seam with a source tag (G7): (inchikey, source), source in
# {pubchem, hmdb, goslin, lipidmaps, kg}. A ``None`` inchikey => refused on that side. The oracle
# source must NOT equal the resolver source, or the certificate is circular (that is why it is tagged).
SourcedInChIKey = tuple[str | None, str | None]

_METRICS: tuple[str, str, str] = ("certified", "refuted", "refused")


@dataclass(frozen=True)
class Thresholds:
    """Hard bounds layered on top of the noise-floor-relative checks (both optional backstops).

    ``min_certified`` — treatment certified count may never fall below this absolute floor.
    ``max_refuted`` — treatment refuted count may never exceed this absolute ceiling.
    Left ``None`` the decision relies purely on the pre-registered noise floor (the default posture).
    """

    min_certified: int | None = None
    max_refuted: int | None = None


@dataclass(frozen=True)
class Prereg:
    """Pre-registered decision contract — pinned BEFORE the arms are observed (R4/R23).

    Pinning ``deployed_commit`` + ``metagraph_fingerprint`` + ``cold_canary_expected`` is what makes the
    later verdict auditable: the result names the exact build and the cold-cache proof it was judged on.
    ``positive_control_required`` is the verdict the KNOWN-BAD ``positive_control_arm`` MUST produce for
    the gate to be considered valid.
    """

    pair_ids: tuple[str, ...]
    thresholds: Thresholds
    positive_control_arm: str
    positive_control_required: str  # "FAIL" | "ABSTAIN"
    deployed_commit: str
    metagraph_fingerprint: str
    cold_canary_expected: str
    metric: str = "certified_overlap"
    noise_rule: str = "replicate_range"


@dataclass(frozen=True)
class ArmReplicates:
    """One arm (e.g. ``baseline`` / ``treatment`` / the plant) observed over >=3 replicates.

    ``replicates`` are full ``ArmScore``s of the SAME arm; their spread establishes the noise floor.
    ``canary_reading`` is the cold-cache proof for this arm's window. ``refmet_mask`` maps each link
    (a_name, b_name) to the frozenset of that link's names that hit RefMet — compared across arms so a
    coverage change is not mistaken for a correctness change.
    """

    name: str
    replicates: tuple[ArmScore, ...]
    canary_reading: str
    refmet_mask: Mapping[Pair, frozenset[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class GateResult:
    """The gate verdict + the artifacts that justify it (never a bare scalar; R8a)."""

    decision: str  # "PASS" | "NOOP" | "FAIL" | "ABSTAIN" | "ABORT"
    deltas: Mapping[str, int] = field(default_factory=dict)
    noise_floor: Mapping[str, int] = field(default_factory=dict)
    excluded_pairs: tuple[Pair, ...] = ()
    positive_control_ok: bool | None = None
    reasons: tuple[str, ...] = ()


# --- Unit 1: noise floor from replicates -----------------------------------------------------------


def noise_floor(arm: ArmReplicates, kept_pairs: Iterable[Pair] | None = None) -> dict[str, int]:
    """Per-metric noise floor = replicate range (max-min) over the arm's >=3 replicates.

    A delta no larger than this run-to-run jitter is not a signal. Fewer than 3 replicates cannot
    establish a floor, so this RAISES (the caller maps that to ABSTAIN — never a fabricated 0 floor).

    ``kept_pairs`` MUST be the same RefMet-parity-retained population the deltas are measured over
    (``decide``). When RefMet parity excludes links, those excluded links can carry replicate
    variability of their own; a floor taken from the complete ``CertifiedOverlap`` totals would then be
    compared against deltas restricted to the retained links — a population mismatch that can inflate the
    floor and report a real retained-link regression/improvement as NOOP. So when a non-empty
    ``kept_pairs`` is supplied the range is computed over each replicate's retained-link counts only. An
    empty/``None`` ``kept_pairs`` means no parity mask was applied (the no-mask contract) and the floor
    falls back to the full aggregate, matching ``decide``'s own fallback.
    """
    reps = arm.replicates
    if len(reps) < 3:
        raise ValueError(f"noise floor needs >=3 replicates, arm {arm.name!r} has {len(reps)}")
    kept = set(kept_pairs) if kept_pairs is not None else set()
    if kept:
        rep_counts = [_counts_over(r.certified.per_link, kept) for r in reps]
    else:
        rep_counts = [{m: getattr(r.certified, m) for m in _METRICS} for r in reps]
    floor: dict[str, int] = {}
    for m in _METRICS:
        vals = [c[m] for c in rep_counts]
        floor[m] = max(vals) - min(vals)
    return floor


# --- Unit 2: RefMet parity filter ------------------------------------------------------------------


def refmet_parity(baseline: ArmReplicates, treatment: ArmReplicates) -> tuple[frozenset[Pair], frozenset[Pair]]:
    """Split links into (kept, excluded): a link is EXCLUDED iff its RefMet-hit mask differs across arms.

    A link present in only one arm's mask counts as a difference (mask absence != empty-match). Excluding
    those links stops a coverage swing from masquerading as a correctness improvement.
    """
    pairs = set(baseline.refmet_mask) | set(treatment.refmet_mask)
    kept: set[Pair] = set()
    excluded: set[Pair] = set()
    _MISSING = object()
    for p in pairs:
        b = baseline.refmet_mask.get(p, _MISSING)
        t = treatment.refmet_mask.get(p, _MISSING)
        (kept if b == t else excluded).add(p)
    return frozenset(kept), frozenset(excluded)


# --- Unit 3: cold-cache canary ---------------------------------------------------------------------


def canary_ok(arm: ArmReplicates, prereg: Prereg) -> bool:
    """The arm's canary reading must equal the pre-registered COLD value.

    A warm (re-served-cache) reading differs from the cold value and is refused. Only the reading is
    accepted as proof — a process restart of the dev API is NOT (that was the confound that invalidated
    an earlier sweep).
    """
    return arm.canary_reading is not None and arm.canary_reading == prereg.cold_canary_expected


# --- Unit 4: confound gate composition -------------------------------------------------------------


def confound_gate(
    prereg: Prereg,
    baseline: ArmReplicates,
    treatment: ArmReplicates,
    caches: Mapping[str, ResolvedRows] | None = None,
) -> tuple[GateResult | None, frozenset[Pair], tuple[Pair, ...]]:
    """Compose units 1-3 + ``arms_look_confounded`` -> (ABSTAIN-or-None, kept_pairs, excluded_pairs).

    Any confound present forces ABSTAIN with an explicit reason (never a silent pass). When clean the
    result is ``None`` and the caller proceeds with the RefMet-parity-kept links.
    """
    reasons: list[str] = []

    for arm in (baseline, treatment):
        if len(arm.replicates) < 3:
            reasons.append(f"arm {arm.name!r} has {len(arm.replicates)} replicates (<3) — no noise floor")
        if not canary_ok(arm, prereg):
            reasons.append(
                f"arm {arm.name!r} cold-cache canary failed "
                f"(reading={arm.canary_reading!r} != expected {prereg.cold_canary_expected!r})"
            )

    if caches is not None:
        flagged = arms_look_confounded(caches)
        if flagged:
            reasons.append(f"byte-identical arm caches (shared-KG-cache confound): {flagged}")

    kept, excluded = refmet_parity(baseline, treatment)
    if excluded and not kept:
        reasons.append("RefMet parity filter excluded every comparable link — no correctness signal left")

    excluded_sorted = tuple(sorted(excluded))
    if reasons:
        result = GateResult(
            decision="ABSTAIN",
            excluded_pairs=excluded_sorted,
            positive_control_ok=None,
            reasons=tuple(reasons),
        )
        return result, kept, excluded_sorted
    return None, kept, excluded_sorted


# --- Unit 5: improvement decision ------------------------------------------------------------------


def representative(arm: ArmReplicates, kept_pairs: Iterable[Pair] | None = None) -> ArmScore:
    """Deterministic representative replicate = the (lower-)median by (certified, refuted, refused).

    Median rather than mean so a single anomalous replicate cannot drag the reading, and deterministic
    tie-breaking so the pure decision is reproducible across runs.

    ``kept_pairs`` MUST be the same RefMet-parity-retained population the floor and deltas are measured
    over (``noise_floor`` / ``decide``). Ranking replicates by their FULL ``CertifiedOverlap`` totals
    while the gate then scores them over the retained links only is a population mismatch:
    parity-excluded variability could reorder the replicates and select a different median than the one
    the retained-link decision is taken on. So when a non-empty ``kept_pairs`` is supplied the median is
    chosen over each replicate's retained-link counts; an empty/``None`` set keeps the full-total order
    (the no-mask contract the pure tests exercise).
    """
    kept = set(kept_pairs) if kept_pairs is not None else set()

    def _key(s: ArmScore) -> tuple[int, int, int]:
        if kept:
            c = _counts_over(s.certified.per_link, kept)
            return (c["certified"], c["refuted"], c["refused"])
        return (s.certified.certified, s.certified.refuted, s.certified.refused)

    ordered = sorted(arm.replicates, key=_key)
    return ordered[(len(ordered) - 1) // 2]


def _counts_over(per_link: Iterable[tuple[str, str, str]], kept: set[Pair]) -> dict[str, int]:
    """Tally per-link verdicts restricted to the retained links ``kept`` (RefMet-parity survivors)."""
    counts = {m: 0 for m in _METRICS}
    for a, bn, v in per_link:
        if (a, bn) in kept and v in counts:
            counts[v] += 1
    return counts


def decide(
    baseline: ArmScore,
    treatment: ArmScore,
    floor: Mapping[str, int],
    kept_pairs: Iterable[Pair],
    thresholds: Thresholds,
) -> GateResult:
    """Decide PASS / NOOP / FAIL on the KG-independent certified counts. FAIL bounds checked FIRST.

    Ordering matters: a fix that moved the headline the right way but destroyed good links (certified
    fell below baseline-floor), raised refuted beyond floor, or regressed ANY single kept link from
    certified->refuted FAILs before it can be credited with an improvement. Only then can an
    improvement (refuted down / refused down / certified up, each beyond the floor) earn a PASS; when
    nothing moves beyond the floor it is a NOOP.

    The aggregate deltas AND the absolute-threshold backstops are measured over the RETAINED links
    (``kept_pairs``) only, not the full ``CertifiedOverlap`` totals. Otherwise a change confined to
    RefMet-parity-EXCLUDED links (a coverage swing, not a correctness one) could flip the verdict even
    though no retained link moved — the same aggregate-pooling failure the per-link guard exists to
    catch. An empty ``kept_pairs`` means no parity mask was applied (``confound_gate`` already ABSTAINs
    when a mask excludes *every* comparable link, before ``decide`` runs), so it falls back to the full
    aggregate — preserving the no-mask contract the pure decision tests exercise.
    """
    fc, fr, fu = floor["certified"], floor["refuted"], floor["refused"]

    b_verdict = {(a, bn): v for (a, bn, v) in baseline.certified.per_link}
    t_verdict = {(a, bn): v for (a, bn, v) in treatment.certified.per_link}
    kept = set(kept_pairs)
    regressed = sorted(p for p in kept if b_verdict.get(p) == "certified" and t_verdict.get(p) == "refuted")

    if kept:
        b_counts = _counts_over(baseline.certified.per_link, kept)
        t_counts = _counts_over(treatment.certified.per_link, kept)
    else:
        b_counts = {m: getattr(baseline.certified, m) for m in _METRICS}
        t_counts = {m: getattr(treatment.certified, m) for m in _METRICS}
    deltas = {m: t_counts[m] - b_counts[m] for m in _METRICS}

    fails: list[str] = []
    if thresholds.min_certified is not None and t_counts["certified"] < thresholds.min_certified:
        fails.append(f"certified {t_counts['certified']} below hard floor {thresholds.min_certified}")
    if thresholds.max_refuted is not None and t_counts["refuted"] > thresholds.max_refuted:
        fails.append(f"refuted {t_counts['refuted']} above hard ceiling {thresholds.max_refuted}")
    if regressed:
        fails.append(f"per-link refuted regression (certified->refuted) on {regressed}")
    if deltas["certified"] < -fc:
        fails.append(f"certified fell {deltas['certified']} beyond floor {fc} (over-correction destroyed good links)")
    if deltas["refuted"] > fr:
        fails.append(f"refuted rose {deltas['refuted']} beyond floor {fr}")
    if fails:
        return GateResult("FAIL", deltas, dict(floor), (), True, tuple(fails))

    improvements: list[str] = []
    if deltas["refuted"] < -fr:
        improvements.append(f"refuted fell {deltas['refuted']} beyond floor {fr}")
    if deltas["refused"] < -fu:
        improvements.append(f"refused fell {deltas['refused']} beyond floor {fu}")
    if deltas["certified"] > fc:
        improvements.append(f"certified rose {deltas['certified']} beyond floor {fc}")
    if improvements:
        return GateResult("PASS", deltas, dict(floor), (), True, tuple(improvements))
    return GateResult("NOOP", deltas, dict(floor), (), True, ("all deltas within the noise floor",))


# --- Unit 6: positive-control self-test ------------------------------------------------------------


def positive_control_selftest(
    prereg: Prereg,
    baseline: ArmScore,
    control: ArmScore,
    floor: Mapping[str, int],
    kept_pairs: Iterable[Pair],
    thresholds: Thresholds,
) -> GateResult | None:
    """Run the decision on the pre-registered KNOWN-BAD arm. Return ABORT if it is not detected.

    If ``decide(baseline, control)`` does not produce ``prereg.positive_control_required`` (FAIL/ABSTAIN),
    the decision core cannot catch a plant, so the whole gate is invalid -> ABORT. Otherwise return
    ``None`` (self-test cleared; the real verdict may proceed).
    """
    probe = decide(baseline, control, floor, kept_pairs, thresholds)
    if probe.decision != prereg.positive_control_required:
        return GateResult(
            "ABORT",
            deltas=probe.deltas,
            noise_floor=dict(floor),
            positive_control_ok=False,
            reasons=(
                f"positive control arm {prereg.positive_control_arm!r} produced {probe.decision}, "
                f"required {prereg.positive_control_required} — the gate cannot detect a known-bad arm; "
                "the improvement verdict is not trustworthy",
            ),
        )
    return None


# --- Unit 7: orchestration -------------------------------------------------------------------------


def _pooled_floor(
    baseline: ArmReplicates, treatment: ArmReplicates, kept_pairs: Iterable[Pair] | None = None
) -> dict[str, int]:
    """Conservative floor = elementwise max of each arm's replicate range (the noisier arm wins).

    ``kept_pairs`` threads through to ``noise_floor`` so the floor is measured over the SAME
    RefMet-parity-retained population as ``decide``'s deltas (avoids the aggregate-vs-kept mismatch).
    """
    fb, ft = noise_floor(baseline, kept_pairs), noise_floor(treatment, kept_pairs)
    return {m: max(fb[m], ft[m]) for m in _METRICS}


def evaluate_conflation_gate(prereg: Prereg, arms: Mapping[str, ArmReplicates]) -> GateResult:
    """Orchestrate the pure gate: confound gate -> noise floor -> positive-control self-test -> decide.

    ``arms`` must contain ``"baseline"``, ``"treatment"``, and ``prereg.positive_control_arm``. Pure and
    deterministic: no I/O, same inputs -> same verdict. Short-circuits to ABSTAIN on any confound and to
    ABORT if the positive control is not detected, before it will emit an improvement verdict.
    """
    baseline = arms["baseline"]
    treatment = arms["treatment"]

    abstain, kept, excluded = confound_gate(prereg, baseline, treatment)
    if abstain is not None:
        return abstain

    floor = _pooled_floor(baseline, treatment, kept)
    b_rep = representative(baseline, kept)
    t_rep = representative(treatment, kept)
    control_rep = representative(arms[prereg.positive_control_arm], kept)

    abort = positive_control_selftest(prereg, b_rep, control_rep, floor, kept, prereg.thresholds)
    if abort is not None:
        return dataclasses.replace(abort, excluded_pairs=excluded)

    result = decide(b_rep, t_rep, floor, kept, prereg.thresholds)
    return dataclasses.replace(result, excluded_pairs=excluded)


# --- Unit 8: LIVE supervised runner (never unit-tested; decision logic covered by units 1-7) -------


def run_conflation_gate(*args, **kwargs):  # pragma: no cover - supervised live step, never in pytest
    """LIVE, SUPERVISED operator step. Drive Unit E per arm x >=3 replicates against a COLD dev API,
    resolve source-tagged independent oracles (small molecules via ``PubChemInChIKeyResolver``; lipids
    via a source-DISJOINT LIPID MAPS oracle so the certificate is not circular), score each replicate
    with ``score_arm``, then run the pure ``evaluate_conflation_gate`` on the observed arms.

    Persist-by-default (R23): write ``prereg.json`` FIRST (the pre-registered contract), then
    ``result.json`` (the verdict + deltas + noise floor + excluded pairs) under a timestamped path, and
    print the path. Deliberately unimplemented in committable library code — wiring the live dev API +
    lipid oracle belongs in the gated operator harness (and depends on ``biomapper-fix`` producing the
    re-resolution arm and the source-tagged lipid structures), not in importable code a test could trip.
    """
    raise NotImplementedError(
        "run_conflation_gate is a supervised live step; run it from the gated Unit F operator harness "
        "once biomapper-fix has produced the re-resolution arm and the source-tagged lipid oracle"
    )
