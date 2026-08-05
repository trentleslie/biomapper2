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

**Read section 1b before writing anything. The obvious version of this claim is prior art.**

> Commercial metabolomics annotation deliverables carry structurally wrong identifiers at a rate
> consistent with what is already published for public databases, but unlike public resources they
> **drift between vintages**, and a cohort study permanently inherits whichever vintage it was
> delivered. Because benchmark ground truth is built from that snapshot, a measurable share of what
> any benchmark reports as resolver error is ground-truth error instead. Detecting this requires two
> independent measurements of the same entity plus a third adjudicator, which standard
> entity-resolution benchmarking does not have and cross-cohort harmonization supplies for free.

Note what it is *not*: it is not a claim that BioMapper outperforms anything. The paper's applied
contribution should not depend on the sign of any head-to-head delta, because every head-to-head we
attempted came back null or unmeasurable.

## 1b. PRIOR ART: do not claim novelty on the error rate

The general finding was published in 2014 and we independently rediscovered it.

- **Akhondi et al. 2014, "On InChI and evaluating the quality of cross-reference links" (PMC4005828).**
  Manually curated cross-references between ChEBI, DrugBank, PDBeChem, HMDB and NPC show
  **connectivity-level inconsistency of 0.59% to 3.25%**. They use the same connectivity-versus-
  stereochemistry decomposition and reach the same conclusion: raw disagreement is dominated by
  stereochemistry, connectivity-level runs about 1 to 3%.
- **Metabolomics 2026;22:28 (PMC12923498), "Metabolite names and identifiers: how far are we from
  interoperability?"** HMDB to ChEBI 4% mismatch, HMDB to PubChem 1.7%, HMDB to KNApSAcK 65%. Also
  splits molecular skeleton from stereochemistry. Tested six conversion tools at three timepoints.

**Our measured 0.92% to 1.66% sits inside Akhondi's published range.** Cite both papers, present our
rate as *consistent with* the literature, and do not present it as a discovery.

What those papers explicitly do **not** cover, and what is therefore ours to claim:

1. **Commercial vendor deliverables.** The 2026 paper states it evaluates only public databases and
   open-source tools, with no evaluation of Metabolon, Biocrates, or other commercial platforms. The
   annotation table a cohort actually scores against is a vendor deliverable, not HMDB.
2. **Vintage drift, which points opposite to the public-resource result.** The 2026 paper tested its
   tools in April 2024, July 2024 and August 2025 and found results "strictly identical." Metabolon
   deliverables are not stable: **all 8 replicated wrong values sit in the 2019 annotation file, and
   later Metabolon releases carry the correct value for 6 of the 8.** Metabolon documents that it
   continually updates annotations while holding the chemical ID stable, so a study inherits whichever
   vintage it was delivered and nothing records which.
3. **Downstream contamination of benchmark ground truth**, quantified. See section 4.

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

### The vintage direction, which is the part that is actually new

For the 8 compounds replicated across metLinkR's supplementary panels, the wrong value is **entirely
concentrated in the 2019 Metabolon annotation file**:

| Panel | correct | wrong |
|---|---|---|
| `2019_Metabolon_Metadata.csv` | 0 | **8** |
| `LEOCC_Metabolon_Annotations.csv` | 6 | 1 |
| `Metabolon_Annotations_Serum_hmdbformatted.csv` | 6 | 1 |
| `Broad_2022Aug_annotations.csv` | 2 | 0 |

So the vendor **corrects** these over time. The claim is therefore **not** that Metabolon annotations
are unreliable at 1%. It is that **annotation vintage determines a study's error rate, studies are
scored against whatever snapshot they were delivered, and that snapshot is not recorded anywhere.**
NECS sits on a vintage carrying the 2019-era errors.

`xylose` is the exception and the one standing defect worth reporting upstream: wrong in all three
Metabolon files, correct in Broad.

### The vintage is unrecorded but RECOVERABLE, which is the practical contribution

There is no version field anywhere. Metabolon's deliverable schema has `CHEM_ID`, `LIB_ID` and
`CHRO_LIB_ENTRY_ID`, but `LIB_ID` takes only 4 distinct values across 1,546 rows (the four
chromatography methods, not a release) and `CHRO_LIB_ENTRY_ID` is per-compound. Monti's paper records
no annotation version or delivery date. So no published study can state which annotation it inherited.

The differences between vintages are themselves a signature, so the vintage can be recovered after
the fact. Matching NECS's 786 gold InChIKeys against dated reference panels, over **all** shared
compounds rather than the 8 known defects:

| Reference panel | shared | agreement |
|---|---|---|
| **`2019_Metabolon_Metadata.csv`** | 650 | **100.0%** (0 disagreements) |
| `LEOCC_Metabolon_Annotations.csv` | 704 | 98.6% |
| `Metabolon_Annotations_Serum_hmdbformatted.csv` | 704 | 98.6% |
| `Broad_2022Aug_annotations.csv` | 79 | 97.5% |

**NECS was delivered the 2019 vintage.** Determined with no version field, no vendor cooperation, and
no input from the authors, using only public supplementary data.

This is the most actionable thing in the paper: a published cohort study's annotation vintage, and
therefore the specific errors it inherited, is recoverable from its own supplement. Recommend it as
a routine check, and recommend that vendors and journals record the vintage so it does not have to be.

Script: `scripts/fingerprint_annotation_vintage.py`.

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

- **Do not claim the error rate as a discovery.** It is prior art (Akhondi et al. 2014, 0.59% to
  3.25% connectivity-level; Metabolomics 2026;22:28). Cite both, present our 0.9% to 1.7% as
  consistent with them, and claim novelty only on the vendor-deliverable setting, the vintage drift,
  and the benchmark-contamination consequence. See section 1b.
- **Do not say "Metabolon annotations are 1% wrong."** The wrong values are concentrated in the 2019
  vintage and later releases fix most of them. The correct statement is about vintage drift and the
  absence of any provenance record of which snapshot a study used.
- **Do not say "curated databases are 1% wrong"** as a general claim either. Say: measured across
  four comparisons spanning cohort panels from Metabolon, Broad, and the COMETS consortium,
  connectivity-level disagreement runs roughly 0.9% to 1.7%, consistent with published rates. The
  Broad-vs-Metabolon comparison shows the phenomenon is not unique to one vendor but does not by
  itself say which side is wrong.
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
| **Akhondi et al. 2014, PMC4005828** | **prior art on the error rate; cite, do not rediscover** | open access |
| **Metabolomics 2026;22:28, PMC12923498, doi 10.1007/s11306-026-02404-w** | **prior art; public-database mismatch rates and tool stability** | open access |
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
