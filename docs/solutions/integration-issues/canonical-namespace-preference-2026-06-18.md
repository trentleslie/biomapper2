---
title: "Metabolite/disease symbols resolve to cross-reference vocabularies instead of the canonical namespace node (prefer_canonical)"
date: 2026-06-18
category: integration-issues
module: kestrel_hybrid
problem_type: integration_issue
component: service_object
symptoms:
  - "Metabolite name resolves to a cross-reference vocabulary node at confidence_tier=high (kynurenine -> UMLS:C0022818 instead of the edge-rich CHEBI:28683)"
  - "Disease name resolves to an ICD/UMLS/KEGG/PANTHER node rather than the canonical MONDO node"
  - "The mis-resolved node carries few or no KG edges and reads downstream as a false cold-start entity"
  - "No error raised -- the non-canonical node is returned silently with a high hybrid-search score"
  - "The canonical node IS present in the candidate list but scores ~2x below the non-canonical top hit, so limit=1 discards it"
root_cause: scope_issue
resolution_type: code_fix
severity: high
related_components:
  - annotation_engine
  - linker
tags:
  - kestrel
  - hybrid-search
  - canonical-namespace
  - prefer-canonical
  - entity-conflation
  - chebi
  - mondo
  - metabolite-mapping
---

# Metabolite/disease symbols resolve to cross-reference vocabularies instead of the canonical namespace node (prefer_canonical)

## Problem

Within a single Biolink category, Kestrel `hybrid-search` ranks candidates by combined text/vector
similarity across **all namespaces at once**, and the non-canonical entry routinely outranks the
canonical one lexically. With `limit=1`, biomapper2 silently returned the wrong-namespace node at
`confidence_tier="high"` — a metabolite resolved to a UMLS/cross-reference node instead of the edge-rich
`CHEBI` node, and a disease resolved to an ICD/UMLS/KEGG/PANTHER node instead of the canonical `MONDO`
node. The canonical node was already in the candidate set; it was discarded before selection because it
scores below the conflated top hit.

This is the metabolite/disease sibling of the gene wrong-species-ortholog bug — same Kestrel ranking
property, same response-side re-rank shape, different discriminator (a per-category canonical-namespace
set instead of the HGNC human marker). See
[`human-gene-symbols-resolve-to-wrong-species-orthologs-2026-06-15.md`](./human-gene-symbols-resolve-to-wrong-species-orthologs-2026-06-15.md).

## Symptoms

- `kynurenine` (`biolink:SmallMolecule`) resolved to `UMLS:C0022818` instead of `CHEBI:28683`
  ("kynurenine"). `Parkinson disease` resolved to a KEGG/PANTHER pathway node instead of
  `MONDO:0005180`.
- All mis-resolutions came back at `confidence_tier="high"` — nothing flagged them as suspect.
- The mis-resolved node acquires few or no KG edges, so a downstream consumer reads it as a false
  "cold-start" entity.
- Live probes (2026-06-18) showed the canonical node legitimately sits ~2× **below** the conflated
  non-canonical top hit: `kynurenine` → UMLS 4.89 vs CHEBI:28683 2.50; `Parkinson disease` →
  KEGG/PANTHER 4.86 vs MONDO 2.49.

## What Didn't Work

- **A score-margin guard** (accept a canonical candidate only if it scores within a margin of the top
  hit). Three rounds of document review added this guard to avoid force-selecting a weak fuzzy match.
  Direct live probes overturned it: the canonical node is *always* ~2× below the conflated top hit in
  the observed cases, so the guard would have **defeated the feature**. Removed — there is deliberately
  no score-margin guard. *(session history — the guard survived three review passes and was killed only
  by live data; see the companion best-practice doc.)*
- **Filtering on the candidate's broader `prefixes` xref list** (as the gene `_select_result` does).
  That admits a row merely cross-referenced to CHEBI/MONDO, not one whose *assigned* id is canonical.
  The fix filters on the candidate's own `id` namespace instead, guaranteeing the assigned CURIE is
  canonical.
- **A request-side `prefix_filter` for the canonical namespace.** It cannot express "prefer canonical
  but fall back honestly" — a hard filter returns nothing when no canonical candidate exists, turning a
  graceful miss into an empty result.

## Solution

A per-category canonical-namespace preference (`prefer_canonical`, default-on), generalizing the
`prefer_human` mechanism. A config map binds each Biolink category to its canonical prefixes; the engine
expands it across descendants and gates it; the annotator's `_select_canonical` re-ranks the existing
candidate window.

**1. Config map of canonical prefixes** (`src/biomapper2/config.py`) — note the prefixes are the *actual*
Kestrel KG strings, verified live (RefMet is `RM`, not `REFMET`; a wrong string is a silent no-op):

```python
CATEGORY_PREFERRED_NAMESPACES: dict[str, set[str]] = {
    "biolink:SmallMolecule": {"CHEBI", "HMDB", "RM"},
    "biolink:Disease": {"MONDO"},
}
```

**2. Canonical candidate selection** (`_select_canonical` in `kestrel_hybrid.py`) — filter on the
candidate's own `id` namespace (case-insensitive), prefer the identity match, fall back honestly to the
top row, and tag provenance via the returned `is_canonical`:

```python
@staticmethod
def _select_canonical(term_results, preferred_prefixes, search_term) -> tuple[dict | None, bool]:
    if not term_results:
        return None, False
    preferred_cf = {p.casefold() for p in preferred_prefixes}
    pool = [r for r in term_results if str(r.get("id", "")).split(":", 1)[0].casefold() in preferred_cf]
    if not pool:
        return term_results[0], False               # honest fallback -- never fabricate a canonical CURIE
    exact = [r for r in pool if KestrelHybridSearchAnnotator._symbol_matches(r, search_term)]
    candidates = exact if exact else pool
    return max(candidates, key=lambda r: r.get("score", 0)), True
```

The caller raises the candidate window and tags provenance only when the choice was actually canonical
(`src/biomapper2/core/annotators/kestrel_hybrid.py`):

```python
limit = HYBRID_SEARCH_LIMIT if (prefer_human or preferred_prefixes) else 1
...
elif preferred_prefixes:
    chosen, is_canonical = self._select_canonical(term_results, preferred_prefixes, search_term)
    if is_canonical:
        chosen = {**chosen, "resolved_via": "canonical_preference"}
```

**3. Engine gate, mutually exclusive with `prefer_human`** (`annotation_engine.py`). The engine resolves
the applicable prefix set across Biolink descendants and only sets it when human-preference is off for the
category, so gene/protein resolution is untouched:

```python
effective_prefer_human = prefer_human and self._is_human_applicable_category(category)
effective_preferred_prefixes = (
    self._category_preferred_prefixes.get(category)
    if prefer_canonical and not effective_prefer_human else None
)

@cached_property
def _category_preferred_prefixes(self) -> dict[str, set[str]]:
    resolved: dict[str, set[str]] = {}
    for category, prefixes in CATEGORY_PREFERRED_NAMESPACES.items():
        for descendant in self.biolink_client.get_descendants(category):
            resolved.setdefault(descendant, set()).update(prefixes)   # union on overlap, never drop
    return resolved
```

`prefer_canonical` is threaded `MappingOptions` → routes → `Mapper` → `AnnotationEngine` → annotator,
default-on, with the parity annotators accepting-and-ignoring `preferred_prefixes`. The bulk path forwards
`preferred_prefixes` so dataset jobs re-rank identically.

## Why This Works

The root cause is the same scope error as the gene bug: discrimination was attempted on the **request**
side (one top hit, or a hard prefix filter) where the canonical node is either discarded or made
unreachable. The fix moves it to the **response** side, where the canonical node is unambiguously marked
by its own `id` namespace — already present in the rows Kestrel returns. Raising the limit ensures the
canonical node is in hand; the namespace filter plus identity match selects it without any score gate,
because score is not a reliable signal here (the canonical node legitimately scores below the conflated
top hit). Filtering on `id` rather than the `prefixes` xref list guarantees the *assigned* result is
canonical, not merely cross-referenced.

## Prevention

- **Filter on the assigned `id` namespace, not the xref `prefixes` list**, when the goal is that the
  *chosen* id be canonical. The broader list admits cross-referenced-but-non-canonical rows.
- **No score-margin guard for namespace preference.** Within a category the canonical node routinely
  scores ~2× below a conflated non-canonical node; a score gate defeats the feature. The namespace filter
  plus an identity match is the discriminator. Probe live scores before adding any score-based gate — see
  [`../best-practices/validate-assumptions-against-live-data-2026-06-18.md`](../best-practices/validate-assumptions-against-live-data-2026-06-18.md).
- **Honest fallback**: when no canonical candidate exists, return the top row with `is_canonical=False`
  rather than fabricating a canonical CURIE — a graceful, observable miss.
- **Keep the two policies mutually exclusive at the engine.** Setting `preferred_prefixes` only when
  `prefer_human` is off for the category avoids a caller passing both and double-re-ranking a gene query.
- **Use the real Kestrel prefix strings** (`RM`, not `REFMET`) — a wrong string is a silent no-op that
  matches nothing. The same `RM`-not-`REFMET` gotcha is documented in
  [`../build-errors/equivalent-ids-prefix-mismatch-and-ci-type-error-2026-04-29.md`](../build-errors/equivalent-ids-prefix-mismatch-and-ci-type-error-2026-04-29.md).
- **Test with mocked hybrid rows carrying `id`/`name`/`synonyms`** so `_select_canonical` is exercised
  offline (`tests/test_kestrel_hybrid_canonical.py`, `tests/test_annotation_engine_canonical.py`). The
  live gold set (`tests/test_canonical_namespace_gold_set.py`) cannot run in the sandbox because building
  `Mapper()` hangs on bmt init — verify live against the deployed dev API. *(auto memory [claude]:
  `project_biomapper2_test_env_quirks`)*

## Verification

Live against the deployed dev API. The re-rank is gated to metabolite/disease categories; gene/protein
resolution is unaffected (mutually exclusive with `prefer_human`).

| Query (category) | `prefer_canonical` | Resolved → |
|---|---|---|
| `kynurenine` (metabolite) | `true` (default) | `CHEBI:28683` (canonical) |
| `serotonin` (metabolite) | `true` | `CHEBI:28790` |
| `Parkinson disease` (disease) | `true` | `MONDO:0005180` |
| `TNFRSF1A` (gene) | `true` | `NCBIGene:7132` (unchanged — gene path) |

The live gold set confirmed `kynurenine`/`serotonin` resolve to their canonical CHEBI nodes and that gene
resolution is unaffected.

## Related Issues

- [`integration-issues/human-gene-symbols-resolve-to-wrong-species-orthologs-2026-06-15.md`](./human-gene-symbols-resolve-to-wrong-species-orthologs-2026-06-15.md)
  — the `prefer_human` parent this feature generalizes (same Kestrel ranking property, HGNC marker
  instead of a canonical-namespace set).
- [`build-errors/equivalent-ids-prefix-mismatch-and-ci-type-error-2026-04-29.md`](../build-errors/equivalent-ids-prefix-mismatch-and-ci-type-error-2026-04-29.md)
  — the `RM`-not-`REFMET` Kestrel prefix-string gotcha the config map depends on.
- [`test-failures/live-gold-set-asserted-live-variable-outcomes-2026-06-18.md`](../test-failures/live-gold-set-asserted-live-variable-outcomes-2026-06-18.md)
  — the gold-set assertion strategy fixed alongside this feature (PR #72).
- [`best-practices/validate-assumptions-against-live-data-2026-06-18.md`](../best-practices/validate-assumptions-against-live-data-2026-06-18.md)
  — the procedural lesson from the score-margin reversal.
- Shipped via PRs: `trentleslie/biomapper2#8` (fork, Greptile) → `Phenome-Health/biomapper2#72` (dev).
