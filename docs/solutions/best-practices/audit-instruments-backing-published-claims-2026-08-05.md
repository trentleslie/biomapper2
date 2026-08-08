---
title: "Measurement code that backs a published claim is production code: test it, give it a positive control, and never restate its numbers in prose"
date: 2026-08-05
category: best-practices
module: biomapper2
problem_type: best_practice
component: testing_framework
severity: high
related_components:
  - tooling
  - service_object
  - documentation
applies_when:
  - "a code comment, PR body, or preprint quotes a measured count, rate, or percentage"
  - "writing an audit/analysis script whose output justifies a design decision"
  - "a guard is justified by 'it costs nothing' and you need to prove the cost measurement could have come back nonzero"
  - "an analysis script queries the same API as production but constructs the request itself"
  - "a cross-dataset rate is aggregated over files rather than over logical datasets"
tags:
  - audit-provenance
  - measured-figures
  - positive-control
  - self-confirming-instrument
  - mutation-testing
  - pinned-artifact
  - analysis-coverage
---

# Measurement code that backs a published claim is production code

## Context

PR [#47](https://github.com/trentleslie/biomapper2/pull/47) (`fix/resolver-category-acceptance`) added a Biolink **category** validator at the commit point of all three Kestrel annotators, after discovering that 1,138 of 12,605 metabolite-arm commits (9.03%) landed on nodes carrying no chemical category at all — mostly `biolink:PhenotypicFeature` EFO "...measurement" nodes. Two resolver defects were fixed alongside it (`connectivity_match` comparing `keys[0]` to `keys[0]` across multi-valued INCHIKEY lists; `refmet_nodes[0]` riding on dict insertion order).

The guard itself was the small half of the change. The larger half — and every lesson worth keeping — came from the fact that **the original numbers existed only in a source comment**: no script, no pinned input, no artifact. Rebuilding them as a runnable audit (`studies/analysis/off_category_audit.py` against pinned suite `suite_20260805T033340Z`, kraken 2.0.1 / biolink 4.2.5 / `git_sha d059564`) changed several of them, and review found that the audit itself was structurally incapable of reporting the one failure it existed to detect.

These numbers reach a preprint. This document is what that cost taught.

## Guidance

### 1. Prose names the artifact field. It never restates the value.

Rounds 1–3 of review each found the same defect in a different file, because each round wrote fresh narrative justification containing fresh live measurements that immediately went stale. Fixing the cited instance did nothing; the next round's prose introduced new numbers.

The fix is structural, not editorial: a comment says *where* the number lives, not *what* it is.

```python
# Wrong — the value is now in two places and only one of them regenerates
# A namespace whitelist would refuse 294 legitimate non-canonical chemical commits.

# Right — one source of truth, and it is executable
# Size and per-namespace breakdown, at one stated scope: artifact field
# ``namespace_whitelist_cost``.
```

Enforce it mechanically. `tests/test_no_measured_figures_in_prose.py` tokenizes each guarded file, scans **only** COMMENT and docstring tokens, strips identifiers that merely contain digits (CURIEs, InChIKeys, semver, SHAs, ISO dates, file:line refs), and flags what remains — 3+ digits, a thousands-separated number, or any percentage. Small integers ("two shapes") are structural facts asserted elsewhere in code and are allowed.

It ships with **both controls**: a positive control asserting the scanner can fail, and a negative control asserting it does not flag identifiers. A guard that cannot fail is worse than no guard.

What it caught was not merely unbacked but **false**: `kestrel_text.py` asserted that `/text-search` returns `UMLS:C0022818` typed Protein as the top hit for "kynurenine". That was copy-pasted from the vector path without re-measuring; the text endpoint ranks `CHEBI:28683` first.

### 2. Re-derive rather than restate — it finds errors, not just missing citations

Every figure regenerated from the pinned artifact moved:

| Claim in the original comment | After re-derivation |
|---|---|
| namespace-whitelist cost: 294 | **577** (the 294 mixed two scopes and reconciled against nothing) |
| "362 Protein/Gene" | **369** (362 was Protein-only; the adjudicated population is 369) |
| failure-open candidates: prose estimate | deterministic scan, artifact field `failure_open_candidate_scan` |
| "18/45 pool-filter simulation" | **deleted** — unauditable, and deleting beat keeping |

### 3. The instrument must be able to report the failure it exists to detect

This is the most dangerous class of bug in this document, because it produces a confident number rather than an error.

```python
adjudicable = verdicts["CORRECT_BUT_REFUSED"] + verdicts["WRONG_AND_REFUSED"]

# Wrong — absorbs the one verdict that is never costless into the safety figure,
# making the claim self-confirming
provably_costless = adjudicable + unresolvable_reason["node_carries_no_chemical_identifier"]

# Right
provably_costless = (
    verdicts["WRONG_AND_REFUSED"]
    + unresolvable_reason["node_carries_no_chemical_identifier"]
)
```

`CORRECT_BUT_REFUSED` — a right compound refused for wearing a wrong Biolink type — is precisely the outcome the audit exists to find. Counting it as costless meant the instrument could not report its own failure mode.

It was **masked on both refusal populations only because `CORRECT_BUT_REFUSED` is zero there**, so 369/369 and 1,133/1,138 were right by coincidence. On a population where the verdict is nonzero, 8,675 (75.65%) collapses to 3,913 (34.12%). Pinned by a test verified red-green against the old formula.

### 4. A zero is only meaningful if the instrument can return nonzero — run a positive control

The headline safety claim was "of the 1,138 refusals, **0** were the right compound under a wrong Biolink type." A zero from an unexercised adjudicator is indistinguishable from a broken adjudicator (see #3, which was exactly that).

So the same `adjudicate` function runs over the **ON-category** commits and the result is recorded in the artifact as `adjudicator_positive_control`, where `CORRECT_BUT_REFUSED` comes back 4,762 — proof the instrument discriminates. The control carries a `verdict_label_note` explaining that those rows were not refused, so the verdict name reads as "gold agrees with the committed node" in that population.

### 5. Query with production's parameters, or the instrument measures a different system

The audit fetched Kestrel `/get-nodes` with `truncate_long_fields=True` while the production `Linker` sends `False`. That caps `equivalent_ids` at 50 and biases refusal-cost verdicts toward "provably costless" — a truncated node looks like it carries fewer identifiers, so it looks less likely to have been the right compound.

Three changes, in order of durability:

1. Send `truncate_long_fields=False` to match production.
2. **Rename the cache file** so a stale truncated cache cannot be silently reused.
3. Assert the run **fails** if any adjudicated node comes back truncated.

Headline numbers were unchanged under untruncated data, so the bias was immaterial here — but it is now *enforced* rather than *asserted*.

### 6. Disclose weighting in the data, not in the prose

`metabolite_total` is **file-weighted**. metlinkr ships five replica target-vocab files, so it enters the cross-dataset rate five times and contributes 94% of the off-category rows. That was disclosed only in surrounding prose — which does not travel with the number into a slide or a preprint.

The fix puts the caveat in the artifact:

```json
"metabolite_total_deduplicated": { ... },
"weighting_warning": "file-weighted: a dataset shipping N target-vocab files with identical resolutions enters this total N times. See metabolite_total_deduplicated before quoting a cross-dataset rate."
```

Per-dataset coverage decisions are computed within a dataset and are unaffected — say so explicitly, so the warning does not get over-applied.

### 7. Analysis code that produces published numbers needs the same coverage as `src/`

`studies/analysis/off_category_audit.py` had **zero** test coverage. That is how the `refusal_provably_costless` bug shipped. It now covers `adjudicate` (all three verdicts, all three UNRESOLVABLE reasons), the costless arithmetic, both `equivalent_ids` response shapes, gold-CURIE extraction, `namespace_composition`, and an assertion that the audit's `is_off_category` / `is_failure_open` are the exact **complement** of the shipped `base.is_on_category` — so the instrument and the guard cannot drift apart.

### 8. Prove coverage by mutation, not by counting tests

A reviewer demonstrated that nothing covered the bulk-forwarding paths: **deleting the `accepted_categories` kwarg from both bulk methods left the test suite byte-identical.** The bulk path is every benchmark run and every dataset API request. New parametrized tests fail under that mutation and pass on revert.

If you cannot name the mutation your test kills, you have not shown the path is covered.

### 9. Un-ignore committed artifacts explicitly

A blanket `*.json` ignore is exactly how a cited number ends up with no artifact behind it. Both the JSON and markdown audit outputs are committed with explicit negations in `.gitignore`. This is a direct recurrence of the pattern in [gitignore-globs-exclude-pinned-benchmark-data](../runtime-errors/gitignore-globs-exclude-pinned-benchmark-data-2026-08-04.md) — a `git add <dir>` that silently skips the file the claim depends on.

## Why This Matters

An unbacked number and a wrong number look identical in a diff. Both read as authoritative; neither has an error mode that surfaces during review. The `refusal_provably_costless` defect is the sharpest case: it produced a plausible 75.65% that no test could contradict, because the formula defined the failure out of existence. It survived three review rounds on the guard code precisely because attention was on the guard, not on the thing measuring the guard.

The compounding cost is that these figures leave the repo. Once "9.03%" or "0 correct-but-refused" is in a slide, a preprint, or a PR body, it circulates with no pointer back to the run that produced it. Making every number regenerate from a pinned artifact means a stale figure can be stale in exactly one place, and that place is executable.

## When to Apply

- Any script under `studies/` whose output justifies a design decision or reaches a slide, PR body, or manuscript.
- Any "this guard costs nothing" claim — build the positive control before trusting the zero.
- Any analysis that calls the same service as production but builds its own request payload.
- Any aggregate rate computed over files, rows, or runs rather than over the logical unit a reader will assume.
- Before writing a measured figure into a comment or docstring. Name the artifact field instead.

## Examples

**The design calls the audit was built to defend.** Each is a case where the cheap-looking alternative is worse and only measurement shows it:

- **Validator, not a pool filter.** Filtering the candidate pool promotes the runner-up into the vacancy, substituting a *different* still-wrong node. `_select_canonical` already prefers CHEBI/HMDB/RM, so promotion can only fire when no canonical node was in the pool. Refusing can only turn wrong→refuse, never wrong→right — and a wrong chemical is far harder to audit than a node that announces itself as not-a-molecule.
- **Category, never namespace.** The two checks look nearly identical in a diff. A namespace whitelist would additionally destroy 577 legitimate non-canonical chemical commits (LM 195, UMLS 98, UNII 97, MESH 77, PUBCHEM.COMPOUND 52, …), including plainly-correct ones like `S-adenosylhomocysteine -> UNII:8K31Q2S66S`.
- **Fail open on an absent type assertion.** `is_on_category` returns `True` when `categories` is missing/empty or is a *pure* top-of-hierarchy sentinel — `biolink:NamedThing` is not a descendant of `biolink:ChemicalEntity`, so without that clause the guard would drop exactly the untyped-but-real chemicals it exists to protect. "Pure" matters: `['biolink:NamedThing', 'biolink:Pathway']` *is* a type assertion and is judged normally.
- **A guard a caller can step around is not a guard.** `kestrel_text` / `kestrel_vector` documented `accepted_categories` as "not applicable" and committed `term_results[0]` unconditionally. Since `annotators` is API-exposed, `annotators=['kestrel-vector-search']` could commit a Protein for a small-molecule query that the default set refuses. All three annotators now validate, bulk paths included.

**Deliberate non-alignment, documented rather than fixed.** `studies/shared_gold_set/labeler.py` still adjudicates by `keys[0]` equality while `connectivity_match` moved to set intersection. Adopting the system's own equivalence relation there would make gold labels agree with the resolver *by construction* on exactly the multi-valued cases the fix changed — destroying the module's non-circularity premise. Strictness there can only defer to expert review, never mislabel. The cost (auto-labeled rows under-represent multi-InChIKey compounds) is now stated in the module docstring instead of being silent, and regenerating the pinned artifact under intersection semantics is filed as a follow-up.

**Baseline parity, not clean, is the bar.** dev is pre-existing lint-red. Both branches: ruff 24 errors, pytest 25 failed / 16 errors (all pre-existing `KESTREL_API_KEY`). State the baseline explicitly so "tests pass" is not read as a claim the branch cannot support.

## Related

- PR [#47](https://github.com/trentleslie/biomapper2/pull/47) — the change this documents
- PR #36 — fixed the same multi-valued-INCHIKEY `keys[0]` artifact in the Hajjar scorer; `connectivity_match` here is the second instance of that defect
- [Trustworthy gates: invoke them, test the real producer shape, keep fallbacks semantically faithful](trustworthy-gates-invoke-test-real-shape-faithful-fallbacks-2026-08-04.md) — the sibling principle for gates; this doc is its analogue for measurement instruments
- [Pinned benchmark data files silently gitignored](../runtime-errors/gitignore-globs-exclude-pinned-benchmark-data-2026-08-04.md) — same `.gitignore` failure mode as #9 above
- `studies/analysis/off_category_audit.py`, `studies/analysis/results/off_category_audit_suite_20260805T033340Z.{json,md}`
- `tests/test_no_measured_figures_in_prose.py`, `tests/test_off_category_audit.py`
