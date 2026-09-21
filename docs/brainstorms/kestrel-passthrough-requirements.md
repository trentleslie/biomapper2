---
date: 2026-09-21
topic: kestrel-raw-passthrough
---

# Optional Pass-Through of Raw Kestrel Search Results

## Problem Frame

biomapper2 maps entity names to KRAKEN nodes: three Kestrel annotators
(`kestrel_text`, `kestrel_vector`, `kestrel_hybrid`) each POST a search and receive
a ranked list of rows, but the pipeline commits **at most one** row per search term
and discards everything else Kestrel returned (hybrid additionally drops rows with
`score < 0.5` before selection). Downstream consumers — ddharmon, benchmarking, manual
adjudication, error analysis — cannot see the candidate rows that were considered but
not chosen, so they cannot audit *why* a given `chosen_kg_id` won or inspect near-misses
without re-querying Kestrel out-of-band and hoping the parameters match.

This adds an **opt-in side channel**: callers may request the top N raw rows Kestrel
returned per endpoint, passed through untouched, without altering selection in any way.

## Requirements

Requirement IDs are preserved verbatim from the source spec (R1–R10) so planning,
implementation, and review can refer to them unambiguously. Test IDs (T1–T15) and
post-deploy checks (V1–V7) are carried in dedicated sections below.

**Request / Response contract**
- R1. Add `MappingOptions.kestrel_top_n: int | None = None`, bounded 1..100 (out-of-range → 422).
  `None` disables the feature. Do not change `candidate_limit` semantics. Keep
  `model_config = {"extra": "ignore"}`.
- R2. Add `kestrel_results: list[KestrelSearchResult] | None = None` to `EntityMappingResult`,
  omitted/None when `kestrel_top_n` is None so existing responses are byte-unchanged. Each
  `KestrelSearchResult` is a Pydantic model with: `endpoint`
  (`Literal["text-search","vector-search","hybrid-search"]`); `request` (the params actually
  sent for the passthrough rows: `search_text`, `limit`, `category`, `prefix`); `rows` (rows
  exactly as Kestrel returned them, Kestrel's order, truncated to N, known fields typed from
  Phase 0.3, unknown fields carried through via `model_config = {"extra": "allow"}`, IDs/CURIEs
  byte-for-byte); `fetch_strategy` (`Literal["shared_call","separate_call"]`); and `error`
  (`str | None`, per R7).

**Raw fidelity**
- R3. Raw means raw: rows are captured **before** any biomapper processing — before the hybrid
  `score >= 0.5` filter, before `stable_result_order`, category guards, and re-ranking.

**Selection invariance (primary acceptance criterion)**
- R4. For any request, `chosen_kg_id`, `assigned_ids`, the resolver vote, and
  `resolution_certificate` MUST be identical for `kestrel_top_n` in {None, 1, 20, 100}.

**Coverage of both paths and no-call cases**
- R5. Single-entity and bulk paths must both populate `kestrel_results`. In bulk, each entity
  receives only its own search term's rows; passthrough batching must respect
  `KESTREL_BATCH_SIZE_SEARCH`.
- R6. Entities with no Kestrel call (annotation_mode `none`; `missing` with IDs provided;
  only non-Kestrel annotators selected) get `kestrel_results: []` when the option is set.

**Failure isolation**
- R7. If a passthrough call fails (timeout, 5xx, malformed body), the mapping result is
  unaffected; record the failure in that `KestrelSearchResult.error` and return empty `rows`.
  A passthrough failure MUST never turn a successful mapping into an error.

**Routes**
- R8. Support `/map/entity` and `/map/batch` (body option) and `/map/dataset/stream`
  (query param, rows per NDJSON line). **`/map/dataset` (non-streaming) rejects `kestrel_top_n`
  with a clear 422** pointing callers to `/map/dataset/stream` (see Key Decisions).

**Payload and docs**
- R9. Document the worst case (1000 batch entities × up to 100 rows × endpoints called) in the
  field description. Propose (do not impose) a batch cap when `kestrel_top_n` is set.
- R10. Update `README.md` (usage + example) and OpenAPI descriptions, stating that
  `candidate_limit` controls the selection window and can change `chosen_kg_id`, while
  `kestrel_top_n` only controls passthrough rows and cannot.

## Success Criteria

- R4 holds under test: parametrizing `kestrel_top_n` ∈ {None,1,20,100} × `candidate_limit`
  ∈ {None,1,50} yields identical `chosen_kg_id`, `assigned_ids`, and certificate (T6).
- A caller setting `kestrel_top_n=10` gets ≤10 raw rows per called endpoint whose IDs match a
  direct Kestrel call with the same parameters (T14), including hybrid rows with `score < 0.5` (T4).
- Existing clients are unaffected: responses without the option have no `kestrel_results` key
  (or null, per R2), and a pre-change `EntityMappingResult` still parses new responses (T13).
- `./scripts/check.sh` passes; `uv run pytest -m "not integration"` green; new/modified modules
  at 100% line + branch coverage; ddharmon still parses responses (V7).

## Scope Boundaries

- No change to annotator selection, re-ranking, resolver voting, or the certificate.
- No merging of rows across endpoints (text/vector/hybrid scores are on different scales).
- No new top-level endpoint.
- No biomapper-derived fields on passthrough rows.
- `candidate_limit` semantics unchanged.
- ddharmon is not modified in this PR; if it should expose the option, that is a follow-up issue (V7).

## Key Decisions

- **Fetch strategy default = `separate_call`.** Always make a dedicated `limit=N` passthrough
  call per endpoint, leaving the selection call byte-for-byte identical to today. This makes R4
  true by construction and requires no live Kestrel experiment to ship. Cost: one extra Kestrel
  call per called endpoint per entity, only when `kestrel_top_n` is set. The Phase 0.4
  prefix-stability experiment script is still delivered and run behind its own gate to document
  whether `shared_call` is a safe future optimization per endpoint — but shipping does not depend
  on it. `fetch_strategy` is surfaced on every `KestrelSearchResult` so consumers/tests can see
  which path produced the rows.
- **`/map/dataset` rejects `kestrel_top_n` with 422.** The non-streaming dataset route
  materializes the whole result set; per-row raw rows (≤100 × 3 endpoints × N entities) would
  bloat the artifact unboundedly. `/map/dataset/stream` already covers the passthrough use case
  line-by-line, so the 422 points callers there.
- **IDs preserved from the source spec.** R#/T#/V# IDs are not renumbered, to keep traceability
  between this doc, the plan, the implementation, and the PR checklist.

## Dependencies / Assumptions

- Verified present in `/home/trentleslie/projects/biomapper2` (origin = fork
  `trentleslie/biomapper2`): `src/biomapper2/config.py`,
  `src/biomapper2/core/annotators/kestrel_{text,vector,hybrid}.py`,
  `src/biomapper2/core/annotation_engine.py`, `src/biomapper2/api/models/{requests,responses}.py`,
  `src/biomapper2/api/routes/mapping.py`, `tests/test_candidate_limit_option.py`,
  `scripts/check.sh`, `README.md`, `docs/CONTRIBUTING.md`.
- PR routing: branch off `origin/dev`, open PR against fork `trentleslie/biomapper2` base `dev`
  for Greptile first, then Phenome-Health (per project convention).
- Kestrel's public Kestrel/Kestrel endpoint is keyless; live integration tests (T14/T15) and the
  Phase 0.4 experiment must never commit API keys, and fixtures (Phase 0.3) must be sanitized.

## Deferred to Planning

These are inherently technical / require reading current code and are correctly answered during
`/ce:plan` and implementation, not in this brainstorm:

- [Affects R1/R2/R5][Technical] The exact side-channel mechanism to carry raw rows from
  `kestrel_request`/annotators up to `extract_mapping_result` without touching `AssignedIDsDict`
  or any of its consumers (resolver, certificate, dataset writers) — Phase 0.1 data-flow trace.
- [Affects R2][Technical] The precise `category`/`prefix` values the pipeline sends per entity
  type from GET `/api/v1/entity-types` — read from code, do not guess (Phase 0.2).
- [Affects R2/R3][Needs research] Kestrel's actual per-endpoint row schema captured from live
  responses → typed known fields + `extra="allow"`; save 2–3 sanitized fixtures per endpoint
  under `tests/fixtures/` (Phase 0.3).
- [Affects Key Decision][Needs research] Phase 0.4 prefix-stability experiment (script under
  `scripts/`, results table in the design note) — informs only whether `shared_call` is a future
  optimization; default remains `separate_call` regardless of outcome.
- [Affects R9][Technical] The concrete proposed (not imposed) batch cap value and where it is
  documented.

## Test & Verification Obligations (carried from spec)

- Unit (mock all Kestrel, use Phase 0.3 fixtures): T1 bounds/422; T2 None → no key; T3 rows
  exact incl. unknown fields; T4 hybrid `<0.5` present; T5 `len(rows) ≤ N` + `request.limit`
  reflects strategy; T6 selection invariance matrix; T7 shared-call slice; T8 separate-call
  byte-identical selection + one extra `limit=N` call; T9 bulk/single parity + per-term isolation
  incl. duplicate names; T10 R6 cases → `[]`; T11 timeout/5xx/malformed each leave result
  unchanged + set `error`; T12 route coverage incl. the 422; T13 backward compatibility.
- Integration (repo integration marker, skipped by unit CI): T14 real-Kestrel ID match;
  T15 real-Kestrel selection invariance.
- Post-deploy checklist in PR description: V1 health; V2 OpenAPI exposes option; V3 unchanged
  default (`has("kestrel_results")` per R2, `chosen_kg_id` == pre-deploy); V4 with option ≤N rows
  + unchanged `chosen_kg_id`; V5 repeat V3/V4 for protein/lipid/disease; V6 batch-100 latency +
  size with/without option; V7 ddharmon still parses + follow-up issue if it should expose the option.

## Deliverables

1. PR-ready change implementing R1–R10 with tests T1–T15.
2. `scripts/` Phase 0.4 prefix-stability experiment + its results table.
3. Design note (PR description or `docs/`) covering: Phase 0.1 data-flow trace + side-channel
   choice, Phase 0.2 category/prefix per entity type, Phase 0.3 row schema, Phase 0.4 fetch
   strategy with evidence, the `/map/dataset` 422 decision, payload-size analysis + proposed cap,
   coverage numbers, and every deviation from the spec with its reason.

## Next Steps

-> /ce:plan for structured implementation planning
