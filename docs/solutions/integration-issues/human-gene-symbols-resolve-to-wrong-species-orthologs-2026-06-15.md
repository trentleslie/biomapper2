---
title: "Human gene/protein symbols resolve to wrong-species orthologs (Kestrel hybrid-search limit=1)"
date: 2026-06-15
last_updated: 2026-06-19
category: integration-issues
module: kestrel_hybrid
problem_type: integration_issue
component: service_object
symptoms:
  - "Human gene symbol resolves to a non-human ortholog NCBIGene ID at confidence_tier=high (TNFRSF1A -> NCBIGene:397020 instead of NCBIGene:7132)"
  - "~42 of 50 human frailty proteins map to wrong-species ortholog nodes with <50 KG edges"
  - "Downstream consumer (kraken) sees a false cold-start: human genes mis-classified as under-characterized"
  - "No error raised -- the wrong node is returned silently with a high score (e.g. 4.876)"
root_cause: wrong_api
resolution_type: code_fix
severity: high
related_components:
  - annotation_engine
  - linker
tags:
  - kestrel
  - hybrid-search
  - ortholog
  - species-disambiguation
  - hgnc
  - gene-mapping
  - prefer-human
---

# Human gene/protein symbols resolve to wrong-species orthologs (Kestrel hybrid-search limit=1)

## Problem

For human gene/protein symbols, biomapper2 resolved a bare symbol to a non-human **ortholog** at
`confidence_tier="high"`, because the underlying Kestrel hybrid-search annotator requested only the
top-1 candidate (`limit=1`) and Kestrel's #1 hit is frequently the wrong-species ortholog. The human
node exists in Kestrel's candidate list (typically rank ~#4) but was discarded before selection.

## Symptoms

- `TNFRSF1A` (`biolink:Gene`) resolved to `NCBIGene:397020` (pig/rat ortholog, score 4.876) instead of
  human `NCBIGene:7132` (3777 edges). `GH1` → bovine ortholog; `LDLR` similarly non-human.
- All mis-resolutions came back at `confidence_tier="high"` — nothing flagged them as suspect.
- Downstream consumer (kraken) saw a "false cold-start": ~42/50 frailty proteins resolved to non-human
  `NCBIGene` orthologs with <50 KG edges and were mis-classified as under-characterized.
- The biomapper2 score was **byte-identical** to Kestrel hybrid-search's own ortholog score —
  confirming biomapper2 *is* Kestrel hybrid-search underneath, with no re-ranking of its own.

## What Didn't Work

- **Kestrel `prefix_filter` / `category_filter` for species** — fails: Kestrel keys *all* gene nodes on
  `NCBIGene` regardless of species (human `NCBIGene:7132` and pig `NCBIGene:397020` share the prefix),
  so a request-side prefix filter cannot separate species. (Kestrel's MCP layer rejects `prefix_filter`
  outright; the REST endpoint accepts it but it still can't filter by species.)
- **`annotation_mode` variations** — `'all'` still returns the ortholog as top-1; `'best'` /
  `'comprehensive'` are invalid and return HTTP 422.
- **A client-side workaround in the downstream consumer (kraken)** — a biomapper pre-resolver + HGNC
  confirmation gate — delivered **zero lift**, because biomapper2 *is* Kestrel underneath. The fix had
  to be at the source (biomapper2) where it benefits every consumer, not bolted onto one consumer.

## Solution

The insight: **HGNC assigns IDs only to human genes** (there is no bovine HGNC id), and the Kestrel
hybrid-search response rows **already carry a `prefixes` list** — the human `NCBIGene:7132` row's
prefixes include `"HGNC"`; ortholog rows (`["NCBIGene","RGD","UniProtKB","ENSEMBL"]`) do not. So the
human candidate is identifiable from the response alone — no extra Kestrel call.

**1. Raise the candidate window, gated to where it applies** (`src/biomapper2/config.py`):

```python
HYBRID_SEARCH_LIMIT = 20            # human node found at rank ~#4 live; 20 gives margin
HUMAN_MARKER_PREFIXES = {"HGNC"}    # human-exclusive marker
```

The raised limit is applied **only for gene/protein** so metabolite/other bulk payloads aren't inflated
~20× (`src/biomapper2/core/annotators/kestrel_hybrid.py`):

```python
limit = HYBRID_SEARCH_LIMIT if prefer_human else 1
```

**2. Two-tier candidate selection** (`_select_result` in `kestrel_hybrid.py`). It returns
`(chosen_row, matched)` — `matched` is True **only** for an HGNC-bearing row that exact-symbol-matches the
query; it is False for the legacy top-1, the ortholog fallback, and the paralog (HGNC-but-no-symbol-match)
case. That `matched` flag is what gates the drug-conflated symbol-fallback bridge downstream (the bridge
fires on `prefer_human and GENE_SYMBOL_FALLBACK_ENABLED and not matched`):

```python
@staticmethod
def _select_result(term_results, search_term, prefer_human) -> tuple[dict | None, bool]:
    if not term_results:
        return None, False
    if not prefer_human:
        return term_results[0], False                                # legacy top-1 (a miss)

    human = [r for r in term_results if HUMAN_MARKER_PREFIXES & set(r.get("prefixes") or [])]
    if not human:
        return term_results[0], False                                # honest fallback -- never fabricate

    exact = [r for r in human if KestrelHybridSearchAnnotator._symbol_matches(r, search_term)]
    if exact:
        return max(exact, key=lambda r: r.get("score", 0)), True     # the only genuine match
    return max(human, key=lambda r: r.get("score", 0)), False        # paralog -- HGNC but no symbol match
```

The HGNC filter must come **before** the symbol match: orthologs share the human row's `name` (same
symbol, different species), so HGNC separates species first, then the symbol match (`_symbol_matches`:
case-insensitive equality on `name`, or membership in `synonyms`) picks the right gene. The symbol-match
step is critical because a human **paralog** (e.g. `TNFRSF1B` → `NCBIGene:7133`) *also* carries HGNC —
matching the queried symbol avoids trading a wrong-species bug for a wrong-gene bug, and a paralog hit is
reported as `matched=False` so it does not suppress the fallback. Defensive reads
(`r.get("prefixes") or []`, `r.get("score", 0)`) tolerate malformed/null rows.

**3. Gate behind a default-on `prefer_human` option**, threaded `MappingOptions` → routes → `Mapper` →
`AnnotationEngine` → annotator. The engine resolves applicability and passes an already-gated effective
flag (`src/biomapper2/core/annotation_engine.py`):

```python
effective_prefer_human = prefer_human and self._is_human_applicable_category(category)

@cached_property
def _human_applicable_categories(self) -> set[str]:
    return self.biolink_client.get_descendants("biolink:Gene") | \
           self.biolink_client.get_descendants("biolink:Protein")
```

`prefer_human=False` restores legacy top-1; metabolites are unchanged. `MappingOptions` uses Pydantic v2
`extra="ignore"` so an older server doesn't 422 on the new field (backward-compat).

## Why This Works

The root cause was twofold: `limit=1` discarded the human candidate before any selection could happen,
and species discrimination was attempted on the **request** side, where it is impossible (Kestrel keys
every species on `NCBIGene`). The fix moves discrimination to the **response** side, where the human
node is unambiguously marked by an `HGNC` prefix — a human-only identifier already present in the rows
Kestrel returns. Raising the limit ensures the human node is actually in hand; the post-filter then
separates species where `prefix_filter` structurally cannot. No additional API call is needed.

## Prevention

- **Symbol-match within the HGNC pool** to avoid trading wrong-species for wrong-paralog (paralogs also
  carry HGNC).
- **Honest fallback**: when no HGNC row exists, return the top candidate rather than fabricating a human
  match — a graceful, observable miss.
- **Make the fallback fraction observable** (reported in the gold-set validation run) so consumers can
  detect recall gaps instead of silently trusting `confidence_tier="high"`.
- **Drug-conflated genes need a non-search bridge, not an xfail** *(updated 2026-06-18 — supersedes the
  earlier xfail guidance)*: `GH1` cannot be resolved by any *re-rank*, but it is **not** unfixable.
  `NCBIGene:2688` *exists* in Kestrel as an **entity-conflation node**: its `name` is `"SOMATROPIN"` (the
  recombinant growth-hormone *drug*), its `synonyms` are pharmaceutical product names (`Norditropin`,
  `Genotropin`, `Saizen`, …), and its categories span `[ChemicalEntity, SmallMolecule, Gene, Protein,
  Drug]`. So `"GH1"` cannot retrieve it in *any* search mode — the gene identity was absorbed into the drug
  node. **Resolution (PR #71): a curated, non-search gene-symbol fallback bridge** assigns the NCBIGene
  deterministically for the 6 known drug-conflations (GH1/CALCA/POMC/CRH/CTLA4/GBA1). The original
  `pytest.mark.xfail(strict=False)` + graceful-fallback gold-set stance is **superseded**: because the
  KG's `/canonicalize` collapses the assigned NCBIGene back into the drug clique (GH1 → `UNII:NQX9KB6PCL`),
  `chosen_kg_id == NCBIGene:X` is unsatisfiable, so the gold set now asserts **clique membership**
  (the chosen node's `equivalent_ids` contain the expected NCBIGene + HGNC) and verifies the bridge
  mechanism offline. See
  [`test-failures/live-gold-set-asserted-live-variable-outcomes-2026-06-18.md`](../test-failures/live-gold-set-asserted-live-variable-outcomes-2026-06-18.md).
- **Test with mocked hybrid rows that include `prefixes`** (and `name`/`synonyms`) so `_select_result` /
  `_symbol_matches` are exercised offline. The live integration/gold-set test cannot run in a sandbox
  because building `Mapper()`/`BiolinkClient` hangs on bmt (Biolink Model Toolkit) init, which is
  network-blocked there — so the fix was verified live against the deployed dev API instead. *(auto
  memory [claude])*
- **Fix at the source, not the consumer**: when a downstream workaround delivers zero lift, suspect the
  downstream service *is* the thing it's trying to correct; fixing it once at the source benefits every
  consumer.

## Verification

Live against the deployed dev API (`dev-biomapper.expertintheloop.io`). The re-ranking is gated to
`biolink:Gene`/`biolink:Protein` (and descendants) — **both verified**; metabolites are excluded by design.

**Gene category:**

| Query | `prefer_human` | Resolved → | HGNC |
|-------|----------------|-----------|------|
| `TNFRSF1A` | `true` (default) | `NCBIGene:7132` (human) | ✓ |
| `TNFRSF1A` | `false` | `NCBIGene:397020` (legacy ortholog) | ✗ |
| `TNFRSF1B` | `true` | `NCBIGene:7133` (correct paralog) | ✓ |
| `LDLR` | `true` | `NCBIGene:3949` | ✓ |
| `glucose` (metabolite) | `true` | `CHEBI:4167` (unchanged) | ✗ |

**Protein category** (verified 2026-06-16 — note Kestrel returns `NCBIGene` gene nodes for these protein
queries, and the HGNC re-ranking engages identically; `false` yields a different non-human node):

| Query (`entity_type=protein`) | `prefer_human=true` | `prefer_human=false` |
|---|---|---|
| `TNFRSF1A` | `NCBIGene:7132` ✓ HGNC | `NCBIGene:397020` |
| `LDLR` | `NCBIGene:3949` ✓ HGNC | `NCBIGene:281276` |
| `TP53` | `NCBIGene:7157` ✓ HGNC | `NCBIGene:403869` |
| `INS` | `NCBIGene:3630` ✓ HGNC | `NCBIGene:397415` |

The mechanism is **HGNC-specific, not gene-specific**: it corrects any human gene/protein query whose
human candidate carries the `HGNC` marker. (`TP53` carries HGNC here — a useful counter-point to the
cautionary `/get-nodes` sample noted in the related `equivalent-ids` doc.)

## Related Issues

- [`canonical-namespace-preference-2026-06-18.md`](./canonical-namespace-preference-2026-06-18.md) — the
  metabolite/disease sibling that **generalizes** this mechanism: the same Kestrel ranking property, but
  the discriminator is a per-category canonical-namespace set (`prefer_canonical`) rather than the HGNC
  human marker. Both are default-on, mutually exclusive at the engine.
- `docs/solutions/build-errors/equivalent-ids-prefix-mismatch-and-ci-type-error-2026-04-29.md` — same
  Kestrel `prefixes` subsystem (LM/RM prefix-string mismatch + CI pyright). **Caveat:** its assumption
  that "prefix filtering cleanly separates vocabularies per entity type" does **not** extend to species
  — Kestrel keys all species on `NCBIGene`, which is exactly what this bug exploits via the HGNC marker.
- `docs/solutions/best-practices/cross-repo-dynamic-api-integration-2026-05-27.md` — see-also for the
  `api/models/requests.py` request-contract surface (where the `prefer_human` option was added) and the
  Kestrel HTTP cache-invalidation gotcha.
- Shipped via PRs: `trentleslie/biomapper2#5` (fork, Greptile) → `Phenome-Health/biomapper2#69` (dev) →
  `#70` (dev → main). Cross-repo follow-up: expose the per-request `prefer_human` opt-out in the
  `biomapper` Python client.
