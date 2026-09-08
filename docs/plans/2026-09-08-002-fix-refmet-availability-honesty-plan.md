---
status: active
created: 2026-09-08
origin: docs/brainstorms/2026-09-08-refmet-availability-honesty-requirements.md
depth: deep
reviewed: 2026-09-08 (document-review: coherence + feasibility + adversarial; P-highs folded in)
---

# RefMet annotator availability — honesty + resilience — Plan

## What this plan does (and does NOT) — read first
Two SEPARATE wins, deliberately not conflated:
- **Resilience (the scoring fix).** Stop the circuit breaker from silently blanking RefMet for the rest of
  a batch. This RESTORES RefMet source-weighting coverage in batch mode, so rows that today miss RefMet
  (e.g. retinol) get the `divergent_refmet` correction they get in single mode. This CHANGES scored
  benchmark numbers on rescued rows — that is the intended effect, not a violation of "resolver unchanged".
- **Honesty/observability (detectability).** Surface RefMet UNAVAILABILITY as a distinct state (per-row +
  certificate + run metric), so residual degradation is detectable instead of silent. **On its own this
  changes NO scored number** — no scorer reads it yet. The harness consuming it (exclude/flag degraded runs)
  is a studies/ follow-up (off-org), explicitly OUT of this src/ PR (see O4).

If neither the resilience win nor the detectability win survives the Phase 0 spike + worst-case wall-clock
proof, a no-op STOP is acceptable.

## Problem frame
`src/biomapper2/core/annotators/metabolomics_workbench.py`: `_fetch_refmet_data` returns `None` for THREE
distinct outcomes — genuine no-match (`refmet_id == "-"`), open breaker (`CircuitBreakerError`), transport
error (`requests.RequestException`) — and `get_annotations` maps `None` to `{slug: {}}`. `_do_refmet_request`
is `@circuit(failure_threshold=3, recovery_timeout=300)` + `timeout=3`; `get_annotations_bulk` fires an
unpaced serial loop. A few timeouts trip the breaker → RefMet empty for the rest of the run, silently. Live
evidence: /entity + /batch n=1 retinol → CHEBI:12777 via `divergent_refmet`; /batch n≥2 and n=400 → the whole
400-name NECS corpus gets `metabolomics-workbench={}` and falls to majority CHEBI:132246 (Unit 0 artifacts,
~/external_benchmark_runs/unit0_*).

## Design precedent (reuse, do not invent)
The certificate already distinguishes "service failed" from "genuine negative": `tier_b_outcome` carries
`lookup_failed` vs `unresolvable`; `equivalent_ids_lookup_ok: bool` is a runtime availability input to
`issue()`. RefMet availability is modeled identically. Verified facts from review: appending a defaulted
`refmet_availability` to the frozen dataclass + the hand-built `to_api_dict`/`to_flat_columns` is additive;
`ResolutionCertificateModel` has no `ConfigDict` (pydantic ignores the extra key until U4 adds it, and U3→U4
ordering prevents an orphaned state); `Entity` has `ConfigDict(extra="allow")` so the single path can carry
the status via `model_extra` with no new Entity field; `CachedSession` uses default `allowable_codes=(200,)`
so timeouts/5xx are NOT cached (only genuine "-" no-match is), which must stay default.

## Scope boundary
- IN: `metabolomics_workbench.py` (status distinction + resilience); `base.py` availability contract; the
  four non-MW annotators (default no-op only); `annotation_engine.py` accumulation + return contract;
  `mapper.py` threading to `issue()`; `certificate.py` field; `api/models/responses.py` + `api/routes/
  mapping.py` surface; run-level metric in the batch/dataset mapper path.
- OUT: resolver selection/tie-break CODE (unchanged); the studies/ benchmark harness consuming the metric
  (O4, off-org follow-up); Goslin/Kestrel resilience fixes (audit only, O2).

## Requirements traceability
| Req | Unit |
|-----|------|
| R1 unavailable != no-match at the annotator | U1 |
| R2 per-row availability in the mapping result (REQUIRED, not optional) | U2, U4 |
| R3 certificate availability field, runtime input to issue() | U3, U4 |
| R4 resilience: a mid-batch failure subset does not blank the rest, within a bounded wall-clock | U1 |
| R5 run-level availability metric (cold-run-attributable) | U5 |
| R6a resolver CODE + no-match path unchanged | U6 |
| R6b rescued rows DO change chosen_kg_id (expected, asserted by direction) | U6 |

## Key decisions
- **D1 annotator status.** `_fetch_refmet_data` returns a typed result with `status ∈ {VOTED, NO_MATCH,
  UNAVAILABLE}` (+ payload). `refmet_id == "-"` → NO_MATCH; breaker-open/transport/timeout → UNAVAILABLE;
  data → VOTED. `get_annotations` emits vote (VOTED) / empty (NO_MATCH) and reports UNAVAILABLE via the
  side-channel — never folds UNAVAILABLE into the empty vote dict.
- **D2 extraction mechanism (was the plan's central gap).** Add a default availability method to
  `BaseAnnotator` returning an all-`not_queried` map; ONLY `MetabolomicsWorkbenchAnnotator` overrides it (and
  later Goslin per O2). `annotation_engine.annotate` accumulates a per-row `annotator_availability:
  dict[slug, status]` in parallel to `_merge_nested_dicts`, and EVERY empty/skip branch
  (`mode == 'none'`, no-annotators, empty frame, provided-id-only) emits a TOTAL `not_queried` map so a
  consumer never reads `None`. Surface it: single path via `Entity.model_extra` (extra="allow"); dataset
  path as an added DataFrame column. `AssignedIDsDict` is NOT touched (keeps the resolver vote clean).
- **D3 certificate field.** Add `refmet_availability: str = "not_queried"` to `ResolutionCertificate`,
  `issue()` kwarg, `to_api_dict`, `to_flat_columns` (`certificate_` prefix). `not_queried` when RefMet was
  not selected for the row, so the field is total.
- **D4 resilience WITH a hard wall-clock bound (redesigned after review).** The breaker today is the only
  wall-clock bound (~9s fast-fail); do NOT loosen it into unboundedness. Instead:
  1. Retry lives INSIDE the `@circuit`-decorated `_do_refmet_request` (verified: circuitbreaker 2.1.3 counts
     one raise per decorated call, so an internal retry that ultimately fails counts ONCE, and one that
     succeeds resets — putting the retry ABOVE the decorator would trip it FASTER, the reverse of intent).
     At most 1 retry with a short bounded backoff; modestly raise the timeout (O3, ~8s).
  2. Add a HARD per-batch deadline in `get_annotations_bulk`: once elapsed, remaining names are marked
     UNAVAILABLE immediately (no network), so worst-case wall-clock is bounded regardless of retry
     accounting. NO serial pacing (it only adds time). Bounded concurrency is an allowed alternative if it
     proves faster without tripping endpoint rate limits (O3), but the deadline is the guarantee.
  3. Keep breaker `failure_threshold`/`recovery_timeout` roughly as-is (a bound, not a liability); only
     the internal retry reduces spurious single-slow-call trips.
  Worst-case must be proven: `batch_time <= min(deadline, N × (timeout × (1+retries) + backoff))`, with an
  explicit operator-tolerable deadline set in O3, BEFORE U-live. Backoff/deadline use an injectable clock
  (0 / immediate in tests).
- **D5 run metric (single home).** The batch/dataset mapper path (NOT the annotator) aggregates
  `refmet_unavailable_rows / total` into the batch/dataset response `summary`. Because CachedSession caches
  successes, the metric is only attributable on a COLD cache; record cache hit/miss beside it and mark it
  cold-run-only for any gating use.

## Implementation units
### U0 — diagnostic spike (mocked session; test, fails-first)
`tests/test_refmet_availability.py`. Mocked `_do_refmet_request` raises/timeouts on the first 3 names then
would-succeed; drive `get_annotations_bulk` over N names; assert that on TODAY's code the post-trip names
return `{slug: {}}` — silently identical to a "-" no-match. RED on current code. If not reproducible, STOP.

### U1 — annotator: status + bounded resilience  [feature-bearing]
`src/biomapper2/core/annotators/metabolomics_workbench.py`. D1 status result; retry INSIDE the decorated
method; timeout↑; hard per-batch deadline in the bulk loop; keep `allowable_codes` default.
Tests (`tests/test_refmet_availability.py`, ≤8): mid-batch UNAVAILABLE does not blank the rest (turns U0
green); genuine "-" stays NO_MATCH; a one-off slow call succeeds on retry and breaker failure_count
increments by exactly 1 (0 when retry succeeds); deadline marks the tail UNAVAILABLE fast.

### U2 — availability contract + plumbing  [feature-bearing]
`src/biomapper2/core/annotators/base.py` (default all-`not_queried` method), the four non-MW annotators
(inherit default, no behavior change), `src/biomapper2/core/annotation_engine.py` (accumulate the per-row
map across annotators incl. ALL skip/empty branches; single→`Entity.model_extra`, dataset→new column),
`src/biomapper2/mapper.py` (read RefMet status; pass `refmet_availability` into the `issue()` calls).
Tests (`tests/test_refmet_availability_plumbing.py`, ≤8): engine emits a TOTAL map incl. skip branches;
mapper forwards the correct status to issue() (assert kwarg).

### U3 — certificate field  [feature-bearing]
`src/biomapper2/core/certificate.py`: add the field + `issue()` kwarg (default `not_queried`) + both
surfaces. Tests (`tests/test_certificate_availability.py`, ≤8): field carried for all four values; existing
certificate invariants unaffected.

### U4 — API + per-row result surface  [feature-bearing]
`src/biomapper2/api/models/responses.py` (`ResolutionCertificateModel.refmet_availability`; REQUIRED
per-row mirror on `EntityMappingResult` per R2), `src/biomapper2/api/routes/mapping.py`
(`extract_mapping_result` passes it through). Fold tests into U3's file (respect ≤8/file).

### U5 — run-level metric  [feature-bearing]
Batch/dataset mapper path + response `summary`; record cache hit/miss; mark cold-run-only.
Test: a batch with K unavailable rows reports K/total.

### U6 — resolver split guard  [feature-bearing]
`tests/test_refmet_availability_plumbing.py` (or a small file): R6a — a genuine NO_MATCH row resolves
exactly as today (empty vote → majority), certificate/selection unchanged. R6b — a name that is UNAVAILABLE
on first attempt then VOTED on retry changes chosen_kg_id from the no-RefMet majority to the RefMet-weighted
node (assert the DIRECTION, e.g. → CHEBI:12777; do not claim invariance).

### U-live — supervised confirmation (operator; # pragma no cover)
COLD cache (clear `metabolomics_workbench_http` first); re-run the 400-name NECS batch on a restarted fixed
instance (8007/8008); assert per-row `refmet_availability` + run metric present, a degraded run is flagged
not silently blanked, wall-clock within the D4 deadline, and record cache hit/miss so the result is
attributable to D4 not cache-warming. Persist the transcript by default.

## Sequencing & gates
U0 fails-first → U1 turns it green (+ prove worst-case wall-clock) → U2 → U3 → U4 → U5 → U6 →
`uv run` ruff/black/pyright/pytest green → U-live (cold) → PR to fork trentleslie/biomapper2 base dev →
greptile-loop 5/5 → then Phenome-Health. Never straight to org/main. Do NOT use the /brainstorm Workflow
tail (fork default branch is `chore/repo-cleanup`; its open-pr targets the default branch) — implement
directly and `gh pr create --base dev`, run greptile-loop by hand.

## Open questions (implementation-time)
- O1 (representation) RESOLVED by D2: parallel `annotator_availability` map via BaseAnnotator default +
  engine accumulation + Entity.model_extra (single) / column (dataset); never an AssignedIDsDict sentinel.
- O2: audit whether goslin-lipid / kestrel share the swallow-to-empty-under-breaker pattern; scope any
  generalization as a follow-up (do not fix here).
- O3: resilience values — timeout (~8s), retry (1) + backoff, per-batch deadline (operator-tolerable, set
  before U-live), optional bounded concurrency. Keep sleeps/clock injectable.
- O4 (out of scope, follow-up): the studies/ harness consuming R5's metric (exclude vs flag a degraded run).
  Until it lands, the honesty fields change NO scored number; only the D4 resilience win moves numbers.

## Constraints
uv run; ruff/black line-length 120; pyright gates src+tests; ≤8 tests/file (split files as noted);
mocked session in tests (never a live call in pytest; live 8007/8008 + Metabolomics Workbench are supervised
operator steps, # pragma no cover); persist diagnostic artifacts by default; fork-first PR flow.

## Risks
- R-a: touching `AssignedIDsDict` would pollute the resolver vote — avoided by the parallel side-channel (D2)
  + U6a guard.
- R-b: certificate schema change ripples (flat TSV, API model, streaming dict) — mirror the existing
  `tier_b_outcome`/`equivalent_ids_lookup_ok` plumbing; `not_queried` keeps the field total; only
  exact-equality dict/column tests need updating (expected).
- R-c: D4 wall-clock blowup on a slow-but-alive endpoint — bounded by the hard per-batch deadline + at most
  1 retry + no pacing; worst case proven before U-live.
- R-d: warm-cache false validation / non-reproducible metric — U-live runs COLD and records cache hit/miss;
  metric is cold-run-only.
- R-e: rescued rows move benchmark numbers and could be mistaken for a regression — R6b makes the direction
  explicit and expected (more RefMet coverage, not less).
