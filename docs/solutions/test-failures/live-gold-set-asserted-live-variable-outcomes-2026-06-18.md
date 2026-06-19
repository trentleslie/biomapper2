---
title: Live integration gold set asserted live-variable KG outcomes, blocking the release
date: 2026-06-18
category: docs/solutions/test-failures/
module: tests/test_human_gene_gold_set.py
problem_type: test_failure
component: testing_framework
related_components:
  - development_workflow
symptoms:
  - "Live integration gold set tests/test_human_gene_gold_set.py merged red and blocked the dev->main release CI (PR #70)"
  - "assert chosen_kg_id == NCBIGene:X failed for 6 drug-conflated genes (GH1/CALCA/POMC/CRH/CTLA4/GBA1) because /canonicalize collapses them into a non-gene clique node (GH1->UNII:NQX9KB6PCL, CALCA->CHEBI:3306, CRH->CHEBI:65307)"
  - "After relaxing to clique-membership, assert resolved_via == 'symbol_fallback' still failed on CRH: assert None == 'symbol_fallback' (CRH's conflated node surfaced in search and was selected directly, matched=True, no bridge)"
  - "Undetectable pre-merge: the integration test can't run locally because bmt init is network-blocked (the full Mapper hangs); CI runs pytest -m 'not external', which includes integration"
root_cause: logic_error
resolution_type: test_fix
severity: high
tags:
  - integration-test
  - gold-set
  - kestrel
  - canonicalize
  - drug-conflation
  - flaky-test
  - merge-gate
  - bmt
---

# Live integration gold set asserted live-variable KG outcomes, blocking the release

## Problem

A live integration gold set (`tests/test_human_gene_gold_set.py`, marked `@pytest.mark.integration`,
hits the live Kestrel knowledge-graph API) blocked the biomapper2 `dev → main` release CI (PR #70). It
asserted live KG outcomes that the upstream drug-conflation makes **unsatisfiable** — and, once relaxed,
asserted a resolution **mechanism** that drifts run-to-run with live Kestrel recall.

## Symptoms

The gold set gates resolution of human genes whose protein product is a marketed therapeutic
(GH1, CALCA, POMC, CRH, CTLA4, GBA1). The upstream Translator/Babel layer conflates each human gene node
into a single node named for the drug, so the gene is unreachable by Kestrel search and is recovered only
by a curated symbol-fallback bridge (`src/biomapper2/core/gene_symbol_resolver.py`).

- **v1 — exact CURIE.** `assert chosen_kg_id == "NCBIGene:796"` (and the other 5) fails. The fallback
  assigns the correct NCBIGene, but Kestrel `/canonicalize` collapses it into the gene's over-merged drug
  clique, so the chosen node surfaces as the drug/chemical representative:
  - GH1 `NCBIGene:2688` → `UNII:NQX9KB6PCL` ("SOMATROPIN")
  - CALCA `NCBIGene:796` → `CHEBI:3306` ("calcitonin")
  - CRH `NCBIGene:1392` → `CHEBI:65307`

  The clique node still carries the NCBIGene **and** an HGNC id in its `equivalent_ids`, so the exact-CURIE
  assertion is structurally unsatisfiable.
- **v2 — mechanism.** After relaxing to clique membership but still asserting the bridge per gene, CI fails
  only on **CRH**: `assert None == 'symbol_fallback'`. CRH's conflated node `CHEBI:65307` carries an HGNC
  equivalent AND "CRH" as a synonym and ranks within the gene-search window, so `_select_result` selects
  it directly with `matched=True` (a correct outcome), no bridge fires, and `resolved_via` is `None`.
- **Merged red undetected:** the integration test can't run locally — bmt (Biolink Model Toolkit) init is
  network-blocked in the sandbox, so the full `Mapper` hangs — and CI runs `pytest -m "not external"`,
  which **includes** `integration` tests against live Kestrel. So both bad assertions passed local
  collection and only failed in CI, twice.

## What Didn't Work

1. **Asserting the exact live CURIE** (`chosen_kg_id == "NCBIGene:X"`). Unsatisfiable — it ignores that
   `/canonicalize` collapses the assigned NCBIGene into a drug-named clique representative (CHEBI/UNII), so
   the chosen id is never the bare NCBIGene for conflated genes.
2. **Relaxing to clique membership but keeping the per-gene mechanism assertion**
   (`assert row["resolved_via"] == "symbol_fallback"`, plus `assert n_resolved_via_bridge == 6`). Still
   flaky: CRH's conflated node itself surfaced in search and was selected directly (`resolved_via=None`),
   tripping the equality even though the end state was correct. Pinning `== 6` also fails the moment Kestrel
   recall improves or upstream de-conflates a gene (the *desired* fix would read as a regression).

## Solution

Two stages (PRs #72 then #73): assert clique membership instead of an exact CURIE, then drop the per-gene
mechanism assertion and report mechanism usage as a bounded count.

**Stage 1 — clique membership, not exact CURIE.** Helper in `tests/test_human_gene_gold_set.py`
(`kg_equivalent_ids` is `{prefix: [local_id, ...]}` for the chosen node):

```python
def _clique_contains(result: dict, expected_curie: str) -> bool:
    prefix, local_id = expected_curie.split(":", 1)
    return local_id in (result.get("kg_equivalent_ids", {}).get(prefix, []) or [])

# per-row in the gold_set_run fixture:
"resolved_to_clique": (chosen == expected) or _clique_contains(result, expected),
```

**Stage 2 — drop the per-gene mechanism assertion; report mechanism as bounded observability.**

```python
# BEFORE (flaky / fragile):
for name in ("GH1", "CALCA", "POMC", "CRH", "CTLA4", "GBA1"):
    assert row["resolved_to_clique"]
    assert row["has_hgnc"]
    assert row["resolved_via"] == "symbol_fallback"   # FLAKY: live-variable mechanism
assert n_resolved_via_bridge == 6                     # FRAGILE: hard-pins live state

# AFTER (end-state only):
for name in ("GH1", "CALCA", "POMC", "CRH", "CTLA4", "GBA1"):
    assert row["resolved_to_clique"], f"{name} -> {row['chosen_kg_id']} clique lacks {POSITIVE_GOLD[name]}"
    assert row["has_hgnc"], f"{name} resolved node lacks an HGNC marker"
    # NO per-gene resolved_via assertion — mechanism is hard-verified offline in
    # test_kestrel_hybrid_fallback.py and test_gene_symbol_resolver.py
assert gold_set_run["n_resolved_to_clique"] == gold_set_run["n_positive"]  # hard end-state gate
assert 0 <= gold_set_run["n_resolved_via_bridge"] <= 6                     # bounded observability
```

The `resolved_via` marker is still *recorded* per row and rolled into `n_resolved_via_bridge` /
`fallback_fraction` for the timestamped report — observed, just no longer asserted as a hard equality. The
mechanism itself is enforced deterministically by **offline mocked unit tests**
(`tests/test_kestrel_hybrid_fallback.py`, `tests/test_gene_symbol_resolver.py`), which exercise the
`kestrel_hybrid.py` `_select_result` `(chosen, matched)` return and the bridge branch
(`prefer_human and GENE_SYMBOL_FALLBACK_ENABLED and not matched`).

## Why This Works

End-state correctness — the resolution landed in the biologically-correct clique that carries both the
expected NCBIGene and an HGNC marker — is **stable regardless of which annotator path produced it**, which
is exactly what a release gate should protect. The *mechanism* (curated bridge vs. the conflated node
happening to surface in search vs. canonicalize-collapse) is a function of live Kestrel recall that drifts;
hard-asserting any single mechanism is inherently flaky. Reporting `n_resolved_via_bridge` as `0 ≤ x ≤ 6`
keeps the signal observable while tolerating upstream de-conflation (fewer bridge fires is success, not a
regression).

The conflation is a documented, *predictable* mechanism, not a random Kestrel bug: NodeNormalization builds
identifier cliques and applies GeneProtein + DrugChemical conflation; a genome-wide sweep of all ~19,295
HGNC protein-coding genes confirmed exactly these 6 genuine drug-conflations (peptide-hormone / biologic
targets) — which is what justifies the curated 6-entry in-code bridge. *(session history)*

## Prevention

- **Live integration gold sets assert only stable end-state correctness.** Verify the *mechanism* in
  offline, mocked unit tests. Report mechanism counts as **bounded** observability (`0..N`), never as a
  hard equality (`== N`) — improving upstream behavior should not break the gate.
- **Probe the real live outcome before asserting an exact value.** Direct Kestrel `/canonicalize` +
  `/get-nodes` calls work locally even though the bmt-dependent `Mapper` does not. Use them to learn that
  conflated genes canonicalize to a drug/chemical representative *before* asserting a bare `NCBIGene:X`.
- **Know what your CI marker actually runs.** CI runs `pytest -m "not external"`, which **includes**
  `integration`. A live gold set that cannot run locally (bmt network block) can still merge red and block
  a downstream release — validate live behavior firsthand before merging assertions about it.
- **Separate the failure classes in the gold set.** Search-recoverable genes (TNFRSF1A/TNFRSF1B/LDLR)
  yield the exact NCBIGene; drug-conflated genes only yield clique membership. A single uniform `== exact`
  assertion conflates the two classes and is unsatisfiable for the conflated one.

## Related Issues

- [`integration-issues/human-gene-symbols-resolve-to-wrong-species-orthologs-2026-06-15.md`](../integration-issues/human-gene-symbols-resolve-to-wrong-species-orthologs-2026-06-15.md)
  — direct predecessor (same Kestrel conflation root cause, same files, the `prefer_human` lineage). It
  documents GH1→SOMATROPIN as a one-off `xfail`; **this doc supersedes that "assert exact CURIE / xfail"
  stance** with clique-membership + offline mechanism verification.
- [`build-errors/equivalent-ids-prefix-mismatch-and-ci-type-error-2026-04-29.md`](../build-errors/equivalent-ids-prefix-mismatch-and-ci-type-error-2026-04-29.md)
  — the real Kestrel prefix-string gotcha (`RM` not `REFMET`) that the sibling canonical-namespace work relies on.
- PRs: **#72** (clique-membership fix + canonical-namespace feature, merged), **#73** (drop the
  live-variable bridge assertion, merged), **#71** (gene-symbol fallback bridge), **#70** (the `dev → main`
  release this unblocked). Auto-memory: `project_kestrel_drug_conflated_gene_canonicalize`,
  `project_biomapper2_test_env_quirks`.
