# Plan — resolver correctness (PR 1: D1 + D2 + D4)

Artifact: `docs/plans/resolver-correctness-brainstorm.md`
workType: **software** · Base: `dev` on personal fork `trentleslie/biomapper2` (Greptile first, never straight to org)
Branch: `fix/resolver-category-acceptance`

Ledger constraints treated as fixed: **L4** (D1+D2+D4 here, D3 follow-up), **L5** (D3 = tighten
only, later), **L6** (engine-computed `accepted_categories` parameter; `descendants(biolink:ChemicalEntity)`;
failure-open on empty categories; log-only refusal + one instrumented run), **L7** (per-row A/B gate,
confirm KG snapshot), **L9** (baseline artifacts exist and are pinned).

---

## Phase 0 — Reproduce the defect as a failing test (TDD)

1. `tests/test_kestrel_hybrid_category.py` (new). Fixture rows are the **live-verified** shapes
   from the brainstorm artifact, not invented ones:
   - `EFO:0800030` / `['biolink:PhenotypicFeature']`, top-scored
   - `CHEBI:192245` / `['biolink:SmallMolecule']`
   - `UMLS:C0639060` / `['biolink:Protein']`, `NCIT:C178456` / `['biolink:Polypeptide']`
   - `UNII:LYJ3482CB6` / `['biolink:ChemicalEntity']`  ← **must survive** (one level up)
   - `CHEBI:75549` / `['biolink:MolecularMixture']`   ← **must survive**
   - `GO:0033265` / `['biolink:MolecularActivity']`, `PathWhiz:PW002494` / `['biolink:Pathway']` ← dropped
   - a row with `categories: []` and one with the key absent ← **must survive** (failure-open)
2. Assert current behaviour commits `EFO:0800030` (red), then that the fix refuses or picks a
   chemical row (green).
3. Add a test that `accepted_categories=None` reproduces today's behaviour byte-for-byte
   (the gene path's guarantee).

## Phase 1 — Config + engine (the `preferred_prefixes` mirror)

4. `src/biomapper2/config.py`: add `CATEGORY_ACCEPTED_ROOTS: dict[str, str]` directly beneath
   `CATEGORY_PREFERRED_NAMESPACES`, seeded `{"biolink:SmallMolecule": "biolink:ChemicalEntity"}`.
   Comment must state: keys are expanded via `get_descendants` so subcategories inherit; the
   **value** is the acceptance root and is expanded separately; gene/protein are intentionally
   absent (HGNC baseline is 0/4476 suspect); unmapped categories are unfiltered.
5. `annotation_engine.py`: add `_category_accepted_categories` as a `cached_property` beside
   `_category_preferred_prefixes` — for each configured key, map every `get_descendants(key)`
   member to `get_descendants(root)`. Union on overlap, same as the existing property.
6. `annotate()`: resolve `effective_accepted_categories = self._category_accepted_categories.get(category)`.
   **Independent of `prefer_canonical` and `prefer_human`** — category acceptance is a correctness
   guard, not a re-ranking preference, so it must not inherit the canonical policy's kill switch.
   Add it to the existing debug log line.

## Phase 2 — Thread the parameter (mechanical, mirrors `preferred_prefixes` exactly)

7. Add `accepted_categories: set[str] | None = None` to: `BaseAnnotator.get_annotations` and
   `.get_annotations_bulk` (with docstring matching the `preferred_prefixes` wording — "honored
   only by annotators that filter candidates; others accept and ignore it"), all five annotator
   implementations (`kestrel_hybrid`, `kestrel_text`, `kestrel_vector`, `metabolomics_workbench`,
   `goslin_lipid`), and `_annotate_dataframe` / `_annotate_single` (**not** `_annotate_entity` —
   the method is `annotation_engine.py:258 _annotate_single`).
8. Forward it at **six** sites, not four. Engine: `:138-139`, `:150-151`, `:245-246`, `:287-288`.
   Annotator: `kestrel_hybrid.get_annotations_bulk`'s internal re-dispatch (`:122-131`) **and —
   critically — both `_kestrel_hybrid_search` call sites, `:60` (single/no-cache) and `:117`
   (bulk)**. `_kestrel_hybrid_search` is a `@staticmethod`; if the kwarg stops at
   `get_annotations` the filter never receives it and the change is a silent no-op, the exact
   failure mode the `:119-121` comment warns about.
   **Do not use "matches how `preferred_prefixes` is threaded" as the completeness check** —
   `metabolomics_workbench.py:101-109` and `kestrel_text.py:67-75` do *not* forward
   `preferred_prefixes` to their per-row `get_annotations`, so mirroring reproduces a real gap.
8a. `limit` must not collapse. `kestrel_hybrid.py:59` and `:116` compute
   `limit = HYBRID_SEARCH_LIMIT if (prefer_human or preferred_prefixes) else 1`. Step 6
   deliberately decouples `accepted_categories` from those flags, so with `prefer_canonical=False`
   (a public request option, `api/models/requests.py:34`) the filter would run against a
   **one-row window** and refuse with no fallback — a hard coverage cliff on the live API path.
   Add `or accepted_categories` to both expressions.

## Phase 3 — The check (VALIDATOR on the committed node, not a filter on the pool)

**This is the reviewed design and it supersedes the pool-filter approach.** Rationale, all
evidence-backed:

- A pool filter promotes the next-best chemical into the vacancy. Live simulation at the
  production limit on 45 sampled off-category commits: **21 refuse / 18 replaced by a
  *different still-wrong* node / 6 unchanged.** The 18 replacements are *less* auditable than what
  they replaced (`EFO:…measurement` announces itself as not-a-molecule;
  `PUBCHEM.COMPOUND:131755421`, a triacylglycerol substituted for a plasmalogen, does not).
- **0 of those 18 promotions went to a canonical namespace, and that is structural, not luck.**
  `_select_canonical` (`:201-206`) already prefers CHEBI/HMDB/RM, so a promotion can only occur
  when *no* canonical node was in `term_results` at all — otherwise the baseline would already
  have committed it. Promotion-to-canonical is impossible by construction.
- Therefore "only promote to a canonical node" and "never promote" are **the same policy on this
  data** (both refuse on 39/39). Take the simpler one.

The validator form is strictly better: it eliminates wrong→wrong **by construction** rather than
by policy, collapses the diff to one predicate at the commit point, means no selector ever sees a
modified pool, makes the `limit` collapse (step 8a) moot, and reduces the failure-open question
from 20 candidate rows to 1 committed node.

Stated cost, accepted deliberately: the check can only convert **wrong→refuse**, never
wrong→right. The evidence says it was never producing wrong→right anyway (0/18).

9. `kestrel_hybrid.py`: add `_is_on_category(row, accepted) -> bool` —
   `True` if `accepted` is None; `True` if the node's `categories` is empty/missing **or is a pure
   top-of-hierarchy sentinel (`{'biolink:NamedThing'}` / `{'biolink:Entity'}`)** (failure-open);
   else `bool(set(categories) & accepted)`.
   *Evidence for the sentinel clause:* across 1,200 live candidate rows **zero** had empty or
   missing `categories`, so the originally-planned guard was dead code. Eight carried
   `['biolink:NamedThing']` — including `OBO:NCIT_C103149` "S-Adenosylhomocysteine" **top-scored
   at 4.889**, a legitimate metabolite. `biolink:NamedThing` is not among the 12 descendants.
10. Apply it in `get_annotations` at the single commit point (`:85`, `if chosen is not None`):
    if `chosen` fails `_is_on_category`, drop it and refuse. **Selectors are untouched** —
    `_select_result`, `_select_canonical` and the legacy top-1 all keep their current behaviour
    and see an unmodified pool. Steps 8 (the `_kestrel_hybrid_search` threading) and 8a (the
    `limit` collapse) become unnecessary under this design; the kwarg only needs to reach
    `get_annotations`.
11a. **CRITICAL — the guard is on CATEGORY, never on NAMESPACE.** Writing it as "the committed
    node must be in a canonical namespace" would destroy **294 legitimate non-canonical chemical
    commits**: UNII 97, MESH 83, PUBCHEM.COMPOUND 52, KEGG.GLYCAN 30, CHEMBL.COMPOUND 10, CHV 10,
    KEGG.COMPOUND 7, NCIT 5 — including plainly-correct ones such as
    `S-adenosylhomocysteine → UNII:8K31Q2S66S` (srm1950). All 26 of refmet's UNII/PUBCHEM commits
    are category-clean. Namespace preference is `_select_canonical`'s job and stays there.

## Phase 3-alt (superseded) — pool filter

9. `kestrel_hybrid.py`: add `_in_accepted_category(row, accepted) -> bool` —
   `True` if `accepted` is None; `True` if `row.get("categories")` is empty/missing **or is a
   pure top-of-hierarchy sentinel (`{'biolink:NamedThing'}` / `{'biolink:Entity'}`)**
   (failure-open); else `bool(set(row["categories"]) & accepted)`.
   *Evidence for the sentinel clause:* across 1,200 live candidate rows, **zero** had an empty or
   missing `categories`, so the originally-planned guard was dead code. Eight carried
   `['biolink:NamedThing']` — including `OBO:NCIT_C103149` "S-Adenosylhomocysteine" **top-scored
   at 4.889**, a legitimate metabolite. `biolink:NamedThing` is not among the 12 descendants, so
   without this clause the filter drops exactly the typing-gap case the guard was meant to protect.
10. Apply it in `_kestrel_hybrid_search` alongside the existing `score >= 0.5` cut (`:232`), so
    every downstream selector (`_select_result`, `_select_canonical`, the legacy top-1) sees an
    already-clean pool and no selector needs to change.
11. Refusal: with the pool empty after filtering, `term_results` is `[]`, `_select_canonical`
    returns `(None, False)` and `get_annotations` already skips the `chosen is not None` block —
    so refusal falls out of existing control flow. Add a single
    `logging.info("no_in_category_candidate: %s", search_term)` at the point of emptying, keyed
    so the instrumented run can grep it. **No `AssignedIDsDict` shape change** (L6: log-only).
    **Invariant this depends on, assert it explicitly:** the free ride only holds when
    `prefer_human` is False. At `:69`, `prefer_human and GENE_SYMBOL_FALLBACK_ENABLED and not
    matched` fires the `GeneSymbolResolver`, and `get_annotations` defaults `prefer_human=True`.
    Via the engine this is unreachable (`get_descendants('biolink:SmallMolecule')` is exactly
    `{'biolink:SmallMolecule'}`, disjoint from the human-applicable set), but Phase 0 calls the
    annotator directly, so **every new test must pass `prefer_human=False` explicitly**, as
    `tests/test_kestrel_hybrid_canonical.py:71,103` already do. Otherwise the refusal assertion
    silently drives a live `/get-nodes` call.
11a. **PROMOTION POLICY — see "Unresolved decision" below.** Whether an empty *canonical* pool
    may promote the top-scored non-canonical chemical is NOT settled by this plan.
12. Scope: `kestrel_hybrid` only. `kestrel_text` / `kestrel_vector` carry the identical bug but
    `_select_annotators` never auto-selects them, so they are not on the measured path; they
    accept-and-ignore the new kwarg and are filed as a follow-up. Keeps the Greptile diff single-purpose.

## Phase 4 — D2 and D4

13. `structure_resolver.py:37-38`: `connectivity_match` switches from `inchikey_block` to
    `inchikey_blocks`. New semantics: either set empty → `None`; intersection non-empty → `True`;
    disjoint → `False`. Update the docstring, which currently says "same first InChIKey block".
14. `resolver.py:129,133`: replace `refmet_nodes[0]` with a deterministic pick — `sorted(...)[0]`
    — and comment that RefMet returning >1 node is itself a signal, so ordering must not be
    incidental. Behaviour is unchanged whenever the list has one element (the common case).
15. Tests, assigned to files that can actually express them:
    - `tests/test_structure_resolver.py` — gold matching a **non-first** INCHIKEY entry now
      returns `True` (the PR #36 artifact, now in the resolver). This is the only file that
      drives the real `connectivity_match`; `test_resolver_source_weighting.py:12-16` and
      `test_source_weighting_e2e.py:42` replace it with a `MagicMock`, so the assertion is
      meaningless there.
    - `tests/test_resolver_source_weighting.py` — multi-node RefMet is order-independent (D4).
    - Verified safe: all six existing `connectivity_match` tests use single-element INCHIKEY
      lists, so `inchikey_blocks` yields singletons and intersection semantics are identical.
      `oracle.py:33,44` calls `inchikey_block`/`inchikey_blocks` directly, never
      `connectivity_match`. `inchikey_blocks` retains the MW/PubChem name fallback (`:80-81`),
      so D2 will not inflate `conflict_no_structure`.
15a. **D4 contamination risk: measured and cleared.** Review asked whether D4 could change rows
    and pollute the D1 gate. Counted over the pinned baseline: **8,814 rows carry a
    `metabolomics-workbench` (RefMet) vote and 0 of them contributed more than one KG node.**
    So `sorted(refmet_nodes)[0]` is a provable no-op on every row of the A/B and cannot
    contaminate the D1 gate. It stays in PR 1 as reproducibility hardening against a case that
    does not occur today. Note it is a *determinism* fix, not a correctness one — lexicographic
    order is still chemically arbitrary; if the multi-node case ever appears, it needs a real
    tiebreak rule, so add a `logging.warning` when `len(refmet_nodes) > 1` to surface it.

## Phase 5 — Validation (the actual gate, L7)

16. `pytest` green; ruff/mypy no worse than the `dev` baseline (dev is known pre-existing lint-red —
    compare, do not require clean).
17. **Instrumented run** (throwaway, not committed): one suite pass with refusal logging at DEBUG,
    capturing every dropped candidate `(query, id, name, categories, score)`. Produces the
    over-filtering audit: how many drops were of rows that the baseline had committed **correctly**.
17a. **A-A null control run FIRST.** Rerun *unchanged* code at the baseline SHA against the same
    pinned KG and diff row-for-row against `suite_20260805T033340Z`. The plan asserts a ~1 pt
    aggregate noise floor, which implies per-row nondeterminism (`_select_canonical` breaks ties
    with `max(..., key=score)` over API list order). Without this control, every per-row diff
    mixes change-effect with run noise — and the per-row diff *is* the gate. Any row that differs
    A-A is excluded from the A/B gate as noise.
18. **A/B run** vs `~/benchmark-runs/suite_20260805T033340Z/`:
    - `KESTREL_API_URL=https://kestrel.krakenkg.com/api`, placeholder `KESTREL_API_KEY`
      (`config.py:21` still defaults to the internal host — must be set explicitly).
    - **Precondition**: new run's `kg_snapshot` == `kraken 2.0.1 (14683250n/92233909e)`,
      `chebi_node_count` == 202220, `biolink_version` == 4.2.5, `kg_stable_during_run: true`.
      A mismatch invalidates the comparison and the A/B must be rerun, not interpreted.
    - **Gate 1 — correct→incorrect**: per-row `chosen_kg_id` diff, excluding A-A noise rows.
      Pass = **no row that was correct in the baseline becomes incorrect**. Aggregate scores are
      expected flat and are *not* the gate — a flat aggregate can hide equal numbers of fixes and
      breaks, which is precisely what the per-row diff exists to catch.
    - **Gate 2 — wrong→wrong adjudication (added; Gate 1 is blind to it).** A live simulation of
      the proposed logic on 45 sampled suspect commits found **21 refuse, 18 REPLACED by a
      different still-wrong node, 6 unchanged**. All 18 pass Gate 1 (incorrect before *and*
      after), yet several are *less* auditable than what they replaced —
      `EFO:...measurement` announces itself as not-a-molecule, whereas
      `PUBCHEM.COMPOUND:131755421` (a triacylglycerol substituted for a plasmalogen) does not.
      **Required:** manually adjudicate a stratified sample of every wrong→wrong change and
      report the count. A rise in camouflaged wrong answers is a FAIL even with Gate 1 green.
      Note also `X - 06267` → the `EFO:0021200` "X-06267 measurement" node is arguably the
      *correct* entity for an unidentified Metabolon feature; the filter destroys it.
    - **Gate 3 — coverage delta. THIS IS THE REAL COST AND IT IS NOT NEUTRAL.** Under the
      validator design, **87%** of the off-category population refuses (45-row simulation:
      39 refuse / 0 promote / 6 unchanged). Extrapolated: **~1,000 rows become unmapped**, and
      **metLinkR coverage drops roughly 14 points** (1,000/7,060). Comparable ID-mappers report
      **coverage**, not accuracy, so this is the number a reviewer will fixate on. The axis brief
      said "expected effect on scores is roughly neutral" — that holds for *accuracy scores* but
      **not for coverage**. Report the coverage delta explicitly and state the trade openly:
      we are exchanging ~1,000 confidently-wrong commits for ~1,000 honest refusals.
      A `chosen_kg_id` diff joined across two runs will not show vanished rows — compute coverage
      separately. `lmsd/capability_regression.json` carries `regression_floor: 0.9` on
      `resolvability` (currently 1.0), a real gate refusals can trip.
    - Report: refusal count, wrong→wrong replacement count, per-dataset coverage delta,
      HGNC unchanged at 0/4476, and the `divergent_refmet` / `conflict_no_structure` flag-count
      delta from D2. Record `HYBRID_SEARCH_LIMIT` (=20) with the results, since refusal count is
      partly a function of it.
    - **Headline metric — replace the prefix metric with the off-category metric.** The 1,083
      prefix count *is* reproducible (a reviewer's non-reproducibility claim was retracted after
      they used the wrong prefix set), but it is the **wrong metric**: it counts CURIE *prefixes*
      while the intervention acts on Biolink *categories*, so the two do not align in either
      direction. Use instead, stated verbatim wherever the number appears:

      > **Off-category commit.** For each metabolite-arm benchmark row with a non-null
      > `chosen_kg_id`, resolve the node's Biolink `categories` via Kestrel `/get-nodes` and count
      > the row as off-category iff
      > `categories ∩ descendants(biolink:ChemicalEntity) = ∅`.

      Exactly computable, not estimated — `/get-nodes` is keyless
      (`POST {"curies":[...],"slim":false,"truncate_long_fields":true}`). All 6,225 distinct
      committed nodes resolved, 0 unresolved:

      | dataset | n | off-category | % | (old prefix metric) |
      |---|---|---|---|---|
      | metlinkr | 7060 | **1080** | 15.3% | 980 |
      | necs | 1488 | 65 | 4.4% | 82 |
      | refmet | 1500 | **0** | 0.0% | 14 |
      | srm1950 | 1058 | 3 | 0.3% | 6 |
      | lmsd | 1499 | **0** | 0.0% | 1 |
      | **metabolite total** | **12605** | **1148 (9.1%)** | | 1083 |
      | hgnc | 4476 | 4197 (93.8%) | | 0 |

      Composition of the 1,148: PhenotypicFeature 692, Gene+Protein 202, Protein 160,
      InformationContentEntity 35, CellLine 10, NamedThing 10, OrganismTaxon 10, rest <10.

      Three reasons it is the right metric: (1) it is exactly the population the intervention acts
      on, so **"1,148 → 0" is honestly achievable** rather than aspirational; (2) it stops counting
      correct commits as errors — refmet's 14 prefix-suspects are **0** off-category, i.e. all 14
      are correctly-typed UNII/NCIT nodes; (3) HGNC at 93.8% off-category is the clean positive
      control proving the gene path must stay unfiltered.
    - **Label it precisely: this is a *type-consistency* metric, not accuracy.** Off-category ≠
      wrong and on-category ≠ right. 6 of 45 sampled off-category commits are on-category and
      still nonsense (`XL-VLDL-P → KEGG.GLYCAN:G11365` "XLSG", typed `biolink:SmallMolecule`).
      The preprint must not imply this fix improves accuracy.
    - Watch **metLinkR** (980 of 1,083 suspects — biggest win and biggest risk) and **NECS**
      (Metabolon plasmalogen vocabulary). Baseline noise floor is ~1pt, so sub-1pt aggregate
      moves are not signal.
19. Persist all run artifacts by default to a timestamped path; pin git SHA + KG snapshot alongside.

## Phase 6 — PR

20. One PR to `trentleslie/biomapper2` base `dev`. **The body LEADS with the coverage delta
    (L12), not with the accuracy flatness.** Required order:
    1. **~1,000 rows move from mapped to unmapped; metLinkR coverage drops ~14 points.** State
       this first, as the intended trade: ~1,000 confidently-wrong commits exchanged for ~1,000
       honest refusals. Do not open with "scores are flat" — a reviewer who meets the coverage
       drop after being told the change is neutral will read it as a regression we missed.
    2. **The LMSD `resolvability` floor, addressed head-on.** `lmsd/capability_regression.json`
       sets `regression_floor: 0.9`, currently 1.0. If refusals trip it, **say so and justify it
       as the intended trade — do NOT adjust the floor to make the gate pass.** Silently relaxing
       a regression floor to accommodate one's own change is the failure mode this instruction
       exists to prevent.
    3. The off-category measurement, **1,148 / 12,605 (9.1%) → 0** (L13), with the definition
       inline and the type-consistency caveat attached.
    4. Accuracy A/B result, framed as *expected* flat, so "no lift" is not read as "no effect".
    5. The corrected D3 chemistry and why D3 is deferred.
21. **Required PR review-checklist item (L13, hard constraint):** confirm the guard is a
    **category** check on the committed node and **not** a namespace whitelist. The two forms look
    nearly identical in a diff and differ by **294 destroyed legitimate commits**.
22. Merits a Greptile credit: real logic, correctness-critical, changes committed output.
23. Follow-ups filed, not bundled: **(a)** D3 tighten-only per L5; **(b)** `kestrel_text` /
    `kestrel_vector` same validator; **(c)** refusal reason surfaced in `AssignedIDsDict` so the
    scorer can distinguish refusal from no-match; **(d)** the 1,148 off-category measurement
    routed to the preprint separately, coverage-delta-first.

---

## Decision resolved in review — validator, not pool filter

Adversarial review's P0 ("the filter substitutes type-camouflaged wrong answers") was accepted and
the design changed: the category check is now a **validator on the committed node** (Phase 3), not
a filter on the candidate pool. Established by targeted follow-up: canonical-only promotion and
never-promote are the same policy on this data (0/18 promotions were canonical, structurally),
so the simpler validator wins. Two review findings were **retracted** on re-check and must not be
carried forward: the 1,083 figure *is* reproducible, and the D4 contamination risk is nil
(0/8,814). What survives is the coverage cost (Gate 3), which is the one thing needing human
acceptance rather than engineering.

## Verified-clean premises (do not re-litigate)

Independently confirmed by adversarial review against live KRAKEN, so the acceptance set itself
is **not** the risk:

- 120 real baseline names sampled; of the 73 whose committed node appeared in returned rows,
  **62 kept / 11 dropped, and all 11 drops were intended suspects (EFO measurement, NCBIGene,
  UMLS Protein). Zero legitimate answers lost.**
- Peptide metabolites clear: glutathione `CHEBI:16856`, carnosine `CHEBI:15727`, anserine
  `CHEBI:18323`, ophthalmate `CHEBI:189750`. KRAKEN does mistype peptide metabolites as
  `biolink:Protein` via UMLS, but a CHEBI row is always present within the real limit and
  `_select_canonical` already prefers it — so rejecting `biolink:Polypeptide` is safe.
- Glycans clear: maltotriose `CHEBI:61993`, N-acetylneuraminate `CHEBI:35418`, hyaluronate,
  chondroitin sulfate — all present and chemical-typed.
- metLinkR **is** genuinely run with `category=biolink:SmallMolecule` (`entity_type="metabolite"`
  → alias table `biolink_client.py:98-115` via `runner.py:165`), and all 625 EFO / 285 UMLS /
  205 NCBIGene metLinkR commits come from `kestrel-hybrid-search` only — so scoping the fix to
  the hybrid annotator and the chemical branch is sound.
- `kestrel_text` / `kestrel_vector` are never auto-selected; `config.py:21` does default to the
  internal host; the 148-`.tsv` coincidence is real.

## Open risks carried into implementation

- **Over-filtering is the smaller hazard than assumed** (see above), but failure-open covers
  missing/sentinel types, not *wrong* types. A CHEBI node mistyped `biolink:PhenotypicFeature`
  would still drop silently. Phase 5.17 makes that visible; if the instrumented run shows
  correct-answer drops, add those specific categories rather than widening the branch wholesale.
- **The acceptance map covers exactly one category string.** `get_descendants('biolink:SmallMolecule')`
  is `{'biolink:SmallMolecule'}` (n=1), so any job whose *resolved* category differs — including
  `biolink:NamedThing`, the fallback `standardize_entity_type` returns for unrecognized entity
  types (`biolink_client.py:117-124`) — is unfiltered. Confirm each dataset's resolved category
  before reading a flat A/B as "no effect."
- **`limit` interaction.** Filtering happens after the API returns, so a query whose top-20
  (`HYBRID_SEARCH_LIMIT = 20`, `config.py:57` — not 10) is entirely non-chemical refuses rather
  than reaching deeper. Results are limit-stable (limit-10 set was a subset of limit-50 on 12/12
  probes), so this is bounded, but record the limit with the results.
- **D2 loosens, D1 tightens.** They land in one PR and move flag counts in opposite directions,
  so attribute the flag delta from the tests, not from the aggregate A/B.
