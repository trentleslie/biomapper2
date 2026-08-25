---
title: "feat: BioMapper cross-cohort harmonization arm benchmark (Deliverable 2, Groups B + queue-of-C)"
type: feat
status: active
date: 2026-08-25
deepened: 2026-08-25
origin: docs/brainstorms/2026-08-22-cross-cohort-eitl-campaign-requirements.md
---

# BioMapper cross-cohort harmonization arm benchmark

## Overview

Build the offline harness that, for each of the four NECS-anchored cohort pairs, resolves both cohort
panels with **BioMapper**, links metabolites across cohorts, and — for each link — issues a **structural
certificate from a source independent of the KG resolution that formed the link**, or **refuses** when
no independent structure exists. The **primary, checkable-artifact deliverable is the per-link
certificate/refusal record**; the per-pair count comparison against Monti et al. 2026 and the
refusal-sensitive summary score are **secondary** context, not the headline.

This ordering is deliberate. The project's audit history is unambiguous: *every claim resting on an
aggregate rate collapsed; every claim resting on a specific checkable artifact survived.* Count-beats
and single scalar scores are aggregate rates; per-link certificates are artifacts. The plan leads with
the artifact.

Everything except the live BioMapper resolution and the (optional, one-time) independent-structure
lookups is offline and testable first. The live run against public Kraken 2.1.0 is a single explicit,
gated, supervised operator step.

## Problem Frame

Monti harmonized NECS against Arivale, Xu, LLFS, and BLSA by name matching (Arivale/Xu, after manual
curation) and RefMet joins (LLFS/BLSA), reporting overlap counts (origin §A/§B). The preprint spine is
"a structural certificate issued for a name-input resolution, plus refusal when one cannot be issued" —
coverage alone reproduces the limitation being criticized. So the deliverable is a per-link structural
verdict, and the Monti counts are context the certificate adjudicates, not a finish line.

**The strategic claim rests on two pairs, and the plan says so.** Only **LLFS and Xu** can carry a
*certified-recovery* claim (cross-platform / large-headroom with adjudicable structure on both sides
where vendor IDs exist). **Arivale** is 98% covered → a same-vendor **reproduction control**, not
recovery. **BLSA** is ~81% sum-composition lipid species (Tian 2023) that name a *set* of molecules →
**coverage-only context**, never structurally certified. All four pairs are built (origin reaffirmed
four-pair scope 2026-08-22, gated by the R11c sizing step), but the certified-recovery headline is
LLFS+Xu; Arivale and BLSA are explicitly labeled as control and context.

This is **Deliverable 2**. Deliverable 1 (NECS gold repair, PR #55,
`docs/plans/2026-08-22-001-fix-necs-gold-repair-plan.md`, `status: active`, unmerged) is separate.
**Only Units 1–3 here are #55-independent**; the certificate units (5, 7b) depend on #55's
`scorers/structure_compare.py` (see Dependencies).

## Requirements Trace

Origin Group B (Deliverable 2) + the queue-build subset of Group C. Each requirement maps to an owning
unit; requirements intentionally out of scope are in **Deferred to Separate Tasks**.

- **R5** — resolve each panel's names to CURIE sets in the three arms → Units 1, 4.
- **R6** — Arm M linking is CURIE-set **intersection**, never structural identity → Unit 2.
- **R6a** — the certificate oracle must be **independent of the KG node that formed the link** (no self-certification off the resolved node) → Unit 5.
- **R6b** — links whose only available structure is the KG node itself are **excluded from the certified count and reported separately** as self-referential → Units 5, 4.
- **R7** — emit the **structural certificate verdict and the compared keys** per link → Unit 5.
- **R7a** — the link-level **verdict state table** (per-side: structure present/absent, corroborated/contradicted/lookup-failed) and its composition rule → Unit 5.
- **R8** — three numbers per pair (asserted / certified / refused) → Units 4, 5.
- **R8a** — report **both** refusal-sensitive metrics (not one) → Unit 4.
- **R8b** — **freeze the scoring threshold/formula before the live run** (pre-registration) → Units 4, 7.
- **R9** — identical row set and denominator across arms per pair → Units 2, 4.
- **R10 / R10a** — the queue is **three-valued** (certified / refused / uncertified-asserted) crossed with the baseline binary; agreement cells become a control sample; do not flatten to two-valued → Unit 6.
- **R11 / R11b / R11c** — certificate triage across all four pairs; planted known-wrong controls; report queue size before and after triage → Units 5, 6.
- **R13** — export queued items to the EITL `pairs` model → Unit 6.
- **R14 / R14a** — label structurally-unadjudicable items before queueing; define the **refusal export representation** (the `pairs` schema requires non-null target fields — a refusal has no target CURIE, so placeholders must never render as a real candidate) → Unit 6.
- **R15a** — **blinding is an export-time property**: on a blinded export pass, the LLM/arm-identifying fields (`llmConfidence`/`llmModel`/`llmReasoning`, proposing arm) are NULLed at write time; no app code changes → Unit 6.
- **R21 / R21a** — per-pair comparison against Monti's published counts, stating the exact row set each figure used; **Monti-published is primary** (we did not compute it), the re-derived identical-row Arm-B is the supporting comparison → Unit 3.
- **R23** — persist every run to a timestamped path by default with pinned source SHAs, deployment URL, `/metagraph` fingerprint, ChEBI release, commit → Unit 4.

## Scope Boundaries

True exclusions only:

- **Not** Deliverable 1 (gold repair) — PR #55.
- **Not** the mapper — `src/biomapper2` is invoked unchanged; no `src/` changes.
- **Not** the EITL **campaign protocol** — the two-campaign blinded→revealed execution, voting, blind-integrity guessing, and reporting (origin R15, R15b–c, R16, R17, R18–R20, R22/R22a/R22b) are deferred. This plan produces only the queue and its blinding-safe export (R10–R15a).

### Deferred to Separate Tasks

- **EITL campaign execution** (R15/R16/R17/R18–R20) — separate task once the queue (Unit 6) exists and the app ingests it.
- **Expert-precision reporting and the committed analysis plan** (R22/R22a/R22b) — Groups D–E, executed after the campaign.
- **The live BioMapper resolution run** and live independent-structure lookups — built here as gated operator steps (Units 4, 5, 7), executed under supervision, not in this plan's automated scope.

## Context & Research

### Relevant Code and Patterns

- `studies/external_benchmarks/runner.py` — `run_vocab` (name-only: `provided_id_columns=[]`, `annotation_mode='all'`) and `run_provided_id` (provided-id-only: `annotation_mode='none'`, no name resolution). Manifest + guards (`assigned_stats_nonnull`, `EmptyDatasetError`, `TrivialMappingError`), save-by-default. **The two existing wrappers are disjoint; Arm M+ID needs a NEW wrapper (see Key Decisions).**
- `src/biomapper2/mapper.py::map_dataset_to_kg` — supports `provided_id_columns=[...]` with `annotation_mode='missing'` ("annotate only entities without provided_ids") — this **is** the Arm M+ID capability; no mapper change needed, only a runner wrapper.
- `studies/external_benchmarks/scorers/curie_scorer.py` — `normalize_curie` / `canonical_prefix` (folds `KEGG.COMPOUND`→`KEGG`, `PUBCHEM.COMPOUND`→`PUBCHEM`), predicted CURIEs from `chosen_kg_id` + `kg_equivalent_ids`. **The Arm-M intersection primitive.**
- `studies/external_benchmarks/scorers/independent_inchikey.py` — **the KG-independent structure oracle** (PubChem PUG-REST from vendor HMDB/PubChem/CAS). Its own docstring records that "the structural concordance is circular (both sides resolved by the same Kestrel KG)" — this module exists precisely to break that circularity. **Mandatory for the cohort-side certificate (R6a).** Note: it returns **first blocks only** today; extending it (or `structure_compare.py`) to the two-block `block1+block2[:8]` key is part of Unit 5.
- `studies/external_benchmarks/config.py` — `DatasetConfig` / `ProvidedIdDatasetConfig` (`arm`, `provided_id_columns`, `annotation_mode`); NECS + RefMet present, the four cohort configs absent. The SHA is pinned at **adapter load** (`sha256_bytes`), not on the config — Unit 1 pins there.
- Adapter pattern: `adapters/necs_metabolon.py`, `adapters/provided_id.py`. Arivale/Xu/LLFS/BLSA adapters absent.
- `~/external_benchmark_runs/monti_string_replication_20260820T182111Z/replicate_monti_stated_methods.py` — the validated Arm-B reconstruction (reproduces Monti within ±5–20%).

### Institutional Learnings

- **Circular structural adjudication is this project's signature failure** (Deliverable 1: "reads KRAKEN's own InChIKey first… NOT KG-independent"). `independent_inchikey.py` was built to break it for the single-dataset case; this plan must carry that independence across the cohort boundary (R6a).
- "Every guard built had a blind spot that made it report clean" — each guard needs a positive control that fails, **including one that exercises the co-derivation failure mode** (two names → same wrong KG node), not just key granularity.
- Public Kraken returned 5xx under load (2026-08-05) — the live run needs retry/backoff; a transient 5xx must not fail a whole pair.
- A gold/id leaking into the provided-id path yields a trivial 100% — keep arms' denominators identical and the `assigned_stats_nonnull` guard live.

### External References

- Monti et al. 2026, GeroScience, doi:10.1007/s11357-026-02174-2 (subscription). Baselines: Arivale 615, Xu 432, LLFS 163, BLSA 99. **Springer terms apply to MOESM5/MOESM6 — no supplement content in a public figure/dataset without a licensing check; if Xu-821 is sourced from MOESM6 this applies to it.**
- Arivale: Watanabe 2023, PMC10115644, **CC BY** — `~/external_benchmark_runs/arivale_public_panel_20260804/watanabe2023_supp_data2_analytes.xlsx`, sheet `Arivale_Metabolomics`, **766 metabolites** (CAS 393 / KEGG 253 / HMDB 464 / PubChem 422 → independent structure available).
- LLFS: Sebastiani 2024, PMC11656345 — the **408-row** published panel (formula/exact-mass; **no per-metabolite HMDB/PubChem** → largely non-independently-certifiable, see R6a consequence).

## Key Technical Decisions

- **Reuse the mapper unmodified.** Arm M = `run_vocab` (name-only). Arm M+ID = a **new runner wrapper** calling `map_dataset_to_kg(provided_id_columns=[…vendor ids…], annotation_mode='missing')` — capability exists in the mapper; the wrapper is the only new invocation code.
- **Linker vs oracle are separated on DATA SOURCE, not just operation (R6a).** Arm M links by CURIE-set intersection (`normalize_curie` over `chosen_kg_id ∪ kg_equivalent_ids`). The certificate compares two structures **each resolved independently of the KG node that formed the link** — cohort side via `independent_inchikey.py` (PubChem from vendor CAS/HMDB/PubChem), NECS side via the repaired gold (#55). Separating only the *operation* (as an earlier draft did) does **not** break circularity when both sides read the same KG node's InChIKey.
- **No independent structure → REFUSE, never certify off the KG.** LLFS (formula/mass only) and BLSA (sum-composition) endpoints are **not structurally certifiable**; their links are refused (counts-only). The "~111 adjudicable LLFS pairs" figure is retired — it was adjudicable only via the circular path; the real adjudicable count on LLFS is recomputed under R6a and is expected to be small.
- **Certification go/no-go is NECS↔Arivale** (independent structure on both sides). NECS↔LLFS is the go/no-go for the **linking rule + Arm-B** only (its known target 163 is the reference), never for certification.
- **Adjudication / certificate key = `block1 + "-" + block2[:8]`** (block-1 alone merges 11 must-separate groups: fumarate/maleate, myo-/chiro-inositol, lactose/maltose, cis/trans-urocanate, bilirubin isomers, ursodeoxycholate/isoursodeoxycholate, threonate/erythronate).
- **Refusal-sensitive score is pinned to a formula (R8, R8a, R8b):** `score = certified / |comparable rows|`, with the denominator the fixed identical-row set (R9) so refusing only ever removes from the numerator, never raises the score. Report **both** metrics (certified/comparable and certified/asserted) and **always the three raw counts + denominator beside any scalar**. Formula/threshold frozen before the live run.
- **No cross-pair pooled rate.** Every headline number is per-pair, tagged `(row-set, adjudicable-fraction, reproduction|recovery)`. A report-time guard rejects any synthetic aggregate that mixes Arivale-reproduction and BLSA-counts-only rows.
- **Arm-B is the baseline we build, so it is locked before we beat it.** Arm-B counts are frozen as a characterization test at a recorded commit before any live run; the recovery claim must beat **Monti-published** (the number we did not compute) and exceed the per-pair `|re-derived − published|` reconstruction gap.
- **Coverage-only claims are prohibited** — every reported overlap carries the asserted/certified/refused triple. (Moved here from Scope Boundaries: this is a constraint on the work, not an exclusion.)

## Open Questions

### Resolved During Planning

- Pair matrix — four NECS-anchored pairs; Arivale = 766 public panel; LLFS = 408 published panel (Trent, 2026-08-25).
- Arm-M linking primitive — `curie_scorer.normalize_curie` over `chosen_kg_id ∪ kg_equivalent_ids`.
- Arm M+ID mode exists in the mapper (`annotation_mode='missing'`); needs only a runner wrapper.
- Certificate independence — mandated via `independent_inchikey.py` on the cohort side (R6a).

### Deferred to Implementation

- **Exact CURIE-set membership rule for a "link"** (single shared CURIE vs a minimum-confidence filter) — settled against the NECS↔LLFS **linking** slice (Unit 7a), where Arm-B 163 is the reference.
- **`structure_compare.py` provenance** — it is a **PR #55 deliverable, not yet present**. Decide at execution: gate Units 5/7b on #55 landing it, or vendor the two-block comparator into this plan as a `Create:`. Units 1–3 proceed regardless.
- **Data sourcing (blocking Unit 1 for two panels):** Xu-821 source path + license (if MOESM6, Springer terms apply); the **408-row** LLFS panel file (the staged LLFS artifact is the 364-row RefMet subset, wrong input); and the BLSA exclusion that reduces the staged 497 names to the expected 468.
- **EITL `pairs` DDL** — the schema lives in the separate `expert-in-the-loop` repo, not here. Pin the actual model/DDL as a Unit 6 input, or Unit 6 emits an intermediate export format and defers the schema binding.
- **Kraken batch size / retry budget** for the live run — tuned against the endpoint (Unit 4).

## High-Level Technical Design

> *Directional guidance for review, not implementation specification.*

```
For a cohort pair (NECS, C):
  panel_N, panel_C  = adapter(NECS), adapter(C)                 # names + vendor IDs, SHA pinned at load
  # ---- LIVE, gated ----
  curies_N = run(panel_N, arm); curies_C = run(panel_C, arm)    # arm M = name-only; M+ID = mode 'missing'
  # ---- offline ----
  links   = { (n,c) : normalize(curies_N[n]) ∩ normalize(curies_C[c]) ≠ ∅ }        # Arm M / M+ID (LINKER: KG)
  arm_b   = monti_reconstruct(panel_N, panel_C)                 # locked pre-run; Monti-published primary
  for each link:
     structN = repaired_gold(n)                                 # NECS side, KG-independent (#55)
     structC = independent_inchikey(vendor_ids(c))              # cohort side, KG-independent (ORACLE ≠ linker's node)
     verdict = certify | refuse | self-referential             # refuse if either side has no independent structure
              on block1+block2[:8]                              #   (LLFS/BLSA → refuse, counts-only)
  report per pair: asserted / certified / refused (+ self-referential),
                   score = certified/|comparable rows|, raw counts, (row-set, adjudicable-frac, repro|recovery)
                   NO cross-pair pooled number
  queue: three-valued(certified/refused/uncertified) × baseline-binary, + planted co-derivation control
         → EITL pairs export (blinded pass NULLs llm/arm fields; refusals get a non-candidate placeholder target)
```

## Implementation Units

Build order note (sequencing fix): **Unit 7a (LLFS linking slice) validates the open membership rule
BEFORE Units 2/4/5/6 are generalized to all four pairs**, so a design flaw is caught on a contained
slice, not across all-pairs code. Four-pair final scope is unchanged.

- [ ] **Unit 1: Cohort panel adapters + configs (Arivale, Xu, LLFS, BLSA)**

**Goal:** Load the four cohort panels into the adapter/DatasetConfig shape with name + vendor provided-id columns, SHA pinned at load.

**Requirements:** R5, R7 (M+ID input), R9

**Dependencies:** Data sourcing (see Deferred) for Xu-821 and LLFS-408.

**Files:** Create `studies/external_benchmarks/adapters/{arivale,xu,llfs,blsa}.py`; Modify `config.py` (`ARIVALE/XU/LLFS/BLSA`); Test `studies/external_benchmarks/tests/test_cohort_adapters.py`

**Approach:** Mirror `necs_metabolon.py`. Arivale from the 766-row `Arivale_Metabolomics` sheet (name `BiochemicalName`; ids CAS/KEGG/HMDB/PubChem). LLFS from the **408-row** published panel (name + formula/mass; flag as non-independently-certifiable — no per-metabolite structural id). Xu (821) and BLSA from their panels; BLSA rows flagged sum-composition/non-certifiable at load. Record and report every exclusion count (e.g. BLSA 497→468) — never silent.

**Test scenarios:**
- Happy path: each adapter yields expected counts (Arivale 766, LLFS 408, Xu 821, BLSA 468) with non-empty name column.
- Edge case: exclusions (unnamed/`X-`, BLSA 497→468) are reported, not silent.
- Error path: a renamed/absent source column fails loud (SwissLipids zero-byte lesson).
- Edge case: LLFS rows carry `independent_structure=False`; BLSA rows carry `certifiable=False`.

**Verification:** Panels load to expected sizes; independent-structure availability flagged per row; SHAs pinned at load.

- [ ] **Unit 2: Cross-cohort overlap scorer (Arm M / M+ID linking)**

**Goal:** Given two panels resolved to per-name CURIE sets, compute Arm-M links by CURIE-set intersection on an identical, explicit row set.

**Requirements:** R6, R9

**Dependencies:** Unit 1

**Files:** Create `studies/external_benchmarks/scorers/cross_cohort_overlap.py`; Test `.../tests/test_cross_cohort_overlap.py`

**Approach:** CURIE set = `normalize_curie` over `chosen_kg_id ∪ kg_equivalent_ids`; link iff sets intersect. No structure here. Operate on mock/cached CURIE sets (fully offline). Emit the identical comparable-row denominator shared by all arms.

**Execution note:** Test-first.

**Test scenarios:**
- Happy path: shared `KEGG:C00031` links; disjoint sets do not.
- Edge case (positive control): `KEGG.COMPOUND:C00031` links to `KEGG:C00031` after canonicalization; a non-aliased pair (`KEGG.GLYCAN`) deliberately does **not** link.
- Edge case: empty CURIE set → no link, a refusal candidate, not an error.
- Edge case: denominator = identical comparable-row set regardless of arm (R9).

**Verification:** Link count + denominator match hand-computed fixtures; canonicalization control both links the alias and rejects the non-alias.

- [ ] **Unit 3: Arm-B baseline reconstruction, locked pre-run**

**Goal:** Recompute Monti's per-pair overlap on the identical row set and **freeze it as a characterization test at a recorded commit** before any live run; report Monti-published as primary.

**Requirements:** R21, R21a, R8b (pre-registration discipline)

**Dependencies:** Unit 1

**Files:** Create `studies/external_benchmarks/scorers/arm_b_baseline.py`; Test `.../tests/test_arm_b_baseline.py`

**Approach:** Port `replicate_monti_stated_methods.py` (CHEMICAL_NAME match for Arivale/Xu; RefMet join with `drop_na(refmet_name)` for LLFS/BLSA). Return the identical-row link set + the published-figure annotation + the per-pair `|re-derived − published|` gap (the error bar the recovery claim must beat).

**Execution note:** Characterization-first — the test locks the counts; the recorded commit is the pre-registration.

**Test scenarios:**
- Happy path: re-derived counts land in the validated band (Arivale ~583, LLFS ~144, Xu ~470, BLSA ~79) and are pinned.
- Edge case: RefMet-undefined names dropped before join; drop count reported.
- Error path: a pair with no method mapping fails loud (no default to name-match).

**Verification:** Re-derived counts reproduce the 2026-08-20 replication and are frozen; each figure records its row set and its gap to Monti-published.

- [ ] **Unit 4: Pair driver + pinned manifest + frozen score (gated live run)**

**Goal:** Orchestrate a pair — run BioMapper on both panels (the gated live step), score all three arms on identical rows, emit the three-number table + both refusal-sensitive metrics, persist with a fully pinned manifest.

**Requirements:** R5, R7, R8, R8a, R8b, R9, R23, R6b (self-referential reported separately)

**Dependencies:** Units 1, 2, 3, 5

**Files:** Create `studies/external_benchmarks/cross_cohort_run.py` and the Arm-M+ID runner wrapper in `runner.py`; Test `.../tests/test_cross_cohort_run.py`

**Approach:** Reuse `map_dataset_to_kg` via the new M+ID wrapper (`annotation_mode='missing'`) and `run_vocab` for M. Live calls isolated behind one explicit entry point; offline scorers consume cached CURIEs. Manifest pins deployment URL, `/metagraph` fingerprint, ChEBI release, source SHAs, commit. Retry/backoff on 5xx. Compute `certified/|comparable|` (frozen formula) **and** `certified/asserted`; always emit raw counts. Report self-referential (KG-only-structure) links separately from certified (R6b).

**Execution note:** Live BioMapper calls are a supervised operator step — default path runs on cached CURIEs; live requires an explicit flag.

**Test scenarios:**
- Happy path (offline): cached CURIEs → the triple + both metrics + a manifest with all pins populated.
- Edge case (positive control): a manifest missing any pin (e.g. `/metagraph` fingerprint) fails the run.
- Edge case (positive control): refusing an asserted-and-certified link **strictly lowers** `certified/|comparable|` (catches a formula that ignores refusals); refusing an uncertifiable link never raises it.
- Error path: N simulated 5xx retries then succeeds; persistent 5xx surfaces clearly, no silent partial table.

**Verification:** An offline pair run emits the three-number table, both frozen metrics, self-referential count separate, and a manifest that fails loud on any missing provenance field.

- [ ] **Unit 5: KG-independent structural certificate + refusal**

**Goal:** For each asserted link, issue a certificate only when **both** structures are resolved independently of the KG node that formed the link; otherwise refuse. Emit the per-side verdict state table.

**Requirements:** R6a, R6b, R7, R7a, R8, R11b

**Dependencies:** Units 1, 2; **`structure_compare.py` (PR #55 deliverable — gate or vendor, see Deferred)**; `independent_inchikey.py` (present, extend to two-block key)

**Files:** Create `studies/external_benchmarks/scorers/link_certificate.py`; Test `.../tests/test_link_certificate.py`

**Approach:** Cohort-side structure from `independent_inchikey.py` (PubChem from vendor CAS/HMDB/PubChem); NECS-side from the repaired gold (#55). Certificate = agreement on `block1+block2[:8]`. **Refuse** when either side lacks an independent structure (LLFS formula/mass, BLSA sum-composition) — do **not** fall back to the KG node's InChIKey. Verdict state table per side: {structure present/absent} × {corroborated/contradicted/lookup-failed}; compose to certify | refuse | self-referential (R7a). A link whose only structure is the KG node is **self-referential**, excluded from certified, reported separately (R6b).

**Test scenarios:**
- Happy path: independent structures agreeing on block1+block2[:8] → certified; disagreeing → asserted-uncertified.
- Edge case (positive control): a stereoisomer pair agreeing on block-1 but differing on block2[:8] → not certified.
- Edge case (**co-derivation positive control, mandatory**): two distinct cohort names resolving to the **same known-wrong ChEBI node** (shared CURIE + shared KG-InChIKey) → the certificate **refuses/does-not-certify** it. This control can only pass because the oracle is independent of the KG node — it is the guard that would have caught the Deliverable-1 failure.
- Edge case: LLFS/BLSA link (no independent structure) → refused, never certified.
- Error path: PubChem lookup failure on one side → refusal, not a crash.

**Verification:** The co-derivation control fails as designed under KG-independent structure and would wrongly certify under a KG-default source; BLSA/LLFS never certify; self-referential links are counted separately.

- [ ] **Unit 6: Three-valued discrepancy queue + blinding-safe EITL export**

**Goal:** Build the three-valued queue (certified / refused / uncertified-asserted) crossed with the baseline binary, triage it, and export to the EITL `pairs` model with blinding as an export-time property and a safe refusal representation.

**Requirements:** R10, R10a, R11, R11a, R11b, R11c, R13, R14, R14a, R15a

**Dependencies:** Units 4, 5; the EITL `pairs` DDL (see Deferred)

**Files:** Create `studies/external_benchmarks/eitl_queue.py`; Test `.../tests/test_eitl_queue.py`

**Approach:** Preserve the three-valued × baseline-binary structure (R10/R10a) — do not flatten to symmetric-difference. Agreement cells become an audit control sample (R11a). Report queue size before and after triage per pair (R11c). Inject planted known-wrong links incl. the co-derivation and self-certification cases (R11b). Export to `pairs`: blinded pass NULLs `llmConfidence/llmModel/llmReasoning` and the proposing arm at write time (R15a); refusals (no target CURIE) get a schema-valid **non-candidate placeholder** target that can never render as a real candidate (R14a); unadjudicable items labeled before queueing (R14).

**Test scenarios:**
- Happy path: each three-valued × baseline cell routes correctly; agreement cells populate the audit sample.
- Edge case (positive control): planted known-wrong + co-derivation + self-certification links are flagged by triage, not passed clean.
- Edge case (R14a): a refused link exports with a placeholder target that is provably non-renderable as a candidate; a validator rejects any refusal exported as a real target.
- Edge case (R15a): a blinded export has all LLM/arm fields NULL; a revealed export carries them.
- Integration: exported rows validate against the `pairs` schema and round-trip.

**Verification:** Export validates against `pairs`; blinded fields NULLed; refusals never render as candidates; before/after triage counts per pair; planted controls caught.

- [ ] **Unit 7a: NECS↔LLFS linking slice (settle the membership rule) — EARLY**

**Goal:** Wire NECS↔LLFS linking + Arm-B offline on cached CURIEs and settle the open CURIE-set membership rule against the known Arm-B target (163), **before** Units 2/4 are generalized to all four pairs.

**Requirements:** R6, R9, R21

**Dependencies:** Units 1 (LLFS+NECS only), 2, 3

**Files:** Create `.../tests/test_necs_llfs_linking.py`

**Approach:** LLFS is ideal here (known target 163) and is used **only** for the linking/Arm-B logic — not certification (it has no independent structure). Settle single-shared-CURIE vs filtered membership here; lock the choice before generalizing.

**Test scenarios:**
- Happy path: Arm-B reconstruction ≈163; the chosen membership rule reproduces a coherent link count.
- Edge case: the membership decision is recorded with its effect on the count.

**Verification:** The membership rule is settled and locked against Arm-B 163 before all-pairs generalization.

- [ ] **Unit 7b: NECS↔Arivale certification go/no-go — LAST before live**

**Goal:** Prove the certificate is **non-circular** end-to-end on the one pair with independent structure on both sides, and that every positive control (incl. co-derivation) fires. This is the recorded go/no-go for the live run.

**Requirements:** R6a, R6b, R7, R8, R8b

**Dependencies:** Units 1–6

**Files:** Create `.../tests/test_necs_arivale_certification.py`

**Approach:** Arivale carries CAS/KEGG/HMDB/PubChem → independent structure both sides. Run the full pipeline on cached CURIEs + cached independent-structure lookups; confirm the three-number table is coherent, the frozen score behaves, and all positive controls (canonicalization, block2[:8] stereo, manifest pin, co-derivation, anti-pooling) fail as designed.

**Execution note:** Characterization-first.

**Test scenarios:**
- Happy path: end-to-end NECS↔Arivale yields a coherent certified/refused/asserted triple with independent structures.
- Integration: all positive controls fire; the co-derivation control refuses; the anti-pooling guard rejects a synthetic Arivale+BLSA aggregate.

**Verification:** Certification is demonstrably non-circular on independent structure; every guard's positive control fails as designed; this is the recorded go/no-go.

## System-Wide Impact

- **Interaction graph:** New `studies/external_benchmarks/` modules + one new `runner.py` wrapper; consumes `map_dataset_to_kg`, `curie_scorer`, `independent_inchikey`, and #55's `structure_compare`. No `src/biomapper2` change.
- **Error propagation:** Live 5xx retried then surfaced; empty panels, missing manifest pins, and PubChem lookup failures fail loud or refuse — never a scorable-looking zero or a KG-fallback certificate.
- **State lifecycle:** Save-by-default to timestamped dirs; a Ctrl-C mid-run must still leave a manifest (`finally`-write).
- **API surface parity:** The M+ID wrapper is the only new invocation seam; the mapper's public API is unchanged.
- **Unchanged invariants:** `src/biomapper2` resolution behavior is unchanged; this is a benchmarking layer above it.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Certificate circular (both sides read the KG node) — the audit failure | R6a: independent oracle (`independent_inchikey.py`) both sides; no-independent-structure → refuse; co-derivation positive control that only passes when independent |
| `structure_compare.py` absent (a #55 deliverable) blocks Units 5/7b | Units 1–3 proceed; decide gate-on-#55 vs vendor the two-block comparator (Deferred) |
| Arm M+ID combined mode assumed | Verified: `map_dataset_to_kg(annotation_mode='missing')` supports it; only a runner wrapper is new |
| Arm-B is the baseline we build and beat | Lock Arm-B pre-run at a recorded commit; recovery must beat Monti-published and exceed `|re-derived − published|` |
| Aggregate-rate collapse (score, count-beat) | Lead with per-link certificate artifacts; pin the score formula; no cross-pair pooled rate (firing guard); always show raw counts |
| Arivale-easy / BLSA-counts pollute a headline | Per-pair only; tag reproduction vs recovery; anti-pooling guard with positive control |
| Public Kraken 5xx under load | Retry/backoff; transient 5xx doesn't fail a pair |
| EITL `pairs` schema not in this repo | Pin the real DDL as a Unit 6 input or emit an intermediate format (Deferred) |
| Data gaps: Xu-821, LLFS-408, BLSA 497→468 | Source + license each before Unit 1 (Deferred); Springer terms if Xu = MOESM6 |
| Springer terms on Monti content | No supplement content in a public figure/dataset without a licensing check |

## Documentation / Operational Notes

- Live run is a supervised operator step: run with the live flag, confirm manifest pins, then score offline.
- Persist each pair to `~/external_benchmark_runs/cross_cohort_<pair>_<timestamp>/`; print the path.
- Report `no-run`/partial states out loud — a pair that never resolved must not read as zero overlap.

## Sources & References

- **Origin document:** [docs/brainstorms/2026-08-22-cross-cohort-eitl-campaign-requirements.md](docs/brainstorms/2026-08-22-cross-cohort-eitl-campaign-requirements.md)
- Deliverable 1 plan: `docs/plans/2026-08-22-001-fix-necs-gold-repair-plan.md` (PR #55; source of `structure_compare.py`)
- Related code: `studies/external_benchmarks/{runner.py,scorers/curie_scorer.py,scorers/independent_inchikey.py,config.py}`; `src/biomapper2/mapper.py::map_dataset_to_kg`
- Arm-B replication: `~/external_benchmark_runs/monti_string_replication_20260820T182111Z/`
- Monti et al. 2026, GeroScience, doi:10.1007/s11357-026-02174-2
