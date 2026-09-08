# RefMet annotator availability — honesty + resilience — Requirements

Created: 2026-09-08
Status: draft (Checkpoint 1)
Scope: PRODUCTION src/. Fork trentleslie/biomapper2 base dev -> Greptile -> then Phenome-Health. NOT studies/.
Depth: Standard-plus (annotator + bulk path + annotation result contract + certificate input/field + API model).
Origin: Unit 0 live diagnosis 2026-09-08 (~/external_benchmark_runs/unit0_resolver_determinism_20260908T104623Z/).

## Problem

Under batch/dataset load the RefMet (`metabolomics-workbench`) annotator silently stops voting, and its
absence is indistinguishable from a genuine "no RefMet match". Pinned cause in
`src/biomapper2/core/annotators/metabolomics_workbench.py`:
- `_do_refmet_request` wrapped in `@circuit(failure_threshold=3, recovery_timeout=300)`, `session.get(url,
  timeout=3)`; `requests.RequestException` and `CircuitBreakerError` are swallowed to `None`.
- `get_annotations` maps `None` / `refmet_id == "-"` to an EMPTY annotation `{slug: {}}`.
- `get_annotations_bulk` fires an UNPACED serial loop of live calls to a slow external endpoint.

In a batch the flaky endpoint times out a few times -> 3 failures trip the breaker -> it OPENS for 300s ->
RefMet returns empty for the REST of the run, silently. Live evidence: /entity retinol and /batch n=1 ->
CHEBI:12777 via `divergent_refmet` (RefMet votes); /batch n=2 and n=400 -> the WHOLE 400-name NECS corpus
gets `metabolomics-workbench={}` and falls to the plain majority CHEBI:132246.

## Impact

Any batch/dataset benchmark run silently drops RefMet source-weighting for most rows once the breaker
trips -> a systematic, non-deterministic class of "biomapper misses" and spurious divergences in the
cross-cohort concordance numbers, and non-reproducible per-row verdicts. A row that missed RefMet because
RefMet was UNAVAILABLE is currently scored identically to a row where RefMet genuinely had no match.

## Decisions (Checkpoint 1)

- **D1 (honesty, core):** RefMet UNAVAILABILITY (timeout / open breaker / transport error) becomes a
  DISTINCT, SURFACED state, never collapsed into an empty no-match. Surfaced BOTH as (A) a per-row
  annotator status in the mapping result AND (B) a first-class field in the resolution certificate.
  Precedent: `certificate.issue()` already takes `equivalent_ids_lookup_ok` (a runtime "lookup failed"
  signal distinct from "no structure") — model annotator availability the same way (a runtime input to
  `issue()`, not a computed-from-graph value), so the "pure certificate" contract is preserved.
- **D2 (resilience):** reduce how often the breaker blanks a run — bounded pacing/throttle (or bounded
  concurrency) in `get_annotations_bulk`; a larger timeout with one retry/backoff before a failure counts
  toward the breaker; breaker tuning (`failure_threshold` / `recovery_timeout`) so a few slow calls cannot
  blank a large batch. Exact values set in planning; resilience only lowers the frequency of the honest
  UNAVAILABLE state, it does not replace it.
- **D3 (run-level signal):** emit a run-level RefMet availability metric (fraction of rows where RefMet was
  unavailable) so the benchmark harness can flag/exclude a degraded run. Lightweight; harness consumption
  decided in planning.

## Requirements Trace

- R1. `unavailable` (timeout/open-breaker/transport) is DISTINCT from genuine no-match (`refmet_id == "-"`)
  and from a successful vote, at the annotator boundary.
- R2. Per-row mapping result carries the RefMet availability status (A).
- R3. The resolution certificate carries an annotator-availability field, plumbed as a runtime input to
  `issue()` alongside `equivalent_ids_lookup_ok` (B); surfaced in the API response model.
- R4. Resilience: one slow/timing-out subset of a batch must NOT zero RefMet for the remaining rows (D2).
- R5. A run-level availability metric is emitted (D3).
- R6. The resolver SELECTION logic is unchanged; genuine no-match still yields an empty RefMet vote and the
  existing majority/divergent_refmet behavior (this change is about availability signalling + resilience,
  not re-scoring).

## Scope Boundaries

- IN: `metabolomics_workbench.py` (fetch/bulk/error handling), the annotation result contract for the
  per-row status, `certificate.issue()` new availability input + certificate field, the API response
  model, the run-level metric.
- OUT: resolver selection/tie-break (untouched); other annotators' resilience (AUDIT whether goslin/kestrel
  share the swallow-to-empty pattern and note as a follow-up, do not fix here); the benchmark harness's
  exclude-vs-flag policy beyond emitting the metric.

## Success Criteria

- Phase 0 (diagnostic, mocked session, NO live call): a batch where the mocked RefMet session times
  out / raises on some names and the breaker opens must reproduce "RefMet empty for the remaining rows" on
  TODAY's code — the failing-first repro. If it cannot be reproduced against the current code, STOP.
- Regression tests (mocked session; <=8/file): (a) a mid-batch timeout/breaker-open surfaces `unavailable`
  for affected rows and does NOT silently zero RefMet for the rest; (b) a genuine `"-"` no-match surfaces
  as empty/no-match, NOT `unavailable` (the two must not be conflated); (c) the certificate carries the
  availability field for both cases; (d) the run-level metric counts unavailable rows.
- Live supervised confirmation (operator, # pragma no cover): re-run the 400-name NECS batch on 8007/8008;
  RefMet availability is surfaced per row + run-level, and a degraded run is visibly flagged rather than
  silently blanked.
- No regression in existing annotator/certificate/mapper/API tests; ruff/black/pyright green.
- A no-op / can't-improve is an acceptable STOP.

## Open Questions (planning)

- O1: exact representation of the per-row `unavailable` status in the annotation return dict (a status key
  vs a sentinel) without breaking existing consumers of `assigned_ids`.
- O2: do goslin-lipid / kestrel annotators share the swallow-to-empty-under-breaker pattern? Audit; scope
  any generalization as a follow-up.
- O3: resilience parameter values (timeout, retry/backoff, pacing rate/concurrency, breaker threshold and
  recovery) — set from the observed endpoint behavior in planning.
- O4: does the benchmark harness EXCLUDE or FLAG rows/runs with unavailable RefMet? (D3 emits the metric;
  policy is a harness decision.)

## Constraints

Production src/ (fork dev -> Greptile -> org, never straight to org/main); uv run; ruff/black line-length
120; pyright gates src+tests; <=8 tests/file; monkeypatch network in tests (never a live call in pytest —
simulate timeout / breaker-open / "-" via a mocked session; live 8007/8008 + Metabolomics Workbench are
supervised operator steps marked # pragma: no cover); persist diagnostic artifacts by default.
