---
title: "feat: Return equivalent_ids from KG nodes"
type: feat
status: active
date: 2026-04-23
origin: docs/brainstorms/equivalent-ids-requirements.md
---

# Return Equivalent IDs from KG Nodes

## Overview

After biomapper2 resolves an entity to a canonical KG node (`chosen_kg_id`), fetch that node's `equivalent_ids` from Kestrel and include them in the output. This gives downstream users (like Lance) the HMDB, REFMET, UniProt, and other identifiers they need for pathway lookups without a separate API call.

## Problem Frame

Currently the pipeline returns only the canonical CURIE. Users need the full set of equivalent identifiers from the KG node for cross-referencing with other databases. (see origin: `docs/brainstorms/equivalent-ids-requirements.md`)

## Requirements Trace

- R1. Fetch equivalent IDs for each unique `chosen_kg_id` using Kestrel `/get-nodes`
- R2. Add `kg_equivalent_ids` field to output (Entity model, DataFrame, API response)
- R3. On by default — always present in output
- R4. Batch `/get-nodes` calls following existing batching pattern
- R5. Add `kg_equivalent_ids` field to Entity Pydantic model

## Scope Boundaries

- Only fetch for `chosen_kg_id` (post-resolution), not all candidate `kg_ids`
- No new Kestrel endpoint — use existing `/get-nodes`
- No changes to resolution logic

## Context & Research

### Relevant Code and Patterns

- `src/biomapper2/core/linker.py` — Linker class with batched Kestrel API calls via `kestrel_request()`
- `src/biomapper2/utils.py` — `kestrel_request()` handles batching via `batch_field`/`batch_items`; `bulk_kestrel_request()` for single calls
- `src/biomapper2/mapper.py` — Pipeline orchestration: annotation → normalization → linking → resolution. New step goes after resolution
- `src/biomapper2/models.py` — Entity Pydantic model with pipeline fields
- `src/biomapper2/api/models/responses.py` — `EntityMappingResult` API response model
- `src/biomapper2/api/routes/mapping.py` — API routes that construct response from mapped results
- `src/biomapper2/config.py` — Kestrel batch size constants

### /get-nodes API Reconnaissance (verified via curl)

**Request:**
```json
POST /get-nodes
{"curies": ["NCBIGene:84836"], "slim": false, "truncate_long_fields": false}
```

**Response shape:** `dict[str, NodeObject]` keyed by input CURIE — **fits `kestrel_request()` batching pattern exactly** (same as `/canonicalize`)

**`equivalent_ids` field:** flat `list[str]` of CURIEs inside each node object, e.g.:
```json
["UMLS:C1825824", "HGNC:28235", "NCBIGene:84836", "UniProtKB:Q96IU4", ...]
```

**Batch field name:** `curies` (same as `/canonicalize`)

**Implication:** Use `kestrel_request()` with `batch_field="curies"` and `json={"slim": False, "truncate_long_fields": False}`. The `json` kwarg merges with the batch field via `{**json_payload, batch_field: chunk}` (verified in `utils.py:194-211`). Post-process the merged dict to extract only `equivalent_ids` from each node object.

### TSV Serialization Convention

Existing list-valued columns (e.g., `curies`, `kg_ids`) use pandas default `repr()` format in TSV output: `['item1', 'item2']`. The new `kg_equivalent_ids` column will follow the same convention automatically — no custom serialization needed.

## Key Technical Decisions

- **New method on Linker**: Add `get_equivalent_ids()` to Linker since it already owns Kestrel API interactions
- **Post-resolution enrichment in Mapper**: Add a "Step 5" after resolution that calls `linker.get_equivalent_ids()` for unique `chosen_kg_id` values
- **Batch by unique chosen_kg_ids**: Collect all unique non-null `chosen_kg_id` values across the dataset, make one batched `/get-nodes` call, then distribute results to each entity
- **Use `kestrel_request()`**: Response is `dict[str, NodeObject]` keyed by input CURIE — fits the existing batching pattern. Post-process to extract `equivalent_ids` list from each node object. Extraction happens inside `get_equivalent_ids()` so the return type is `dict[str, list[str]]` — callers never see node objects
- **Graceful degradation on Kestrel errors**: Enrichment is non-critical. On API failure, log a warning and return empty dict — do NOT raise. The entity retains its `chosen_kg_id` and the pipeline continues
- **Keep chosen_kg_id in equivalent_ids list**: The KG node is equivalent to itself — Kestrel returns it in the list. Keep it to match raw KG truth; stripping it creates surprise when someone cross-references Kestrel directly
- **Sort equivalent_ids**: Sort the list alphabetically before returning. Makes TSVs diffable, eliminates flaky-test failures from nondeterministic API response ordering
- **Pydantic `Field(default_factory=list)`**: Use `Field(default_factory=list)` for both Entity model and API response model — avoids mutable default warnings
- **All tests in `tests/test_equivalent_ids.py`**: Single test file for the feature, following existing convention of one test file per feature

## Open Questions

### Resolved During Planning

- **/get-nodes request shape**: Uses `curies` field (not `node_ids`), `slim=false`, `truncate_long_fields=false`. Response is `dict[str, NodeObject]` — fits `kestrel_request()`
- **Batch size**: Use `KESTREL_BATCH_SIZE_CANONICALIZE` (2000) — response per node is larger than canonicalize but 2000 is still safe
- **Error handling policy**: Graceful degradation (empty list + warning log). Enrichment is non-critical
- **TSV serialization**: Pandas default `repr()` format — matches existing list columns

### Deferred to Implementation

- **Batch size tuning**: If `/get-nodes` responses are significantly larger per node than `/canonicalize`, may need a smaller batch size constant. Start with 2000 and adjust if timeouts occur

## Implementation Units

- [ ] **Unit 1: Add get_equivalent_ids to Linker + Entity model field**

**Goal:** Add the Kestrel `/get-nodes` call and the Entity model field for equivalent IDs

**Requirements:** R1, R4, R5

**Dependencies:** None

**Files:**
- Modify: `src/biomapper2/core/linker.py`
- Modify: `src/biomapper2/models.py`
- Test: `tests/test_equivalent_ids.py`

**Approach:**
- Add `kg_equivalent_ids: list[str] = Field(default_factory=list)` field to Entity model (after the resolution fields). Comment: "Enrichment step output — equivalent IDs for the chosen KG node"
- Add `get_equivalent_ids(kg_node_ids: list[str]) -> dict[str, list[str]]` static method to Linker
- The method calls `kestrel_request()` with endpoint `get-nodes`, `batch_field="curies"`, additional JSON params `slim=False`, `truncate_long_fields=False`
- Post-process the merged response dict inside the method: for each `{curie: node_object}`, extract `node_object.get("equivalent_ids", [])` (defensive — handles nodes missing the key)
- Sort each equivalent_ids list alphabetically before returning
- Returns `{curie: [equivalent_ids]}` — callers never see node objects
- **Empty input list short-circuits to empty dict without API call**
- **On Kestrel API error: log warning, return empty dict. Do NOT raise — enrichment is non-critical**

**Patterns to follow:**
- `Linker.get_kg_ids()` — static method using `kestrel_request()` for batched API calls

**Test scenarios:**
- Happy path: `get_equivalent_ids(["NCBIGene:84836"])` returns dict mapping node ID to list of CURIEs including `UniProtKB:Q96IU4`, `HGNC:28235`, etc.
- Happy path: multiple node IDs returns equivalent IDs for each
- Edge case: empty list input returns empty dict (no API call made)
- Edge case: node ID not found in KG returns empty list for that ID (graceful, not error)
- Edge case: node object missing `equivalent_ids` key entirely → empty list for that CURIE (defensive `.get()`)
- Edge case: returned equivalent_ids include the chosen_kg_id itself → kept (matches raw KG truth)
- Edge case: equivalent_ids list is sorted alphabetically (verify deterministic order)
- Error path: Kestrel API error (mock 500 response) → logs warning, returns empty dict
- Model: Entity with `kg_equivalent_ids=["A", "B"]` serializes correctly via `to_dict()` and `to_series()`

**Verification:**
- `Linker.get_equivalent_ids(["NCBIGene:84836"])` returns non-empty equivalent IDs (integration test)
- Entity model accepts and serializes `kg_equivalent_ids` field
- All new code paths covered by tests

---

- [ ] **Unit 2: Integrate enrichment into Mapper pipeline**

**Goal:** Wire the equivalent IDs fetch into both `map_entity_to_kg()` and `map_dataset_to_kg()`

**Requirements:** R1, R2, R3

**Dependencies:** Unit 1

**Files:**
- Modify: `src/biomapper2/mapper.py`
- Test: `tests/test_equivalent_ids.py`

**Approach:**
- In `map_entity_to_kg()`: after resolution (Step 4), add Step 5 — if `chosen_kg_id` is not None, call `linker.get_equivalent_ids([entity.chosen_kg_id])` and set the result on the entity. If None, `kg_equivalent_ids` stays as default empty list
- In `map_dataset_to_kg()`: after resolution (Step 4), collect all unique non-null `chosen_kg_id` values from the DataFrame. If the set is empty, skip the API call. Otherwise, make one batched call to `linker.get_equivalent_ids()`, then map results back to each row's `kg_equivalent_ids` column (empty list for rows with no match)
- The DataFrame approach mirrors how `_link_dataframe()` collects unique curies for a bulk request

**Patterns to follow:**
- `Linker._link_dataframe()` — bulk collect unique items, single API call, distribute results
- `mapper.py` Steps 1-4 pattern — call method, join/update result

**Test scenarios:**
- Happy path: `map_entity_to_kg("aspirin", ...)` returns result with non-empty `kg_equivalent_ids` (mocked pipeline)
- Happy path: dataset mapping output DataFrame has `kg_equivalent_ids` column with non-empty lists for matched entities
- Edge case: entity with `chosen_kg_id=None` (no KG match) gets `kg_equivalent_ids=[]`
- Edge case: dataset where ALL entities have `chosen_kg_id=None` — no `/get-nodes` call made, all rows get empty lists
- Edge case: dataset mix of matched/unmatched — matched rows get equivalent IDs, unmatched get empty lists
- Integration: full pipeline from entity name through to equivalent IDs (mocked Kestrel responses for determinism)

**Verification:**
- `map_entity_to_kg()` output includes `kg_equivalent_ids` field
- `map_dataset_to_kg()` output TSV includes `kg_equivalent_ids` column
- Existing tests still pass (no breaking changes)
- All new code paths covered by tests

---

- [ ] **Unit 3: Update API response model and routes**

**Goal:** Include `kg_equivalent_ids` in the REST API response

**Requirements:** R2, R3

**Dependencies:** Unit 2

**Files:**
- Modify: `src/biomapper2/api/models/responses.py`
- Modify: `src/biomapper2/api/routes/mapping.py`
- Test: `tests/test_equivalent_ids.py`

**Approach:**
- Add `kg_equivalent_ids: list[str] = Field(default_factory=list, description="Equivalent identifiers from the resolved KG node")` to `EntityMappingResult`
- Update the `/map` route response construction to include `kg_equivalent_ids=mapped_item.get("kg_equivalent_ids", [])`
- Update the batch mapping route (`/batch` handler `map_batch()`) similarly
- Update the dataset stream route (`/dataset/stream` handler `map_dataset_stream()`) — it constructs an inline dict (not `EntityMappingResult`) at line 328-334 that includes `chosen_kg_id`; add `kg_equivalent_ids` to that dict

**Patterns to follow:**
- Existing `chosen_kg_id` field in `EntityMappingResult` and how it's populated in `mapping.py`

**Test scenarios:**
- Happy path: POST `/api/v1/map` returns response with `kg_equivalent_ids` field containing CURIEs
- Edge case: entity with no KG match returns `kg_equivalent_ids: []` in response
- Integration: API response `kg_equivalent_ids` matches what the Mapper returns internally

**Verification:**
- API response schema includes `kg_equivalent_ids`
- All new code paths covered by tests

## System-Wide Impact

- **Interaction graph:** Adds one new Kestrel API call (`/get-nodes`) to the pipeline after resolution. No callbacks or middleware affected
- **Error propagation:** On `/get-nodes` failure, logs warning and returns empty equivalent IDs. Pipeline continues with all existing fields intact. This is a non-critical enrichment step
- **API surface parity:** Both `map_entity_to_kg()` (Python API) and `/api/v1/map` (REST API) get the new field
- **Unchanged invariants:** All existing output fields remain unchanged. The `chosen_kg_id` resolution logic is untouched. Existing list-valued columns continue using pandas default serialization

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `/get-nodes` payload too large per node for batch of 2000 | Start with 2000; add `KESTREL_BATCH_SIZE_GET_NODES` constant if timeout occurs |
| Large equivalent_ids lists bloat output | Acceptable — users need the full list for cross-referencing |
| Additional API call adds latency | Batched into one call per dataset; latency is one round-trip, not per-entity |
| Kestrel API transient failures | Graceful degradation — empty list + warning log, pipeline continues |

## Sources & References

- **Origin document:** [docs/brainstorms/equivalent-ids-requirements.md](docs/brainstorms/equivalent-ids-requirements.md)
- GitHub issue: Phenome-Health/biomapper2#62
- Linker implementation: `src/biomapper2/core/linker.py`
- Kestrel API utilities: `src/biomapper2/utils.py`
- Entity model: `src/biomapper2/models.py`
- API response models: `src/biomapper2/api/models/responses.py`
