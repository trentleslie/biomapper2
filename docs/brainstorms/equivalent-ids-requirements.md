---
date: 2026-04-23
topic: equivalent-ids
---

# Return Equivalent IDs from KG Nodes

## Problem Frame

When biomapper2 maps an entity to a KG node, it returns only the canonical CURIE (`chosen_kg_id`). Users like Lance need the node's other known identifiers (HMDB, REFMET, UniProt aliases, etc.) for downstream tasks like pathway lookups. Currently they'd have to make a separate Kestrel API call to get these.

GitHub issue: Phenome-Health/biomapper2#62

## Requirements

- R1. After resolution, fetch equivalent IDs for each unique `chosen_kg_id` using Kestrel's `/get-nodes` endpoint (with `slim=False`, `truncate_long_fields=False`)
- R2. Add a new `kg_equivalent_ids` field/column to the output containing the equivalent IDs for the resolved KG node
- R3. Equivalent IDs fetched by default (no opt-in flag needed). The column is always present in the output
- R4. Batch the `/get-nodes` calls to avoid timeouts on large datasets (follow existing batching pattern in the Linker)
- R5. Add `kg_equivalent_ids` field to the Entity Pydantic model

## Success Criteria

- `map_entity_to_kg("aspirin")` returns a result containing `kg_equivalent_ids` with a list of CURIEs from the KG node
- `map_dataset_to_kg()` output TSV includes a `kg_equivalent_ids` column
- REST API `/map` endpoint response includes `kg_equivalent_ids`
- Existing tests continue to pass; no breaking changes to existing output fields

## Scope Boundaries

- Only fetch equivalent IDs for `chosen_kg_id` (post-resolution), not for all candidate `kg_ids`
- No new Kestrel endpoint — use existing `/get-nodes`
- No changes to the resolution logic itself
- Design should be expandable: adding pre-resolution equivalent IDs later should not require breaking changes (the `kg_equivalent_ids` name is scoped to the chosen node; a future `kg_ids_equivalent_ids` could cover candidates)

## Key Decisions

- **Column name**: `kg_equivalent_ids` — short, indicates KG origin, leaves room for `kg_ids_equivalent_ids` later
- **On by default**: Low cost (one batched API call for unique chosen_kg_ids), high value. Users who don't need it can ignore the column
- **Post-resolution only**: Lance's use case is pathway lookups for the mapped entity, not debugging candidate nodes

## Dependencies / Assumptions

- Kestrel `/get-nodes` endpoint returns `equivalent_ids` in its response when `slim=False`
- The endpoint accepts batched node ID requests

## Next Steps

-> `/ce:plan` for implementation planning, then execute as part of the `feat/dev-api-infrastructure` branch alongside repo cleanup changes
