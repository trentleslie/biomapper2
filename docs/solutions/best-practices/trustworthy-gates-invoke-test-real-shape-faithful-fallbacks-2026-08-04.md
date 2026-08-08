---
title: "Trustworthy gates: invoke them, test the real producer shape, keep fallbacks semantically faithful"
date: 2026-08-04
category: best-practices
module: biomapper2
problem_type: best_practice
component: testing_framework
severity: high
related_components:
  - tooling
  - service_object
applies_when:
  - "building a threshold/regression-floor gate that must fail closed on a capability drop"
  - "a declared gate config or assert helper exists but you have not verified the run path calls it"
  - "writing gate tests from a hand-built fixture instead of the real producer's output shape"
  - "adding a fallback that substitutes a different measurement when the target regime is absent"
tags:
  - benchmark-gate
  - regression-floor
  - false-confidence
  - test-fixture-drift
  - fail-closed
  - lmsd
---

# A gate is only trustworthy if it's invoked, tested against real producer output, and its fallbacks preserve intent

## Context

In `biomapper2` (`studies/external_benchmarks`), the LMSD lipid benchmark was re-cast post-Goslin from an accuracy headline into a **capability-regression gate**: shorthand lipid resolvability must stay ≥ 0.90 or the run should fail closed. The author added a config `role="capability_regression"` with `regression_floor=0.90`, plus `assert_capability_floor(...)` and `capability_resolvability(...)` in `scorers/regression.py`.

The gate looked complete and passed its own test suite. Greptile review — not local tests — surfaced **three linked defects, each producing false confidence**: a passing run that actually enforced nothing, would crash in production, or could pass while measuring the wrong thing. The three defects are three distinct ways the same guard can be hollow, which is why they generalize into one principle worth keeping.

## Guidance

A gate/guard/threshold is only as trustworthy as three independent properties. Each LMSD defect violated exactly one. When you build any fail-closed check, verify all three:

### (a) It is actually invoked in the real code path

A declared floor constant and an `assert_*` helper that nothing calls is **dead config**. It reads like a safety net and enforces nothing — a regressed capability gets scored, persisted, and reported as a passing run.

- **Wrong:** `assert_capability_floor` and `regression_floor=0.90` exist; `orchestrate_lmsd` (the actual run path) never calls them.
- **Right:** Wire the gate into `orchestrate_lmsd` **after scoring, before persisting**, and record the measured value for provenance.

```python
# In orchestrate_lmsd, after scoring:
resolvability = capability_resolvability(result, regime="shorthand")
write_json("capability_regression.json", {"resolvability": resolvability, "floor": floor})
assert_capability_floor(result, floor, regime="shorthand")  # raises -> fails closed
persist(result)  # only reached if the gate passed
```

**Check:** grep the run path for the gate call. If the assertion isn't on the line between "scored" and "persisted," it isn't guarding anything.

### (b) Its tests exercise the REAL producer's data shape

A hand-built fixture that diverges from what the upstream function actually emits can make a test green while production throws. Here, `capability_resolvability`'s fallback read `result["comparable_core"]["coverage"]["fraction"]`, but the real producer `score_structure_oracle` emits `coverage` at the **result root** (`result["coverage"]`) — `comparable_core` has no `coverage` sub-key. Any LMSD result lacking a shorthand regime would `KeyError` in production, *after* the provenance file was already written. It wasn't caught because the orchestrator test built a fixture that duplicated `coverage` under **both** locations — a shape the producer never emits.

- **Wrong:**
```python
# fixture invents a shape the producer never emits
fixture = {"comparable_core": {"coverage": {"fraction": 0.9}}, "coverage": {"fraction": 0.9}}
# code reads the fictional path
frac = result["comparable_core"]["coverage"]["fraction"]  # KeyError in prod
```
- **Right:** read the real path, and derive the fixture from the actual producer:
```python
frac = result["coverage"]["fraction"]

# fixture built from the real producer, not by hand:
result = score_structure_oracle(sample_input)   # or a snapshot of its output
assert "coverage" not in result.get("comparable_core", {})  # pin the real shape
```
Add a regime-less regression test that **fails on the old code** and passes on the fixed path.

**Check:** if a test's fixture is hand-authored, ask "does the upstream function actually emit this?" Prefer asserting against real producer output (or a snapshot of it) over a shape you invented.

### (c) Its fallbacks preserve the gate's semantic intent

A convenience fallback can silently change **what** is measured, letting an unrelated signal satisfy a specific threshold. LMSD's fallback-to-blended-coverage did exactly this: if a release dropped its `ABBREVIATION` field, the scorer omits the shorthand regime, and **blended** coverage (mostly non-shorthand) could clear the **shorthand** floor — a run measuring zero shorthand observations passes.

- **Wrong:**
```python
def capability_resolvability(result, regime):
    r = result["regimes"].get(regime)
    if r is None:
        return result["coverage"]["fraction"]  # blended — different measurement
    return r["fraction"]
```
- **Right — regime-strict, fail closed on absence:**
```python
def capability_resolvability(result, regime):
    r = result["regimes"].get(regime)
    if r is None or r["observations"] == 0:
        return None                    # no substitute measurement
    return r["fraction"]

def assert_capability_floor(result, floor, regime="shorthand"):
    val = capability_resolvability(result, regime)
    if val is None:
        raise CapabilityRegression(f"no {regime} observations — cannot certify floor")
    if val < floor:
        raise CapabilityRegression(f"{regime} resolvability {val:.3f} < floor {floor}")
```
Cover it: regime-absent, regime-empty (zero observations), and a high-blended-must-still-fail case, plus an end-to-end `orchestrate_lmsd` test.

**Check:** for every fallback branch, ask "does this return the same *kind* of number the threshold was written about?" If it substitutes a different signal, fail closed instead.

## Why This Matters

A broken gate is worse than no gate: no gate is honestly absent, but a gate that looks safe manufactures **false confidence**. Someone reads `regression_floor=0.90` in config and reasonably assumes regressions can't ship — so the guard becomes the reason no one checks manually. All three LMSD defects had this signature:

- Dead config → every run "passes" the floor it never evaluated.
- Fictional-shape test → the suite is green while production crashes post-write, leaving a half-written provenance artifact.
- Blended fallback → the run passes on a number that has nothing to do with the capability being gated.

The failure mode is silent and self-reinforcing, which is why two of the three surfaced only in adversarial review, not local tests. Polished, complete-looking guard code earns *more* scrutiny, not less.

## When to Apply

- Any threshold / floor / ceiling / `assert_*` / guard / fail-closed check — especially in **eval, benchmark, gate, or CI** code where a false pass is invisible until it matters.
- Any test whose **fixture stands in for a real producer's output** (scorers, parsers, API-response handlers, serializers).
- Any guard with a **fallback / default / "if missing" branch** — that branch is where semantic intent quietly leaks.
- Reviewing others' guard code: run the three checks explicitly rather than trusting that a green suite means the gate works.

## Examples (wrong → right, at a glance)

| Property | Wrong | Right |
|---|---|---|
| (a) Invoked | `assert_capability_floor` defined, never called in `orchestrate_lmsd` | Called after scoring / before persist; writes `capability_regression.json` |
| (b) Real shape | Reads `result["comparable_core"]["coverage"]["fraction"]`; test fixture duplicates `coverage` in both spots | Reads `result["coverage"]["fraction"]`; fixture derived from `score_structure_oracle`; regime-less regression test |
| (c) Fallback intent | Missing shorthand regime → return blended coverage (passes on non-shorthand data) | Missing/empty regime → return `None`; `assert` fails closed with "no shorthand observations" |

## Related
- Surfaced during the Greptile review of the Goslin-lipid benchmark PR (`trentleslie/biomapper2`, base `dev`), 2026-08-04. Companion learning from the same review cycle: [gitignore globs silently excluding pinned benchmark data](../runtime-errors/gitignore-globs-exclude-pinned-benchmark-data-2026-08-04.md).
