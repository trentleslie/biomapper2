---
title: "feat: Optional pass-through of raw Kestrel search results"
type: feat
status: active
date: 2026-09-21
deepened: 2026-09-21
origin: docs/brainstorms/kestrel-passthrough-requirements.md
---

# feat: Optional Pass-Through of Raw Kestrel Search Results

**Target repo:** biomapper2 (origin = fork `trentleslie/biomapper2`; branch off `origin/dev`,
PR to fork base `dev` for Greptile first, then Phenome-Health). All paths below are repo-relative.

> **Deepened 2026-09-21** after a 5-persona document review (coherence, feasibility, security,
> scope-guardian, adversarial), all run against the live code. Two P1 design corrections were folded
> in: (1) selection invariance is **not** "true by construction" — passthrough shares the RefMet
> wall-clock batch deadline, global request counters, and the HTTP cache, so it must be executed
> *after* the RefMet-armed window and proven with a timed test; (2) the used-endpoint set must be
> **recorded during mapping**, not re-derived from `_select_annotators` (which omits the mode/provided-id
> skip and would violate R6). Two items are deferred to your Checkpoint-2 judgment (R9 hard cap;
> Phase 0.4 experiment scope) — see Open Questions.

## Overview

Add an opt-in side channel that returns the top-N raw rows Kestrel returned per search endpoint the
pipeline actually used, untouched, alongside the normal mapping result. A new request option
`MappingOptions.kestrel_top_n` (1..100, `None` disables) turns it on; a new response field
`EntityMappingResult.kestrel_results` carries the rows. Selection — `chosen_kg_id`, `assigned_ids`,
resolver vote, certificate — is unchanged for any `kestrel_top_n`.

Two decisions from the brainstorm shape the design: **fetch strategy = `separate_call`** (dedicated
`limit=N` calls, selection calls untouched) and **`/map/dataset` → 422**. The document review then
forced a third: because the passthrough calls are not free of shared side effects, the pipeline
**records** which Kestrel endpoints it used per entity during mapping, and the **route layer executes
the passthrough after the RefMet-armed batch-deadline window closes**, attaching the rows to each
result. The selection/annotation/resolution spine is byte-identical to today; passthrough never feeds
back into it.

## Problem Frame

Three Kestrel annotators (`kestrel_text`, `kestrel_vector`, `kestrel_hybrid`) each receive a ranked
list and commit at most one row; the rest is discarded (hybrid also drops `score < 0.5` in the return
of `_kestrel_hybrid_search`, `src/biomapper2/core/annotators/kestrel_hybrid.py:284`). Downstream
consumers (ddharmon, benchmarking, adjudication, error analysis) cannot audit why a `chosen_kg_id` won
or inspect near-misses without re-querying Kestrel out-of-band. See origin:
`docs/brainstorms/kestrel-passthrough-requirements.md`.

## Requirements Trace

Requirement/test/verification IDs are preserved verbatim from the origin doc.

- R1. `MappingOptions.kestrel_top_n: int | None = None`, `ge=1, le=100` (422 out of range); keep `extra="ignore"`.
- R2. `EntityMappingResult.kestrel_results: list[KestrelSearchResult] | None = None` (omitted/None when option unset).
- R3. Rows captured raw — before hybrid `>=0.5` filter, `stable_result_order`, category guards, re-ranking.
- R4. Selection invariance across `kestrel_top_n ∈ {None,1,20,100}` (primary acceptance criterion) — see Key Decisions for the corrected, *non*-by-construction argument.
- R5. Single + bulk paths both populate; per-entity isolation; respect `KESTREL_BATCH_SIZE_SEARCH` (discharged as a deliberate per-entity trade-off — see below).
- R6. No-Kestrel-call entities → `kestrel_results: []` when option set (guaranteed by the recorded-endpoints design, not by re-derivation).
- R7. Passthrough failure isolation → record a classified `error`, empty `rows`, mapping result unaffected.
- R8. `/map/entity` + `/map/batch` (body) + `/map/dataset/stream` (query); `/map/dataset` → 422.
- R9. Document worst-case payload; **hard-enforced batch cap** (422/413 when `len(entities) × kestrel_top_n × endpoints_used` exceeds a documented threshold) — decided at Checkpoint 2, reversing the spec's "propose not impose".
- R10. README + OpenAPI: `candidate_limit` moves the selection window, `kestrel_top_n` cannot.

## Scope Boundaries

- No change to annotator selection, re-ranking, resolver voting, or the certificate.
- No merging of rows across endpoints (text/vector/hybrid scores are on different scales).
- No new top-level endpoint; no biomapper-derived fields on passthrough rows.
- `candidate_limit` semantics unchanged.

### Deferred to Separate Tasks

- ddharmon exposing `kestrel_top_n`: follow-up issue only (V7), not this PR.
- `shared_call` fetch optimization: not implemented; `fetch_strategy` never emits it this release (see Unit 3).
- **Phase 0.4 live prefix-stability experiment: split out of this PR** (Checkpoint 2). It gates nothing shippable (default is `separate_call`). Filed as a separate exploratory task; only 0.1–0.3 (fixtures/schema/category-map, which Units 3–5 need) stay in this PR.

## Context & Research

### Relevant Code and Patterns

- **Mirror for the request option:** `MappingOptions.candidate_limit`
  (`src/biomapper2/api/models/requests.py:45-55`) — same `int | None`, `ge=1, le=100`, description style.
- **Response read sites (3) that must surface `kestrel_results`:**
  - `extract_mapping_result` (`src/biomapper2/api/routes/mapping.py:52-82`) — `/entity` + `/batch`.
  - the manual per-row dict in `map_dataset_stream.generate_ndjson` (`src/biomapper2/api/routes/mapping.py:392-407`).
- **Attach mechanism (verified):** `map_entity_to_kg` operates on a Pydantic `Entity`
  (`ConfigDict(extra="allow")`) and returns `entity.to_series()/to_dict()` (`src/biomapper2/mapper.py:602-604`).
  Values are carried by adding keys to the `pd.Series` passed to the final
  `entity.update_from(...)` (`mapper.py:584-600`), exactly as `resolution_certificate` /
  `lipid_resolution` are. **There is no `mapped_item` dict to assign to.** The mapper attaches a
  private **passthrough plan** (`category`, `prefixes`, recorded endpoints, `search_text`) this way;
  the route then executes the calls and attaches `kestrel_results`.
- **Route-armed shared state (why collection timing matters):** `/batch` arms a **wall-clock RefMet
  per-batch deadline** across the whole per-entity loop (`mapping.py:176-177`, disarm `222-223`);
  `refmet_availability` is embedded in the certificate. `kestrel_request` also mutates **process-global
  request counters** (`_bump`, `src/biomapper2/utils.py:89-121,426-431`, feeding
  `request_counter_snapshot()` used in benchmark manifests) and goes through a **process-global
  `requests_cache` CachedSession** keyed on method+url+json (`utils.py:60-74,425-433`).
- **Endpoint selection (verified caveat):** `AnnotationEngine._select_annotators(category)`
  (`annotation_engine.py:253-267`) takes only `category`, always appends `kestrel-hybrid-search`, and
  is consulted **only when `annotators is None`**. The mode=`none` and mode=`missing`-with-provided-IDs
  **skip** (pipeline makes no Kestrel call) lives in `annotate`/`_annotate_dataframe` gating, **not** in
  `_select_annotators`. Re-deriving endpoints from `_select_annotators` would therefore fire calls the
  baseline skipped → violates R6. Slug→endpoint: hybrid→`hybrid-search`, text→`text-search`, vector→`vector-search`.
- **Raw fetch primitive (verified):** `kestrel_request(...)` **raises** on failure
  (`raise_for_status` re-raises 5xx/transient; `response.json()` raises on malformed body;
  `BisectBudgetExceeded` when bisect is enabled, default off). The passthrough wraps it in try/except.
- **Existing option test to sibling:** `tests/test_candidate_limit_option.py`.

### Key Behavioral Finding (Phase 0.1, verified)

Every route that supports `kestrel_top_n` calls `map_entity_to_kg` **one entity at a time**
(`/batch` and `/dataset/stream` are per-entity/per-row loops; `map_dataset_to_kg` — the only true bulk
path, behind `/map/dataset` — joins DataFrames directly and never calls `map_entity_to_kg`). So the
422 boundary is safe and passthrough is always single-term. **R5 is discharged as a deliberate
trade-off, not "trivially satisfied":** passthrough forgoes bulk batching (it issues N extra
single-term round-trips, one per row × used endpoint) because supported routes are per-entity; this is
the latency cost R9's cap must bound. Recorded in the design note as a deviation.

### Institutional Learnings

- Kestrel public endpoint `https://kestrel.krakenkg.com/api` is the packaged default and **keyless**
  (`config.py:53-54`); the host guard withholds any set key from the public host. Fixtures (0.3),
  the experiment (0.4), and the design note must never commit keys **or** captured request detail
  (host/headers) if ever run against a keyed non-public host — add an explicit redaction check before committing.
- `kestrel_results` rows are **untrusted external data** (not biomapper-attested); document this so any
  renderer (future UI, ddharmon) treats them as unescaped.

## Key Technical Decisions

- **`separate_call` default.** Dedicated `limit=N` call per *used* endpoint; selection calls unchanged.
  `fetch_strategy` always reports `separate_call` (typed as a single-value Literal this release, Unit 3).
- **Selection invariance (R4) is preserved by *placement + recording*, not "by construction".**
  Passthrough shares three pieces of state with selection: the RefMet wall-clock batch deadline, the
  global request counters, and the HTTP cache. Therefore:
  1. **Execute passthrough after the RefMet-armed window closes.** In `/batch`, collect in a second
     pass after the main loop and after `disarm_batch_deadline()` (single `/entity` and `/dataset/stream`
     do not arm the deadline, so per-entity collection is fine there). This prevents passthrough latency
     from tipping late-batch entities past the deadline and flipping their `refmet_availability`/certificate.
  2. **Record, don't re-derive, the used endpoints.** The `annotate` path records the Kestrel endpoints
     it actually invoked per entity (empty when it skipped), attached to the entity as the passthrough
     plan. Passthrough reads that record → R6 guaranteed, no `_select_annotators` drift.
  3. **T6 (mocked) cannot falsify invariance** (zero latency, no contention). Add a **timed live
     invariance test** (extend T15): a multi-entity batch with a realistic armed `BATCH_DEADLINE_S` and
     induced passthrough latency, asserting late-batch `refmet_availability`/certificate are unchanged
     across `kestrel_top_n`.
  4. **Counter provenance:** passthrough calls `_bump` on the global counters. Tag passthrough traffic
     so `request_counter_snapshot()` stays comparable across `kestrel_top_n` (e.g. a `passthrough=True`
     flag or endpoint suffix); do not silently inflate benchmark request counts.
- **Attach via `Entity.update_from`.** The mapper adds the passthrough *plan* to the final
  `entity.update_from(pd.Series({...}))`; the route attaches the executed `kestrel_results`. Never
  enters `AssignedIDsDict`, resolver, or certificate. `Entity` is `extra="allow"`, so the plan survives to `to_series()/to_dict()`.
- **`/map/dataset` → 422.** That route returns a TSV path + stats (`DatasetMappingResponse`); no
  per-entity JSON to carry rows. Reject with 422 pointing to `/map/dataset/stream`.
- **Classified error, not `str(e)`.** R7's `error` field is an enumerated class
  (`"timeout" | "upstream_error" | "malformed_response" | "other"`); the full exception is logged
  server-side. Avoids leaking internal Kestrel URLs/wiring to API clients.

## Open Questions

### Resolved at Checkpoint 2

- **[R9] Hard-enforced batch cap.** Reject with 422/413 when
  `len(entities) × kestrel_top_n × endpoints_used` exceeds a documented threshold (closes the
  resource-exhaustion vector; reverses the spec's "propose, not impose"). Threshold value deferred to implementation.
- **[Phase 0.4] Split out of this PR.** Keep 0.1–0.3 (fixtures/schema/category-map) here; the
  `shared_call` viability experiment is a separate exploratory task.

### Resolved During Planning

- Where does passthrough attach without touching selection? → mapper records a private passthrough plan
  via `Entity.update_from`; route executes + attaches `kestrel_results` after the RefMet window.
- How are used endpoints known? → recorded by `annotate`, not re-derived (guarantees R6).
- `/map/dataset`? → 422.

### Deferred to Implementation

- Exact typed fields on `KestrelRow` — from Phase 0.3 live schema; unknown fields via `extra="allow"`.
- The exact `category`/`prefix` **and the exact selection-call JSON payload shape** per entity type
  (Phase 0.2/0.3) — pin these so passthrough rows equal what selection saw and cache keys line up.
- Precise mechanism for `annotate` to record used endpoints (return value vs. attribute on the entity).
- The concrete cap threshold number (pending the R9 decision above).

## High-Level Technical Design

> *Directional guidance for review, not implementation specification.*

```mermaid
flowchart TD
    R[map_entity / map_batch / dataset_stream  (options.kestrel_top_n)] --> M[Mapper.map_entity_to_kg]
    M --> STD[standardize entity_type -> category; get_standard_prefix -> prefixes]
    STD --> ANN[annotation_engine.annotate  -- UNCHANGED selection calls; RECORDS used kestrel endpoints]
    ANN --> RES[resolver.resolve -> chosen_kg_id, certificate]
    RES --> PLAN[entity.update_from: attach passthrough PLAN category/prefixes/endpoints/search_text]
    PLAN --> RET[return entity.to_series/to_dict]
    RET --> LOOP{route}
    LOOP -->|batch: AFTER loop + disarm RefMet deadline| PT[kestrel_passthrough.collect  separate_call limit=N raw]
    LOOP -->|entity / stream: per item| PT
    PT --> OUT[attach kestrel_results -> extract_mapping_result / ndjson row]
```

The `annotate → resolve` spine is byte-identical to today; passthrough runs off the RefMet-armed
budget, from a recorded plan, and only ever appends `kestrel_results`.

## Implementation Units

- [ ] **Unit 1: Phase 0 verification — data-flow trace, category/prefix + selection-payload map, live fixtures** *(Phase 0.4 experiment split to a separate task)*

**Goal:** Produce the evidence/ fixtures shipping units need, before feature code.

**Requirements:** Supports R2 (row schema), R3, R4 argument, design-note deliverable.

**Dependencies:** None.

**Files:**
- Create: `tests/fixtures/kestrel_{text,vector,hybrid}_search_*.json` (2–3 sanitized responses each, 0.3)
- Create: `docs/plans/2026-09-21-001-feat-kestrel-raw-passthrough-design-note.md` (or PR body) covering 0.1–0.3 (+0.4 if kept)
- Create *(only if Phase 0.4 kept per Checkpoint 2)*: `scripts/kestrel_prefix_stability.py` (reproducible; saves to a timestamped path by default per repo SOP)

**Approach:**
- 0.1 Trace `kestrel_request` → annotators → `annotate`/resolver/certificate → read sites; confirm the side channel touches no `AssignedIDsDict` consumer.
- 0.2 Record exact `category` (from `standardize_entity_type`) + `prefix` (from `get_standard_prefix`) per entity type, **and the exact selection-call JSON payload** each Kestrel annotator sends, so passthrough replicates it byte-for-byte (row parity + cache-key parity).
- 0.3 Capture live per-endpoint row schema (keyless `KESTREL_API_URL`); sanitize (explicit redaction check for host/headers/keys before commit); save fixtures.
- 0.4 *(if kept)* Prefix-stability experiment; summary table in the design note. Decision stays `separate_call` regardless.

**Test scenarios:** Test expectation: none (fixtures/artifact unit). Fixtures consumed by Units 3–5.

**Verification:** Fixtures load; design note has the 0.2 map (incl. selection payload shape) and 0.3 schema. **0.4 table is a soft deliverable and does not block Units 3–5.**

- [ ] **Unit 2: Request option `kestrel_top_n`**

**Goal:** Add the opt-in knob (R1).

**Requirements:** R1. **Dependencies:** None.

**Files:** Modify `src/biomapper2/api/models/requests.py`; Test `tests/test_kestrel_top_n_option.py`.

**Approach:** Add `kestrel_top_n: int | None = Field(default=None, ge=1, le=100, description=...)` to `MappingOptions`, mirroring `candidate_limit`; description states it controls passthrough rows only and cannot change `chosen_kg_id` (R10). Keep `extra="ignore"`.

**Patterns to follow:** `MappingOptions.candidate_limit` (`requests.py:45-55`).

**Test scenarios:**
- Happy path: default `None`; 1/20/100 accepted.
- Edge/Error: 0, 101, non-integer → 422 via TestClient (T1).
- Backward compat: unknown extra option still parses (T13).

**Verification:** OpenAPI exposes `kestrel_top_n` with the bound; out-of-range → 422.

- [ ] **Unit 3: Response models — `KestrelRow`, `KestrelRequestParams`, `KestrelSearchResult`, `kestrel_results` field**

**Goal:** Add the response side channel (R2), raw-preserving.

**Requirements:** R2, R3. **Dependencies:** Unit 1 (row schema).

**Files:** Modify `src/biomapper2/api/models/responses.py`; Test `tests/test_kestrel_passthrough_models.py`.

**Approach:**
- `KestrelRow`: type stable fields from 0.3 (confirm names from fixtures); `model_config = {"extra": "allow"}`; IDs/CURIEs preserved byte-for-byte (str, no coercion).
- `KestrelRequestParams`: `search_text`, `limit`, `category`, `prefix`.
- `KestrelSearchResult`: `endpoint: Literal["text-search","vector-search","hybrid-search"]`, `request: KestrelRequestParams`, `rows: list[KestrelRow]`, **`fetch_strategy: Literal["separate_call"]`** (single value this release — widen only when `shared_call` ships), `error: Literal["timeout","upstream_error","malformed_response","other"] | None = None`.
- Add `kestrel_results: list[KestrelSearchResult] | None = Field(default=None, ...)` to `EntityMappingResult`.

**Patterns to follow:** `LipidResolution` / `ResolutionCertificateModel` nesting in `responses.py`.

**Test scenarios:**
- Happy path: round-trips a fixture row unchanged incl. unknown fields (T3).
- Edge: `kestrel_results=None` serializes with no key or null per R2 (T2).
- Backward compat: pre-change `EntityMappingResult` still parses a new response (T13).

**Verification:** Models validate all Unit 1 fixtures with zero field loss.

- [ ] **Unit 4: Passthrough core module (`kestrel_passthrough.collect`)**

**Goal:** The collector that makes `separate_call` fetches from a **recorded** endpoint plan and builds `KestrelSearchResult`s (R3, R6, R7).

**Requirements:** R3, R5 (single-term), R6, R7. **Dependencies:** Unit 3.

**Files:** Create `src/biomapper2/core/kestrel_passthrough.py`; Test `tests/test_kestrel_passthrough_collect.py`.

**Approach:**
- `collect(search_text, category, prefixes, endpoints, n) -> list[KestrelSearchResult]` where `endpoints`
  is the **recorded** list of endpoints the pipeline actually used for this entity (from the mapper's
  passthrough plan). **No `_select_annotators` re-derivation, no `select_fn` hedge.**
- For each endpoint: call `kestrel_request(method="POST", endpoint=<ep>, batch_field="search_text", batch_items=[search_text], batch_size=KESTREL_BATCH_SIZE_SEARCH, json=<exact 0.2 selection payload with limit=n>)`; take `rows = result.get(search_text, [])[:n]` **raw** — no `>=0.5` filter, no `stable_result_order`, no category guard.
- R6: empty `endpoints` → `[]`.
- R7: wrap each call in try/except; classify the raised exception into the enumerated `error` value, log full detail server-side, set `rows=[]`; never propagate. (Note `kestrel_request` **raises**; tests assert on raised exceptions, not a returned 5xx shape.)
- `fetch_strategy="separate_call"` always.

**Execution note:** Start with a failing test asserting raw rows include a hybrid row with `score < 0.5` (proves R3 divergence from the annotator path).

**Patterns to follow:** `_kestrel_hybrid_search` call shape (`kestrel_hybrid.py:268-284`) minus filtering.

**Test scenarios:**
- Happy path: mock `kestrel_request` returns 100 rows; `n=10` → `len==10`, order preserved, `request.limit==10`, `fetch_strategy=="separate_call"` (T5).
- Raw fidelity: hybrid mock with a `score<0.5` row → present (T4, R3).
- R6: empty `endpoints` → `[]` (T10).
- Error paths: `kestrel_request` **raises** timeout / HTTPError(5xx) / JSON-decode / BisectBudgetExceeded → each yields the right classified `error`, `rows==[]`, no propagation (T11, R7).
- Endpoint fidelity: given recorded `["hybrid-search"]` → one result; recorded `[]` → `[]`; recorded all three → three results.

**Verification:** No path raises; rows byte-identical to the mocked Kestrel slice.

- [ ] **Unit 5: Record used endpoints, execute passthrough off the RefMet window, attach at all read sites; `/dataset` 422**

**Goal:** Thread the option end-to-end without perturbing selection (R4, R5, R6, R8).

**Requirements:** R4, R5, R6, R8. **Dependencies:** Units 2, 3, 4.

**Files:**
- Modify: `src/biomapper2/core/annotation_engine.py` (record the Kestrel endpoints actually invoked per entity; empty when skipped)
- Modify: `src/biomapper2/mapper.py` (`map_entity_to_kg` gains `kestrel_top_n`; attach the passthrough **plan** — `category`, `prefixes`, recorded `endpoints`, `search_text` — into the final `entity.update_from`)
- Modify: `src/biomapper2/api/routes/mapping.py` (`/entity`: collect after mapping; `/batch`: collect in a second pass **after the loop and after `disarm_batch_deadline()`**; `extract_mapping_result` surfaces `kestrel_results`; `map_dataset_stream` adds `kestrel_top_n` query param, collects per row, adds a **JSON-native** `kestrel_results` to the row dict; `map_dataset` rejects the param with 422)
- Test: `tests/test_kestrel_passthrough_routes.py`

**Approach:**
- Engine records used endpoints for the entity (covers `annotators is None` default, explicit `annotators`, and the mode/provided-id skip → `[]`).
- Mapper attaches the plan via `entity.update_from(pd.Series({"_kestrel_passthrough_plan": {...}}))` (private key; `Entity` `extra="allow"`). When `kestrel_top_n is None`, attach nothing.
- Route executes `collect(...)` from the plan and sets `kestrel_results` (list of `model_dump()` dicts — JSON-native, since the NDJSON path `json.dumps` runs outside its try/except at `mapping.py:416`). `/batch` runs this as a post-loop pass so passthrough latency never enters the armed RefMet wall-clock budget.
- `map_dataset_stream`: `kestrel_top_n: int | None = Query(default=None, ge=1, le=100)`; `map_dataset`: same `Query` but raise `HTTPException(422, "...use /map/dataset/stream")` if provided.
- Passthrough `_bump` traffic tagged so `request_counter_snapshot()` stays comparable (Key Decisions §4).

**Patterns to follow:** how `candidate_limit` is threaded (`mapping.py:129,205,310,389`); how certificate/lipid_resolution ride `entity.update_from` (`mapper.py:584-600`).

**Test scenarios:**
- Selection invariance (mocked, primary): parametrize `kestrel_top_n ∈ {None,1,20,100}` × `candidate_limit ∈ {None,1,50}`; assert identical `chosen_kg_id`, `assigned_ids`, `resolution_certificate` (T6). *Note: mocks are zero-latency; T6 cannot prove the deadline case — see the timed test in Unit 6.*
- Separate-call proof, cache-aware: assert selection call args are byte-identical to the no-option run, and the passthrough issues a distinct cache-keyed request per used endpoint **accounting for `from_cache`** (when `n` equals the selection limit the passthrough is a cache hit, not a new HTTP call) (T8).
- Deadline safety: in `/batch`, passthrough collection happens after `disarm_batch_deadline()` (assert ordering / that late-entity `refmet_availability` is independent of `kestrel_top_n`).
- Bulk/single parity: same entities via `/entity` and `/batch`; per-entity isolation incl. duplicate names — A never sees B's rows (T9).
- R6 route cases: `annotation_mode="none"`; `missing` + IDs provided; `annotators=["goslin-lipid"]` → `kestrel_results == []` (T10).
- R7 at route: mock passthrough failure → mapping result unchanged, classified `error` set, HTTP 200 (T11).
- Routes: `/entity`, `/batch`, `/dataset/stream` return rows; `/map/dataset` + `kestrel_top_n` → 422; without → unchanged (T12).

**Verification:** Unit suite green (Kestrel mocked); `chosen_kg_id` identical across the T6 matrix; `/batch` passthrough demonstrably after disarm.

- [ ] **Unit 6: Docs, payload analysis + cap, integration & timed-invariance tests**

**Goal:** README + OpenAPI + worst-case payload + cap; live parity, live + timed invariance (R9, R10, T14, T15).

**Requirements:** R9, R10, T14, T15. **Dependencies:** Units 2–5.

**Files:**
- Modify: `README.md`, field descriptions in `requests.py`/`responses.py` (R10 wording; document rows are untrusted external data)
- Create: `tests/test_kestrel_passthrough_integration.py` (repo integration marker; skipped by `-m "not integration"`)

**Approach:**
- R9: document worst case (1000 × ≤100 × endpoints); implement the **hard-enforced cap** (422/413 when `len(entities) × kestrel_top_n × endpoints_used` exceeds the documented threshold). Add a test asserting an over-threshold request is rejected.
- R10: README + OpenAPI separate `candidate_limit` (moves selection window, can change `chosen_kg_id`) from `kestrel_top_n` (passthrough only, cannot).

**Test scenarios:**
- Integration (marked): 3 names/type, `kestrel_top_n=10` row IDs match a direct Kestrel call, same params (T14).
- Integration (marked): selection invariance vs real Kestrel (T15) **plus** a timed multi-entity `/batch` with a realistic armed `BATCH_DEADLINE_S` and induced passthrough latency, asserting late-batch `refmet_availability`/certificate unchanged across `kestrel_top_n` (the case T6 cannot reach).
- Docs: `Test expectation: none` for prose.

**Verification:** `-m "not integration"` green; integration + timed test green locally; README renders the example; `./scripts/check.sh` clean.

## System-Wide Impact

- **Interaction graph:** additive — a recorded plan on the entity + a route-layer collect + read at 3 sites. No annotator/engine-selection/resolver/certificate *behavior* changes (the engine gains only a passive endpoint recorder).
- **Shared-state interactions (the review's core finding):** RefMet wall-clock batch deadline (mitigated by post-window collection), global request counters (tagged so provenance stays comparable), HTTP cache (T8 asserts on cache keys/`from_cache`). These are why R4 is *engineered*, not free.
- **Error propagation:** contained in Unit 4 (classified `error`); never reaches the mapping result (R7). NDJSON rows are `model_dump()` dicts to stay JSON-serializable outside the stream's try/except.
- **API surface parity:** three read sites must all surface the field or `/dataset/stream` silently omits rows; `/dataset` intentionally 422s.
- **Untrusted data:** `kestrel_results` are verbatim external rows (`extra="allow"`); documented as untrusted for any renderer.
- **Unchanged invariants:** `candidate_limit` semantics, `chosen_kg_id`, `assigned_ids`, `resolution_certificate` for any `kestrel_top_n` (R4) — the release contract, proven by T6 (mocked) **and** the timed test (Unit 6).

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Passthrough latency tips RefMet batch deadline → certificate differs by `kestrel_top_n` (breaks R4) | Collect in `/batch` after the loop + `disarm_batch_deadline()`; timed invariance test (Unit 6). |
| Endpoint re-derivation fires calls the baseline skipped → violates R6 + perturbs state | Record used endpoints in `annotate`; passthrough reads the record (no `_select_annotators` re-derive). |
| Global request counters inflated → benchmark provenance polluted | Tag passthrough `_bump` traffic; keep `request_counter_snapshot()` comparable across `kestrel_top_n`. |
| T8 flaky: `n`==selection limit → cache hit, zero extra HTTP calls | Assert on cache keys / `from_cache`, not raw HTTP call count. |
| Row schema drift / unknown fields dropped (breaks R3) | `KestrelRow` `extra="allow"`; T3 asserts unknown fields survive; fixtures from live capture. |
| Resource exhaustion via large batches (R9) | Enforce a cap (level pending Checkpoint 2); `/dataset` (unbounded artifact) already 422s. |
| `error=str(e)` leaks internal Kestrel URL/wiring | Enumerated `error` class; full exception logged server-side only. |
| Passthrough payload ≠ selection payload → row/cache mismatch | Pin exact selection-call JSON in Phase 0.2/0.3; passthrough replicates it with `limit=n`. |
| Live Kestrel flakiness (public 5xx under load) | Integration tests marked/skipped in unit CI; R7 makes runtime failures non-fatal. |

## Documentation / Operational Notes

- PR description carries the V1–V7 post-deploy checklist; add a V-item confirming `/batch` request-counter
  parity (or documented delta) with vs without `kestrel_top_n`.
- Coverage: report line + branch % for new/modified modules (target 100% per quality gate).
- Design note records every deviation: bulk path per-entity on all supported routes; `/dataset` 422;
  R5 per-entity trade-off; post-window collection; counter tagging; error classification.

## Sources & References

- **Origin document:** `docs/brainstorms/kestrel-passthrough-requirements.md`
- Related code: `src/biomapper2/mapper.py:460,584-604`, `src/biomapper2/api/routes/mapping.py:52-82,176-177,222-223,329-422`,
  `src/biomapper2/core/annotation_engine.py:142-154,253-267`, `src/biomapper2/core/annotators/kestrel_hybrid.py:268-284`,
  `src/biomapper2/api/models/requests.py:45-55`, `src/biomapper2/api/models/responses.py:169-232`,
  `src/biomapper2/utils.py:60-121,425-433`
- PR routing: fork `trentleslie/biomapper2` base `dev` (Greptile first), then Phenome-Health.
