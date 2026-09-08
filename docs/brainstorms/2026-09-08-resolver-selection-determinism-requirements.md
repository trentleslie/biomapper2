# Deterministic node selection in the resolver — Requirements

Created: 2026-09-08
Status: draft (Checkpoint 1)
Scope: PRODUCTION `src/biomapper2/core/resolver.py`. Fork trentleslie/biomapper2 base dev -> Greptile -> then Phenome-Health. NOT studies/.
Depth: Standard (bounded production fix on the selection path + a determinism regression test).

## Problem

BioMapper's node selection for the same query name is **not deterministic** — it depends on
process/batch history. Verified live: `retinol (Vitamin A)` on the same #64-patched instance
(127.0.0.1:8008), same code, resolved to `CHEBI:132246` (wrong) inside the large batch run but returns
`CHEBI:12777` (correct, matches NECS) on a fresh probe (5/5) and a small batch. This is the deferred
"#3" selection-state flip (class of 15999<->64790), distinct from the benchmark cache determinism
(#65) and the #64 hybrid-cache-key.

## Root cause (located in the Phase 1.1 scan; confirm in the Phase 0 spike)

`_choose_best_kg_id` (`src/biomapper2/core/resolver.py:100`) line 130:
`majority = max(kg_ids_dict, key=lambda k: len(kg_ids_dict[k]))`. On a **count tie** between sibling
candidate nodes, `max()` returns the first key in dict-iteration order, with **no deterministic
tie-break**. The code itself documents the hazard for the adjacent RefMet path ("must not ride on dict
insertion order (which follows API response order)") and applies `sorted()` there — but the **default
majority vote was never given the same stable tie-break**. Retinol ties (12777 vs 132246), has no RefMet
vote, so it falls through to the order-dependent `max()`; batch/process history reorders the candidates
and flips the tie.

## Decision (Checkpoint 1)

Give the default majority selection a **deterministic tie-break using BioMapper's existing
category-preferred-prefix / canonical-namespace policy**, with **lexicographic CURIE as the final stable
fallback** (guarantees a total order). The tie-break must fire **only on count ties** — a clear majority
must resolve exactly as today (no broad behavior change).

## Requirements Trace

- R1. Same query name -> same chosen node regardless of process/batch history (determinism).
- R2. On a count tie, prefer the canonical-namespace/preferred-prefix node; lexicographic CURIE as the
  final total-order fallback.
- R3. **No-op when there is a clear majority** — only tie cases change; existing non-tie resolutions are
  byte-identical.
- R4. The RefMet source-weighting / InChIKey-connectivity path is unchanged.
- R5. A determinism regression test (monkeypatched) that FAILS on today's code and passes after the fix.

## Scope Boundaries

- Only the selection tie-break in `_choose_best_kg_id`. No change to annotation, linking, or the
  RefMet/structure weighting path.
- No studies/ change. No new candidate SOURCES. Not a re-scoring of majority logic — only the tie-break.

## Success Criteria

- Determinism regression test: resolve a name in isolation vs after a large simulated batch (monkeypatched
  candidate ordering / API-response order) -> IDENTICAL chosen node. Must fail pre-fix, pass post-fix.
- Retinol-style tie resolves to the canonical node (12777) deterministically.
- Full existing resolver test suite green; a "clear majority unchanged" test proves R3.
- Live supervised confirmation (operator step, not pytest): retinol stable across isolation vs batch on
  8007/8008.

## Open Questions

### Resolved During Planning
- Tie-break rule -> canonical-namespace/prefix preference + lexicographic fallback (Checkpoint 1).

### Deferred to Implementation (Phase 0 spike + plan)
- **Confirm line 130 is THE culprit** (Phase 0 spike): reproduce retinol isolation-vs-batch flip live +
  a minimal monkeypatched unit repro that flips selection purely by candidate ordering. If it cannot be
  reproduced / traced to line 130, STOP (acceptable no-op).
- Does a reusable preferred-prefix function exist (`_category_preferred_prefixes` / the ChEBI-RM canonical
  policy)? Confirm it returns a usable ordering for the tie-break; if not, define the prefix priority.
- Whether any OTHER call site shares the same order-dependent `max()` pattern (audit for the same bug).

## Constraints

uv run; ruff/black 120; pyright gates src+tests; <=8 tests/file; monkeypatch network in tests (never a
live call in pytest; live 8007/8008 reproduction is a supervised operator step); persist any diagnostic
artifact by default; fork-first PR flow.

## Impact note

Fixing this restores run-to-run reproducibility of the benchmark's per-edge-case classifications
(monti_only/biomapper_only/certified/refuted), which are currently not citable at the individual-case
level (aggregate conclusions already hold). It is a correctness+reproducibility fix on the production
selection path — a small diff with a large trust payoff.
