# Cross-Cohort Metabolomics Harmonization Benchmark

**Date:** 2026-08-04
**Status:** design approved, implementation not started
**Targets:** `studies/external_benchmarks`
**Preprint role:** the applied use case for the BioMapper preprint (A2.1, clinical-lab molecular entity resolution)

---

## 1. Motivation

Monti et al. 2026 (GeroScience, doi:10.1007/s11357-026-02174-2) harmonized the New England
Centenarian Study (NECS) metabolomics panel against four other aging cohorts in order to replicate
their findings. They report **coverage only**: how many metabolites overlapped. They report no
accuracy for any of those overlaps, because their method structurally cannot produce one. Matching
on names tells you two rows share a label; it cannot tell you they are the same molecule.

This is the general shape of the problem BioMapper addresses, in a setting where the consequence is
concrete: a wrong cross-cohort link silently merges two different molecules' effect estimates in a
replication analysis.

The comparison is worth running because it is **publicly reproducible end to end**. Both panels,
their harmonization code, and the adjudicating structures are open.

## 2. What is claimed

Two claims, one per cohort pair, each measured on identical rows against a reference linkage that
neither method can see.

| Pair | Their method | Their coverage | Our claim |
|---|---|---|---|
| NECS <-> Arivale | vendor `CHEMICAL_NAME` exact match | 615 of 766 (80%) | **precision**: name matching asserts links that are structurally wrong, and the vendor identifiers behind those names are not a safe fallback |
| NECS <-> LLFS | RefMet standardized-name join | 163 of 408 (40%) | **recall**: RefMet name standardization is a single-resolver bottleneck that silently discards what it cannot standardize |

### What is explicitly NOT claimed

- **Not** that BioMapper beats name matching on coverage for same-vendor panels. This was measured,
  not assumed: see section 3. The headroom is approximately zero and saying otherwise would be false.
- **Not** any adjudication of sum-composition lipid species. See section 7.
- Xu et al. is out of scope, so the 385-versus-432 contradiction in Monti's text stays unresolved.

## 3. Measured findings that shaped this design

These are already computed and pin the design. They are not assumptions.

### 3.1 Recall headroom over name matching on NECS <-> Arivale is approximately zero

Both panels are Metabolon, which is why Monti could use vendor names at all. Exact
case-insensitive name matching reaches 583 of 766 Arivale analytes. Adding matching on any shared
curated identifier (HMDB, KEGG, PubChem, CAS) brings in **2 more distinct Arivale analytes**.

The 43 extra pairs identifier matching does find are overwhelmingly isomer confusions, not synonym
recoveries. This is a lower bound (the probe only sees pairs sharing a namespace), but it is
sufficient to rule out a coverage claim on this pair.

### 3.2 The vendor's curated identifiers collide constitutional isomers, identically in both panels

Both panels inherit the same Metabolon annotation table, so they inherit the same errors:

| Colliding pair | Shared annotation, present in both panels | Distinct InChIKeys? |
|---|---|---|
| alanine / beta-alanine | CAS `56-41-7` | yes |
| cysteine / cystine | CAS `56-89-3` | yes |
| 1-methylhistidine / 3-methylhistidine | KEGG `C01152` | yes |
| o-cresol sulfate / p-cresol sulfate | HMDB `0011635` | yes |

`beta-alanine` ships carrying alanine's CAS; `cysteine` ships carrying cystine's CAS. A harmonizer
that "upgrades" from names to vendor identifiers therefore merges molecules that names kept apart.
This is the precision story, and it motivates arm M+ID (section 4).

### 3.3 The adjudication key must be block 1 plus the 8-character stereo hash

Every NECS gold InChIKey is **two blocks** (`14-10`), never the standard three (`14-10-1`).
Spermidine ships as `ATHGHQPFGPMSJY-UHFFFAOYAK` where the standard key is
`ATHGHQPFGPMSJY-UHFFFAOYSA-N`. A full-string match against any standard InChIKey would fail on
**every row**, because the trailing flag and version characters are a legacy encoding.

The 8-character stereo/isotope hash is byte-identical across the two formats and does carry
stereochemistry:

| Key | Distinct keys over 786 rows | Keys shared by more than one row |
|---|---|---|
| Block 1 only | 772 | **11** |
| Block 1 + 8-char stereo hash | 785 | **1** |

The 11 groups that block-1 matching silently merges are exactly the ones this domain must keep
apart: fumarate/maleate, myo-/chiro-inositol, lactose/maltose, cis/trans-urocanate, bilirubin
(Z,Z)/(E,E)/(E,Z), ursodeoxycholate/isoursodeoxycholate, threonate/erythronate. The stereo hash
separates 10 of the 11; gluconate/galactonate genuinely share a stereo hash and remain merged.

**Decision:** the adjudication key is `block1 + "-" + block2[:8]`, normalizing away trailing
flag/version/protonation characters on both sides. Block-1 matching is reported as a labelled
secondary metric for continuity with prior NECS numbers.

### 3.4 Most of a cross-vendor panel cannot be structurally adjudicated at all

BLSA's published analyte list (497 analytes, Tian et al. 2023) is **404 sum-composition lipid
species (81%)** and only **93 discrete molecules (19%)**. Names like `Triacylglyceride 14:0_36:2`,
`Phosphatidylcholine O-36:4`, and `Ceramide d18:2/23:0` denote a *set* of possible molecules, so no
structural oracle can adjudicate them.

This is why LLFS is the recall partner rather than BLSA, and it is a named, quantified finding in
its own right: structure-only validation of cross-vendor metabolomics harmonization is bounded to
the polar fraction. State the boundary; do not hide it.

### 3.5 LLFS clears the same gate that BLSA fails (measured 2026-08-04)

Run via `scripts/llfs_step1_sizing.py`, artifacts in `~/external_benchmark_runs/cohort_panels_20260804/`.

| | LLFS | BLSA |
|---|---|---|
| panel size | 408 | 497 |
| sum-composition / discrete | 190 / **218 (53%)** | 404 / 93 (19%) |
| overlap their method finds | 141 (they report 163) | 188 |
| **structurally adjudicable** | **111 of 141 (79%)** | 93 ceiling |

The 190/218 split lands within 2 of Monti's stated 188 lipid / 220 polar, so the panel parses
correctly. **111 is a floor**: the classifier flags any chain notation, which over-flags fully
specified species (`ACar 10:0` is decanoylcarnitine; `LPC 16:0/0:0` is 1-palmitoyl-GPC, both single
molecules). Refining the classifier during implementation can only raise it.

**The recall claim is now quantified at its source.** RefMet standardizes 364 of 408 LLFS names
(89%) but only **1,066 of 1,495 NECS names (71%)**. The 429 unstandardizable NECS names are
discarded by their `drop_na(refmet_name)` before any join occurs. That silent drop, not the join, is
the bottleneck.

**Reproduction gap:** we reproduce 141 of their 163. Lead on the remaining 22: their
`03.platform.mapping.llfs.Rmd` carries the comment `## mapping to refmet (mapping from original
names > mapping from standardized)`, implying a two-pass fallback we did not implement. Testable
during implementation; the reproduction guard in section 7 pins whichever value we land on.

## 4. Arms

Three arms per cohort pair, all scored on identical rows.

| Arm | Input to the method | Link asserted when |
|---|---|---|
| **B** baseline | panel names only | Arivale: vendor names match case-insensitively. LLFS: RefMet `name_to_refmet` returns the same standardized name, with unstandardizable names dropped, exactly as `03.platform.mapping.llfs.Rmd` does |
| **M** BioMapper | panel names only, for input parity with B | the two rows' predicted CURIE sets intersect |
| **M+ID** BioMapper | names plus vendor HMDB/KEGG/PubChem/CAS via `provided_id_columns` | same rule as M |

Arm M+ID exists to test section 3.2 directly: does BioMapper's resolution survive a poisoned
identifier, or inherit the collision? Both outcomes are informative.

**Arm M's linking rule is CURIE-set intersection, never structure.** This is forced, not chosen: if
the linking rule were structural identity and the adjudicator were also structural identity,
precision would be 100% by construction. This mirrors `scorers/metlinkr_scorer.py`.

## 5. Reference linkage and adjudication

Built from each panel's **own** identifiers, resolved outside the KG.

- **NECS side:** the curated `gold_inchikey` shipped in Monti's supplement, excluding the 10 known
  corrupt cells (`gold_inchikey == "4000"`, affecting salicylate, glycoursodeoxycholate, and 8
  others).
- **Arivale / LLFS side:** the panel's own registry identifiers resolved through PubChem PUG-REST
  via the existing `scorers/independent_inchikey.py`.
- A pair enters the reference linkage iff both sides yield an adjudication key (section 3.3) and the
  keys are equal.

**Adjudicable subset** = pairs where both sides yield a key. Precision and recall are computed only
inside it. Links asserted outside it are counted and reported as `unadjudicable`, never scored as
correct or incorrect. This is the `needs_verification` discipline already in `metlinkr_scorer.py`.

Two properties to keep on the record in the results text:

1. The reference is a relation, not a matching. After the stereo hash it is very nearly one-to-one
   (785 distinct keys over 786 rows), but the many-to-one rate is reported rather than assumed away.
2. **The reference is not complete.** A link falling outside it is not evidence of an error. This is
   why unadjudicable is its own bucket.

## 6. Metrics

Per arm, inside the adjudicable subset: **precision**, **recall**, **F1**.

Reported alongside, never folded in:

- asserted-but-unadjudicable count per arm
- the **reproduction check** of arm B against the published figure (ours 583 versus their 615 for
  Arivale; ours versus their 163 for LLFS)
- the unadjudicable fraction of each panel, with the sum-composition lipid count broken out

## 7. Guards, all fail-loud

| Guard | Behavior |
|---|---|
| **Reproduction** | arm B's count is pinned to the value our reimplementation is known to produce (583 for Arivale) and raises on any drift, so a changed source file or a changed matching rule is caught rather than absorbed. The gap to the published figure (583 versus 615) is *reported*, not asserted, because it is attributed to their documented manual name-curation step and is expected to be non-zero. |
| **Provided-ID plumbing** | if `chosen_kg_id_provided` is empty across all rows of arm M+ID, raise. This is the exact failure that produced a fictitious +0.6pt result on 2026-08-04 and propagated to four documents and the wiki before it was caught. |
| **Anti-trivial** | assert gold columns are present for the scorer and absent from BioMapper's input. |
| **Circularity** | assert the reference-side resolver is not the KG. |
| **Noise floor** | NECS shows roughly 1pt run-to-run variation on identical input. Every arm runs n=3; any delta smaller than the observed range is labelled as within noise. |
| **Unscorable** | zero adjudicable pairs raises rather than reporting a hollow rate. |

## 8. Data sources

| Source | What | License | Status |
|---|---|---|---|
| Monti et al. supplement | NECS panel, 1,495 rows (786 valid gold InChIKey, 10 corrupt, 699 absent) | published supplement | **in hand** |
| Watanabe et al. 2023, *Nat Med* 29:996-1008, Supp Data 2 (PMC10115644) | Arivale panel, 766 metabolites with CAS/KEGG/HMDB/PubChem | **CC BY** | **in hand**, SHA-pinnable |
| `montilab/monti_et_al_necs_metabolomics` v1.0.0, Zenodo 10.5281/zenodo.17107095 | their harmonization code, defines arm B exactly | public repo | **in hand** |
| Sebastiani et al. 2024, *Cell Rep* 43:114913 (PMC11656345), supplement 2 (`NIHMS2038904-supplement-2.xlsx`, the lab's `TableS1a_All_results_09.01.2023.xlsx`) | LLFS panel, 408 metabolites; sheet `annotation` also carries Monti's own precomputed RefMet standardized names, formula, exact mass, and class hierarchy | CC BY-NC-ND | **in hand**, sha256 `16492c59...b3767f57` |
| Metabolomics Workbench RefMet bulk name service (`name_to_refmet_new_min.php`) | arm B for LLFS; response columns match Monti's `annotation` sheet exactly, confirming it is the service their `refmet_convert` wraps | public service | verified working |
| Tian et al. 2023, *Metabolites* 13:591 (PMC10221446), Supp Table S2 | BLSA panel, 497 analytes | **CC BY** | in hand, used for the section 3.4 sizing |

All sources SHA-pinned in `config.py` with fail-loud mismatch, per the `metlinkr.py` pattern.

Note on CC BY-NC-ND for the LLFS table: we compute on it and cite it, and instruct readers to fetch
it from PMC rather than redistributing a modified copy.

## 9. Module layout

Approach: **one shared pair-scorer, thin per-panel loaders, per-pair config.** Both comparisons are
the same experiment with different panels and a different baseline function, so the scoring logic is
shared and the panel-specific parts stay small enough to test on in-memory fixtures.

```
studies/external_benchmarks/
  panels/
    arivale.py            # Watanabe Supp Data 2 -> panel frame (name + own ids), SHA-pinned
    llfs.py               # Cell Rep TableS1a    -> panel frame, SHA-pinned
    (necs_metabolon.py already exists and is reused unchanged)
  competitors/
    vendor_name_match.py  # arm B for Arivale: case-insensitive exact name join
    refmet_nameconvert.py # arm B for LLFS: RefMet name service client, rate-limited + cached,
                          #   fail-loud on outage (subclasses competitors/base.py)
  scorers/
    cohort_pair_scorer.py # reference linkage, adjudication key, P/R/F1, unadjudicable accounting
  config.py               # CohortPairConfig entries for (NECS, Arivale) and (NECS, LLFS)
```

Reused unchanged: `scorers/independent_inchikey.py` (non-circular gold resolution),
`competitors/base.py` (transport, cache, rate limit, retries), `adapters/necs_metabolon.py`,
`adapters/provided_id.py` (arm M+ID).

New tests are offline, on in-memory fixtures, per the existing suite's convention. No test hits a
live API.

## 10. Sequencing

**Step 1 was a gate, not code, and it PASSED on 2026-08-04.** See section 3.5: LLFS is 53% discrete
molecules and 111 of the 141 overlapping pairs are structurally adjudicable (79%), against BLSA's
19% ceiling. The recall arm is viable and the design proceeds unchanged.

The panel itself was captcha-walled: five automated routes failed (PMC `bin/` captcha, the OA
service's ftp path 404 over https, plain ftp refused, an empty Europe PMC `supplementaryFiles`
bundle, and a 404 from the S3 open-data `author_manuscript` mirror). It was retrieved by hand from
PMC to `data/NIHMS2038904-supplement-2.xlsx`, which is **gitignored**: the file is CC BY-NC-ND and
we do not redistribute it. Its sha256 is pinned in `config.py` and verified fail-loud on load, the
same posture the harness takes for other externally-sourced tables.

Subsequent steps:

2. Panel loaders plus offline tests, both panels SHA-pinned.
3. Arm B for Arivale, with the reproduction guard against 615.
4. `cohort_pair_scorer.py` plus offline tests, including a deliberately circular fixture that must raise.
5. Arms M and M+ID on NECS <-> Arivale; n=3 for the noise floor.
6. Arm B for LLFS (RefMet client), with the reproduction guard against 163.
7. Arms M and M+ID on NECS <-> LLFS.
8. Results assembly and figures.

## 11. Risks

| Risk | Mitigation |
|---|---|
| ~~LLFS panel unobtainable~~ | **Retired 2026-08-04**: retrieved by hand and SHA-pinned in `data/`. |
| ~~LLFS adjudicable subset too small~~ | **Retired 2026-08-04**: 111 of 141 adjudicable (79%). See section 3.5. |
| Sum-composition classifier over-flags fully specified species | It currently flags any chain notation, so `ACar 10:0` and `LPC 16:0/0:0` are wrongly excluded. This makes 111 a floor, so it cannot inflate a result, but refining it during implementation is a tracked task. |
| Our arm B reproduces 141, not their 163 | Pinned and reported, never silently absorbed. Their two-pass RefMet fallback is the leading hypothesis for the gap and is testable. |
| RefMet name service unavailable or rate-limited | `competitors/base.py` already caches, rate-limits, retries, and fails loud rather than scoring an outage as 0% coverage. |
| Arm M+ID inherits the isomer collisions | This is a result, not a failure. Report it either way. |
| Reference linkage incompleteness read as precision error | Enforced by the `unadjudicable` bucket and stated in the results text. |

## 12. Delivery

Code plus offline tests open as a PR on the personal fork `trentleslie/biomapper2` against `dev`
for Greptile review first, then Phenome-Health. This diff carries real logic and data-mutation
paths, so it merits a review credit.

Run artifacts land in `~/external_benchmark_runs/<run>/` by default with a `PROVENANCE.md` pinning
source SHAs, seeds, and config, per the artifact-hygiene SOP. Saving is never behind a flag.
