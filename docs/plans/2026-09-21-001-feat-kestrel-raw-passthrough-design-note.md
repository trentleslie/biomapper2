---
title: "Design note: raw Kestrel passthrough (Phase 0.1–0.3)"
type: design-note
status: active
date: 2026-09-21
origin: docs/plans/2026-09-21-001-feat-kestrel-raw-passthrough-plan.md
---

# Design Note — Optional Pass-Through of Raw Kestrel Search Results

Covers the Phase 0 evidence the shipping units depend on (0.1 data-flow trace, 0.2 category/prefix +
selection-payload map, 0.3 row schema/fixtures) and records every deviation from the spec with its
reason. **Phase 0.4 (the live `shared_call` prefix-stability experiment) is split out of this PR** per
Checkpoint 2; it gates nothing shippable (default is `separate_call`).

## Phase 0.1 — Data-flow trace (side channel touches no selection consumer)

The selection spine is, per entity, in `Mapper.map_entity_to_kg`:

```
annotate (assigned_ids, availability, source)  ->  normalize (curies)  ->  link (kg_ids)
  ->  resolve (chosen_kg_id, chosen_kg_id_review)  ->  enrich (kg_equivalent_ids)
  ->  certificate (_certify_and_reresolve)
```

The passthrough is a **side channel that never enters this spine**:

- The mapper RECORDS which Kestrel endpoints annotation actually invoked
  (`annotation_result["kestrel_endpoints_used"]`) and, only when `kestrel_top_n` is set, attaches a
  private plan (`_kestrel_passthrough_plan` = category / prefixes / endpoints / search_text / top_n)
  via `Entity.update_from`. `Entity` is `extra="allow"`, so the plan rides `to_series()/to_dict()`.
- The plan is data only; it never enters `assigned_ids` / `AssignedIDsDict`, the resolver, the
  certificate, or any dataset writer. `extract_mapping_result` reads the same fields it always did;
  `kestrel_results` is attached by the route AFTER `map_entity_to_kg` returns.
- The **route** executes `core.kestrel_passthrough.collect(...)` from the plan and attaches
  `kestrel_results`. On `/map/batch` this runs in a SECOND pass, after the loop and after
  `disarm_batch_deadline()`, so passthrough latency never enters the armed RefMet wall-clock budget
  (see Key Decisions in the plan; this is why R4 is engineered, not free).

Verified: no `AssignedIDsDict` consumer reads `_kestrel_passthrough_plan` or `kestrel_results`.

## Phase 0.2 — category / prefix + exact selection-call payload

Per entity, in `map_entity_to_kg`:

- `category = biolink_client.standardize_entity_type(entity_type)` (e.g. `metabolite` →
  `biolink:SmallMolecule`).
- `prefixes = normalizer.get_standard_prefix(vocab)` (a list; `[]` when `vocab` is None).
- `search_text` = the entity name the annotators searched (`entity.name`, which `Entity.from_input`
  copies from `name_field`).

The three Kestrel search annotators send an **identical payload shape** (see
`kestrel_{text,vector,hybrid}._kestrel_*_search`):

```python
kestrel_request(
    method="POST", endpoint=<endpoint>, batch_field="search_text",
    batch_items=[search_text], batch_size=KESTREL_BATCH_SIZE_SEARCH,
    json={"limit": <limit>, "category": category, **({"prefix": prefixes} if prefixes else {})},
)
```

The passthrough collector (`collect`) replicates this **byte-for-byte with `limit=n`**, so the raw rows
equal what selection saw and the `requests_cache` key lines up (a cache hit when `n` equals the
selection limit; a distinct keyed call otherwise). Slug → endpoint mapping (recorded, not re-derived):
`kestrel-hybrid-search → hybrid-search`, `kestrel-text-search → text-search`,
`kestrel-vector-search → vector-search`. The default small-molecule selection uses only
`hybrid-search`; text/vector are reached only via an explicit `annotators=[...]`.

## Phase 0.3 — per-endpoint row schema + fixtures

Fixtures live in `tests/fixtures/kestrel_{text,vector,hybrid}_search_*.json`. **These are
sanitized/representative** — the schema is derived from the fields the annotators consume plus
representative unknown fields; a live capture against the keyless public Kestrel was intentionally NOT
run in this build (all Kestrel access is mocked here). No host/headers/keys are present in any fixture
(explicit redaction check: the fixtures contain only `endpoint`, `search_text`, a `note`, and a
`response` map of rows).

Typed known fields on `KestrelRow` (all optional; IDs/CURIEs preserved byte-for-byte as `str`):

| field | type | source |
|-------|------|--------|
| `id` | `str` | `chosen["id"]`, `_select_canonical` namespace filter |
| `score` | `float` | `chosen["score"]`, hybrid `>=0.5` filter |
| `name` | `str` | `_symbol_matches`, node name |
| `synonyms` | `list[str]` | `_symbol_matches` |
| `prefixes` | `list[str]` | `_select_result` human-marker filter |
| `categories` | `list[str]` | `is_on_category` guard |

Every other field Kestrel returns is preserved via `model_config = {"extra": "allow"}`; the hybrid
fixture deliberately includes a `score < 0.5` row so the raw-fidelity contract (R3 — passthrough does
NOT apply the selection `>=0.5` filter) is falsifiable in tests.

## Phase 0.4 — split out

The `shared_call` viability experiment (`scripts/kestrel_prefix_stability.py`) is a separate
exploratory task. Shipping does not depend on it: `fetch_strategy` is a single-value Literal
(`separate_call`) this release, widened only when/if `shared_call` ships.

## Deviations from the spec (with reasons)

- **`fetch_strategy` is a single-value Literal (`separate_call`)**, not `Literal["shared_call",
  "separate_call"]` as the origin doc wrote. Reason: only `separate_call` ships this release; a
  two-value Literal would advertise a path that never emits. Widen when `shared_call` lands.
- **`error` is an enumerated class**, not `str | None` as the origin doc wrote
  (`timeout | upstream_error | malformed_response | other`). Reason: `str(exc)` would leak internal
  Kestrel URLs/wiring to API clients; the full exception is logged server-side only.
- **R9 cap uses the worst-case endpoint count (3)** for a pre-flight check on `/map/batch` and
  `/map/dataset/stream`, rather than the exact per-entity `endpoints_used`. Reason: the exact count is
  known only after mapping; a worst-case pre-flight rejects an over-cap request BEFORE any passthrough
  amplification is paid, and is deterministic/testable. Threshold: `KESTREL_PASSTHROUGH_MAX_ROWS =
  100_000` worst-case rows (config, read at request time).
- **Passthrough forgoes bulk batching** (R5): supported routes call `map_entity_to_kg` one entity at a
  time, so passthrough issues N extra single-term round trips (one per row × used endpoint). This is a
  deliberate per-entity trade-off, bounded by the R9 cap.
- **`/map/dataset` (non-streaming) → 422**: it returns a TSV path + stats, with nowhere to carry
  per-entity JSON rows; callers are pointed to `/map/dataset/stream`.
- **Fixtures are representative, not a live capture** (see 0.3): this build does not make live Kestrel
  calls; the live ID-match parity is covered by the (skipped) integration tests T14/T15.
- **Request-counter tagging** (Key Decisions §4): passthrough calls go through the same
  `kestrel_request` and therefore `_bump` the global per-endpoint counters. This build does NOT add a
  `passthrough=True` suffix; the effect is documented here as a known provenance caveat (a run with
  `kestrel_top_n` set will show extra `hybrid-search`/`text-search`/`vector-search` requests in
  `request_counter_snapshot()`). Tagging is a small follow-up if benchmark provenance needs it.

## Test / verification map

- Unit (Kestrel mocked): `test_kestrel_top_n_option.py` (R1/T1/T13), `test_kestrel_passthrough_models.py`
  (R2/R3/T2/T3/T13), `test_kestrel_passthrough_collect.py` (R3/R6/R7/T4/T5/T10/T11),
  `test_kestrel_passthrough_routes.py` (R4/R5/R6/R7/R8/R9 + /batch post-window ordering; T6/T8/T9/T10/T11/T12).
- Integration (marked `integration`, skipped by `-m "not integration"`):
  `test_kestrel_passthrough_integration.py` (T14 real ID match; T15 real invariance + timed
  batch-deadline invariance).
