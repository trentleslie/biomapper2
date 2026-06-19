---
title: "Validate design assumptions against live data before encoding them"
date: 2026-06-18
category: best-practices
module: kestrel_hybrid
problem_type: best_practice
component: development_workflow
applies_when:
  - "A design decision or test assertion encodes an assumption about an external service's behavior (scores, rankings, id shapes, canonicalization)"
  - "Document/plan review reasoning is about to add a guard, threshold, or margin without measuring the real distribution it guards against"
  - "A correctness gate asserts an exact live value that the upstream system may transform (conflation, canonicalization, normalization)"
  - "The full local pipeline can't run in the sandbox, tempting a 'reason it out' shortcut instead of a direct probe"
severity: medium
related_components:
  - annotation_engine
  - testing_framework
tags:
  - live-data-validation
  - design-review
  - kestrel
  - assumptions
  - score-margin
  - probe-first
  - integration-test
---

# Validate design assumptions against live data before encoding them

## Context

Across the `prefer_human` / `prefer_canonical` resolution work, two separate, well-reasoned decisions were
reached by review *reasoning alone* and both turned out to be wrong against the live Kestrel knowledge
graph. Review and planning passes are good at surfacing plausible failure modes, but they cannot observe
the real distribution of an external service's scores, rankings, or id transformations. When the
assumption is cheap to measure, measuring it beats reasoning about it — and the cost of *not* measuring
is a guard that defeats the feature, or a release-blocking assertion that is structurally unsatisfiable.

A reinforcing trap: the full biomapper2 `Mapper` cannot run in the development sandbox (bmt init is
network-blocked, so it hangs). That made "reason it out" feel like the only option. It isn't — the raw
Kestrel `/hybrid-search`, `/canonicalize`, and `/get-nodes` endpoints are directly reachable from the
sandbox and are sufficient to calibrate any assumption about Kestrel's behavior.

## Guidance

Before encoding an assumption about an external system's behavior into a guard, threshold, or exact-value
assertion, **probe the live system and measure the actual distribution.** Reserve review/planning
reasoning for *which* behaviors to probe — not for *predicting their values*.

A minimal probe needs no pipeline, only the raw endpoint:

```python
import os, requests

resp = requests.post(
    f"{KESTREL_API_URL}/hybrid-search",
    headers={"X-API-Key": os.environ["KESTREL_API_KEY"]},
    json={"limit": 20, "category_filter": "biolink:SmallMolecule", "search_text": ["kynurenine"]},
)
for row in resp.json()["kynurenine"]:
    print(row["id"], round(row["score"], 2), row["name"])
# -> UMLS:C0022818 4.89 ... / CHEBI:28683 2.50 kynurenine   <- canonical is ~2x BELOW the top hit
```

Specifically:

- **Measure before you gate.** If you are about to add a score margin, a confidence threshold, or a
  ranking assumption, first print the real scores for representative inputs. Only add the gate if the data
  supports it.
- **Probe the real outcome before asserting an exact value.** If a correctness gate will assert an exact
  live id, first fetch what the upstream system actually returns for that input — it may transform it
  (conflation, canonicalization).
- **Use the reachable sub-endpoints when the full pipeline can't run.** A sandbox block on the full
  pipeline is not a block on validation; the underlying service endpoints are usually still reachable.

## Why This Matters

Reasoning-only decisions that look obviously safe can be exactly backwards against live data, and the
failure is silent until production or CI:

- A score-margin guard "to avoid force-selecting a weak fuzzy match" reads as prudent, but only live
  scores reveal that the canonical node legitimately sits ~2× below the conflated top hit — so the guard
  would have silently defeated the feature for every metabolite and disease.
- An exact-CURIE correctness assertion reads as the strongest possible gate, but only a live
  `/canonicalize` probe reveals that the assigned id collapses into a drug/chemical clique node — making
  the assertion structurally unsatisfiable and blocking a release.

In both cases the cost of the missing probe was high (a defeated feature; a blocked `dev → main` release
that merged red undetected because the integration test can't run locally), and the cost of the probe was
a few seconds against a reachable endpoint.

## When to Apply

- A design or review pass is about to add a guard, margin, threshold, or ranking assumption that depends
  on an external service's score/ranking behavior.
- A test or correctness gate will assert an exact live value that an upstream system might transform.
- The full local pipeline can't run in the sandbox and you're tempted to substitute reasoning for
  measurement — check whether the underlying endpoints are individually reachable first.

## Examples

**Example 1 — the score-margin guard (design decision reversed).** Three rounds of document review added a
score-margin guard to the canonical-namespace selector, on the reasoning that a canonical candidate far
below the top hit was probably a weak fuzzy match not worth force-selecting. A direct `/hybrid-search`
probe showed the opposite — the canonical node is *always* ~2× below the conflated top hit:

| Query | Non-canonical top hit | Canonical node | Ratio |
|---|---|---|---|
| kynurenine | UMLS 4.89 | CHEBI:28683 2.50 | ~51% |
| Parkinson disease | KEGG/PANTHER 4.86 | MONDO:0005180 2.49 | ~51% |

The guard was removed; the shipped selector has **no score-margin guard**, only the namespace filter plus
an identity match. *(session history: the guard survived three review passes and was overturned only by
live probes.)* See
[`../integration-issues/canonical-namespace-preference-2026-06-18.md`](../integration-issues/canonical-namespace-preference-2026-06-18.md).

**Example 2 — the exact-CURIE gold-set assertion (correctness gate reversed).** A live gold set asserted
`chosen_kg_id == "NCBIGene:X"` for six drug-conflated genes. A `/canonicalize` probe showed each assigned
NCBIGene collapses into its drug clique representative (GH1 → `UNII:NQX9KB6PCL`, CALCA → `CHEBI:3306`),
making the assertion unsatisfiable; it merged red and blocked the release. The originating incident and the
clique-membership fix are documented separately — this best practice is the *procedural* generalization of
its "probe the real live outcome before asserting an exact value" lesson:
[`../test-failures/live-gold-set-asserted-live-variable-outcomes-2026-06-18.md`](../test-failures/live-gold-set-asserted-live-variable-outcomes-2026-06-18.md).

## Related Issues

- [`integration-issues/canonical-namespace-preference-2026-06-18.md`](../integration-issues/canonical-namespace-preference-2026-06-18.md)
  — the feature whose score-margin guard the live probes overturned (Example 1).
- [`test-failures/live-gold-set-asserted-live-variable-outcomes-2026-06-18.md`](../test-failures/live-gold-set-asserted-live-variable-outcomes-2026-06-18.md)
  — the originating incident for Example 2; covers the gold-set assertion strategy in depth (this doc does
  not duplicate its Prevention prose).
- Auto memory: `project_biomapper2_test_env_quirks` (the bmt sandbox block + reachable raw endpoints),
  `project_kestrel_drug_conflated_gene_canonicalize`.
