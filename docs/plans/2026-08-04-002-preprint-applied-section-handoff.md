# Handoff: what the BioMapper preprint's applied section should claim

**Date:** 2026-08-04
**Audience:** the agent drafting the BioMapper preprint's applied/results section
**Status:** evidence complete, ready to write. No further runs required for the core claims.
**Repo:** biomapper2, branch `feat/cross-cohort-harmonization-benchmark`
**Artifacts:** `~/external_benchmark_runs/cohort_panels_20260804/`

---

## 0. Read this first: the claim changed twice on 2026-08-04

This document supersedes two earlier positions taken the same day. Both were wrong and the record
matters, because the second reversal is what licenses the strongest claim in the paper.

1. **Original plan:** a head-to-head benchmark showing BioMapper beats published harmonization
   methods on coverage and precision. **Dead.** Every comparative claim was withdrawn after
   measurement. See section 5.
2. **Interim position:** the ground-truth-defect finding is real but panel-specific, so claim only
   the mechanism and the method, no rate. **Superseded.** A fourth test replicated the defect at
   compound level on independent data. See section 2.

**Write to this document, not to earlier notes.**

---

## 1. The headline claim

> Curated metabolite annotation tables assign structurally wrong identifiers at roughly 1% of
> entries. The errors are well-formed, invisible to standard validation, and propagate identically
> into every cohort inheriting the annotation. Detecting them requires two independent measurements
> of the same entity plus a third adjudicator, which is apparatus that standard entity-resolution
> benchmarking does not have and cross-cohort harmonization supplies for free.

Everything below supports that sentence. Note what it is *not*: it is not a claim that BioMapper
outperforms anything. The paper's applied contribution should not depend on the sign of any
head-to-head delta, because every head-to-head we attempted came back null or unmeasurable.

---

## 2. Evidence for the rate (four independent estimates)

All figures are **connectivity-level** disagreement: the two sources assign InChIKeys with different
first blocks, meaning different molecules, not different stereochemistry or charge states.

| Comparison | What is independent about it | Rate |
|---|---|---|
| NECS vs Arivale, adjudicated by PubChem name lookup | two cohort panels + a third path; each defect has two confirmations | 9/562 = **1.60%** |
| Broad vs Metabolon (metLinkR SI raw input panels) | different curating organizations, InChIKeys on both sides, nothing reconciled | 4/241 = **1.66%** |
| Metabolon vs Metabolon (different annotation snapshots) | same vendor, different releases; measures internal inconsistency | 24/2600 = **0.92%** |
| COMETS curator groups spanning 2+ cohort datasets | expert linkage independent of the identifiers | 2/208 = **0.96%** |

Report the range (**roughly 0.9% to 1.7%**), not a point estimate. The Wilson intervals are wide
(NECS 9/562 is [0.84%, 3.02%]) and the four designs are not measuring exactly the same population.

### The compound-level replication is the strongest evidence, stronger than the rate

**8 of the 13 connectivity disagreements found in metLinkR's supplementary input panels are the same
compounds carrying the same wrong values as the NECS gold defects**, established independently from a
different paper's supplement:

`cortisone`, `fructose`, `gamma-glutamylvaline`, `glucuronate`, `n-acetylneuraminate`,
`n1-methyladenosine`, `pseudouridine`, `xylose`.

A rate can be argued with. A named compound carrying a specific wrong InChIKey in two unrelated
publications' supplementary data cannot.

### The mechanism, caught directly

`xylose` disagrees `PYMYPHUHKUWMLA` versus `SRBFZHDQGSBBOR`. `arabinose` disagrees on **the same two
keys, reversed**. The InChIKeys are swapped between two isomeric sugars. `mannose` shows the same
shape (`GZCGUPFRVQAUEE` vs `WQZGKKKJIJFFOK`).

This is the most quotable finding in the paper. It is not a typo or a missing value; it is a
row-level assignment swap between chemically adjacent species, which is exactly the class of error
that survives every format check and is invisible to any single-source audit.

---

## 3. Named examples to use in the text

Nineteen NECS gold defects were established with two independent confirmations each. Use these:

| Compound | Assigned (wrong) | Correct |
|---|---|---|
| choline | `CRBHXDCYXIISFC` | `OEYIOHPDSNJKLS` |
| xylose | `PYMYPHUHKUWMLA` | `SRBFZHDQGSBBOR` |
| pseudouridine | `HZIOZCLEXIYJAD` | `PTJWIQPHWPFNBW` |
| cortisone | `IWIJFUQFXLWZIA` | `MFYSYFVPBJMHGN` |
| glucuronate | `IAJILQKETJEXLJ` | `AEMOLEFTQBMNLQ` |
| n-acetylneuraminate | `KBGAYAKRZNYFFG` | `SQVRNKJHWKZAKO` |
| n1-methyladenosine | `QQBGTSSELNKRID` | `GFYLSDSUCHVORB` |
| gamma-glutamylvaline | `SITLTJHOQZFJGG` | `AQAKHZVPOOGUCK` |
| fructose | `BJHIKXHVCXFQLS` | `LKDRXBCSQODPBY` |

`choline` is the best single example for a reader: `CRBHXDCYXIISFC` is a perfectly valid InChIKey and
simply is not choline.

Full list: `conflict_adjudication.csv`, `necs_miss_adjudication.csv`.

---

## 4. The consequence for benchmarking, with numbers

On the NECS benchmark, scored against that annotation:

| Metric | As scored | Gold-corrected |
|---|---|---|
| Strict | 609/796 = 76.5% | **626/796 = 78.6%** |
| Equivalence-set | 662/796 = 83.2% | **679/796 = 85.3%** |

**17 of 136 adjudicable misses (12%) were the resolver being right and the ground truth being wrong.**

Two things must be stated alongside these:

- **Both figures are floors.** 39 misses could not be resolved by name.
- **The bias runs both ways and only one direction is observable.** A wrong gold produces false
  debits (resolver right, scored wrong), which this method catches, and false credits (resolver and
  gold wrong the same way), which it cannot. So the honest claim is **"the reported accuracy is wrong
  in an unknown direction and we can bound only one side"**, not "accuracy was understated by 2.1
  points." Do not overstate this; the weaker phrasing is the defensible one.

Operational consequence worth one sentence: of 17 rows routed to expert review as chemically
ambiguous, **10 (59%) were bad ground truth rather than hard chemistry**.

---

## 5. What was tried and withdrawn (report this; do not hide it)

Four comparative claims were attempted and all four failed on measurement. Reporting them is what
makes section 4 credible rather than self-serving.

| Claim | Outcome | Why |
|---|---|---|
| BioMapper beats vendor-name matching on **coverage** (NECS/Arivale) | withdrawn | name matching reaches 583 of 766 Arivale analytes; identifier matching adds **2** |
| BioMapper beats vendor-name matching on **precision** | withdrawn | after removing the 9 gold defects, the baseline errs **once in 562** (99.8%). No headroom, one discordant pair |
| BioMapper beats RefMet-join on **accuracy** (NECS/LLFS) | withdrawn | LLFS ships no identifiers, and only 21 of the discarded rows carry a gold structure |
| BioMapper beats RefMet-join on **coverage** | reported, bounded | see below |

The one surviving comparative result, stated with its limits:

> RefMet standardization discards 429 of 1,495 NECS names before any join can occur. 282 are unnamed
> feature codes nobody could map, leaving **147 named metabolites** the method drops. BioMapper
> resolves **83 of the 147 (56%)** to structure-bearing entities, against 91% on the names RefMet can
> standardize. On the 21 discards carrying independent structure, 15 resolved and **9 are correct
> (60%)**.

A methodological caution that belongs in the text: a naive coverage measure would have reported
**100%**, because `chosen_kg_id` is non-empty on all 1,495 rows and 172 collapse onto a single
catch-all node. Counting only structure-bearing, non-degenerate resolutions drops unmappable feature
codes to 1%, which is the correct behavior. This is worth a sentence because it is the same class of
error as the paper's main finding, committed by the measurement rather than the data.

---

## 6. The framing that ties it together

The applied section should argue this progression:

1. Cross-cohort harmonization is normally presented as an application of entity resolution.
2. It is also the only routinely available setting that supplies **two independent measurements of
   the same molecule**, which is the minimum apparatus for auditing an entity resolver at all.
3. Using it that way, the annotation substrate everyone benchmarks against turns out to carry
   structurally wrong identifiers at roughly 1%, propagating across cohorts.
4. Therefore published accuracy figures in this space, including ours, are wrong in an unknown
   direction, and every error analysis built on a single curated column is partly contaminated.
5. **Harmonization is not just an application of BioMapper; it is the apparatus that makes entity
   resolution auditable.**

Point 5 is the thesis sentence. It is true regardless of any score, which is why the section should
lead with it.

### Why this is defensible under review

- No claim depends on BioMapper winning a comparison.
- The central finding has four independent rate estimates and a compound-level replication.
- The withdrawn claims are reported, which pre-empts the "you only show what flatters you" objection.
- A reviewer attacking the core finding has to argue that choline's InChIKey is `CRBHXDCYXIISFC`.

---

## 7. Scope limits: do not overclaim

- **Do not say "curated databases are 1% wrong."** Say: measured across four comparisons spanning
  cohort panels from Metabolon, Broad, and the COMETS consortium, connectivity-level disagreement runs
  roughly 0.9% to 1.7%. Most of the evidence concerns the **Metabolon annotation lineage**, which is
  widely inherited; the Broad-vs-Metabolon comparison shows it is not unique to one vendor but does
  not by itself say which side is wrong.
- **Do not report raw disagreement rates.** They are dominated by artifacts. Cross-vendor raw
  disagreement is 28.6%, but almost all of it is stereo-specification depth (`lactate` as
  `JVTAAEKCZFNVCJ-REOHCLBH` versus `JVTAAEKCZFNVCJ-UHFFFAOY`: same connectivity, one curator
  recording stereochemistry and the other not). Report connectivity-level only, and say why.
- **Do not use SRM1950 as support.** Tested and inconclusive: raw 19.7% collapsed to ~1 defensible
  candidate once inorganic ion-versus-neutral-atom conventions were stripped. One real candidate
  remains (`7-Ketolithocholic acid` carries what PubChem returns for `7-Ketodeoxycholic acid`), worth
  a footnote at most.
- **Do not present the 12% as a field number.** It is P(gold wrong | resolver disagreed), so it has
  BioMapper in its denominator. The field-level number is the ~1% base rate.
- **Do not claim accuracy was understated.** See section 4 on bidirectional bias.

---

## 8. Provenance

Everything is reproducible from public sources.

| Source | Use | License |
|---|---|---|
| Monti et al. 2026, GeroScience, doi 10.1007/s11357-026-02174-2 | NECS panel, the methods reproduced | published supplement |
| Watanabe et al. 2023, Nat Med 29:996-1008, PMC10115644, Supp Data 2 | Arivale panel, 766 metabolites | **CC BY** |
| Sebastiani et al. 2024, Cell Rep 43:114913, PMC11656345, supplement 2 | LLFS panel, 408 metabolites | CC BY-NC-ND, not redistributed |
| Patt et al. 2025 metLinkR SI, PMC12053952, `pr4c01051_si_001.zip` | raw input annotation panels, the cross-vendor replication | see repo config |
| Tian et al. 2023, Metabolites 13:591, PMC10221446 | BLSA panel, adjudicability ceiling | **CC BY** |
| PubChem PUG-REST | the third adjudication path | public |

**Scripts** (branch `feat/cross-cohort-harmonization-benchmark`):
`scripts/adjudicate_conflicts.py`, `scripts/adjudicate_necs_misses.py`,
`scripts/metlinkr_multipanel_gold_test.py`, `scripts/comets_gold_screen.py`,
`scripts/srm1950_gold_check.py`, `scripts/llfs_coverage_arm.py`, `scripts/llfs_step1_sizing.py`.

**Result documents:** `UNIT0_GATE_RESULT.md`, `NECS_MISS_ADJUDICATION.md`,
`SRM1950_GENERALITY_TEST.md`, `COMETS_FIELD_TEST.md`, `metlinkr_multipanel_gold_test.json`, all in
`~/external_benchmark_runs/cohort_panels_20260804/`.

Note that `SRM1950_GENERALITY_TEST.md` and `COMETS_FIELD_TEST.md` both conclude "not established."
Those conclusions were drawn before the metLinkR raw-panel test and are superseded by it. The
documents are kept because their confound analyses (ion conventions, curator pre-reconciliation) are
what forced the connectivity-level split that made the final result correct.

---

## 9. Open items

- **The xylose/arabinose swap should be reported upstream** to Metabolon, along with the other 18
  defects. Worth a sentence in the paper noting it was reported.
- **Which side is wrong in Broad-vs-Metabolon disagreements** is not established for the 4 cross-vendor
  cases individually. The 8 compound-level replications are adjudicated; those 4 are not. Either
  adjudicate them by the third path or describe them as disagreements rather than as Metabolon errors.
- **The 7-ketolithocholic acid candidate in SRM1950** looks like a genuine NIST error and is unchased.
- **The `EFO:`/`LOINC:` nodes returned despite `category_filter: biolink:SmallMolecule`** is unresolved
  from the earlier NECS work and should not appear in the paper until it is.
