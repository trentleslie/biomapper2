---
date: 2026-08-22
topic: cross-cohort-eitl-campaign
---

# Cross-Cohort Harmonization Benchmark + Expert-in-the-Loop Adjudication Campaign

> **Revision note (2026-08-22):** persona review applied, then three of its seven blockers resolved.
> The adjudication protocol has been reshaped to run on the expert-in-the-loop app **as deployed,
> with configuration only and no code changes** — verified against the running source. Remaining
> decisions are under *Outstanding Questions → Resolve Before Planning*.

## Problem Frame

Monti et al. 2026 (GeroScience, doi:10.1007/s11357-026-02174-2) harmonized the New England
Centenarian Study metabolomics panel against four other cohorts and published the resulting overlap
counts. Their method is name-based and, for two of the four pairs, explicitly hand-curated ("After
name curation, 615 metabolites were matched"). They report **coverage only** — how many metabolites
overlapped — and no accuracy, because name matching structurally cannot produce one. A wrong
cross-cohort link silently merges two different molecules' effect estimates in a replication
analysis.

This is the applied use case for the BioMapper preprint, whose spine is *a structural certificate
issued for a name-input resolution, plus refusal when one cannot be issued.*

## Narrative Spine

The comparison is told in four beats, each deeper than the last. Coverage is the on-ramp, not the
claim; the claim is structural certification; the punchline is that even expert-curated ground truth
carries structural contradictions.

1. **Coverage / overlap — the shared language.** Monti reported overlap counts, and every reader of
   that paper thinks in them. BioMapper reproduces the overlap picture **automatically**, with none of
   the manual name curation Monti's method required. On same-vendor pairs (Arivale, Xu — both
   Metabolon) name matching already reaches ~98%, so the honest statement is *parity, achieved
   without hand curation*; on cross-platform pairs (LLFS, BLSA) BioMapper *recovers* overlap the
   name-based method silently drops when RefMet cannot standardize a name. Accessible, non-threatening,
   establishes common ground.
2. **The turn: coverage is not correctness.** Two names can "match" and denote different molecules; a
   name can fail to match and denote the same one. Coverage cannot tell these apart — by construction,
   which is why Monti reported no accuracy. This is where the familiar metric runs out.
3. **Structural certification — the contribution.** BioMapper resolves a name to a structure and
   issues a certificate, or refuses when it cannot. Now the overlaps can be *graded*, not just counted.
   This is the paper's spine: *a structural certificate issued for a name-input resolution, plus
   refusal when one cannot be issued.* UniChem is the prior art for structural cross-referencing but
   cannot start from a name and never declines.
4. **The deepest cut: the curated ground truth itself is structurally self-contradictory.** The NECS
   annotation ships **two InChIKey columns that disagree on 48 of 691 rows** (see Disagreement
   Provenance), and the existing benchmark scores against the wrong one. Name-based curation cannot
   detect this; a structural check does. So "expert-curated gold" is not a fixed floor — it needs the
   same structural lens, and demonstrating that on Monti's own data is the strongest evidence for the
   approach. This beat lands last because it is the most convincing.

**Why coverage is the opening and not the claim.** Beating a hand-curated coverage number, on its own,
invites the obvious objection "you made your matcher more permissive," and coverage alone reproduces
exactly the limitation being criticised. So coverage earns attention and establishes parity, then
beats 2–4 carry the actual contribution. Expert adjudication is what converts the graded overlaps into
a precision claim on **both** arms, and is therefore load-bearing rather than an add-on.

**The two deliverables map onto the arc.** Beat 1 is the Deliverable 2 four-cohort overlap comparison
(the metabolite spreadsheet). Beats 2–4 are the structural through-line that Deliverable 1's gold
repair and exemplar set anchor — beat 4 *is* the Deliverable 1 work, and it is the deepest, last, and
most convincing evidence, which is part of why Deliverable 1 ships first and stands on its own.

## Glossary

Terms used with a fixed meaning throughout, because reviewers found each of them ambiguous:

- **Link** — an asserted correspondence between one NECS panel row and one other-cohort panel row.
- **Arm** — one of the three methods producing links: **B** (Monti's published per-pair method,
  reconstructed), **M** (BioMapper, names only), **M+ID** (BioMapper plus vendor identifiers).
- **Proposing arm** — the arm that asserted the link under adjudication.
- **CURIE-set intersection** — set-theoretic intersection of the CURIE sets the two panel rows
  resolve to. A link is asserted when the intersection is non-empty.
- **Baseline** — arm B, always. Never the repaired gold and never BioMapper.
- **Independent oracle** — structures derived from **each cohort's own vendor annotation**
  (SMILES/InChI), standardized locally, never from the KG node that produced a CURIE intersection.

## Deliverables

This ships as **two independent deliverables**, decided 2026-08-22. Group A is small, self-contained,
independently valuable, and its outcome partly determines whether Deliverable 2's central claim is
even available (R4a). Bundling them would gate a low-risk fix behind a large contingent effort.

**Deliverable 1 — Gold repair and the exemplar set (Group A).** Ships on its own. Needs no live
BioMapper run, no expert campaign, and no external data. Produces: a repaired NECS gold column with a
per-row provenance record, a classified defect taxonomy over the 48 contradictory rows, the re-scored
NECS benchmark, the recomputed Unit 0 verdict, and the publishable exemplar set (R22a). **This is the
current planning scope.**

**Deliverable 2 — The harmonization benchmark and EITL campaign (Groups B-E).** Gated on Deliverable
1 landing and on R4a's verdict. Requirements are specified here so the design is settled, but
planning and execution follow Deliverable 1.

## Requirements

**A. Repair the measuring instrument — DELIVERABLE 1**

- **R0.** Recover the stranded prior branch before anything else. The Unit 0 sizing gate
  (`scripts/llfs_step1_sizing.py`), the NECS miss adjudicator (`scripts/adjudicate_necs_misses.py`)
  and the 2026-08-04 design and plan documents exist only on
  `feat/cross-cohort-harmonization-benchmark`, whose remote was deleted. Push that branch and merge
  or cherry-pick what R3/R4 need. Until this is done, R3 and R4 cannot start.
- **R1.** Classify each of the 48 disagreeing rows **first**, using the annotation's own `SMILES` and
  `formula` columns rather than a key-to-key comparison, into: genuine wrong-molecule defect,
  tautomer/protonation encoding difference, stereochemistry-only difference, or undecidable. The
  InChIKey first block is not invariant to ring-chain tautomerism or protonation, so a key comparison
  cannot make this call.
- **R2.** Rebuild the NECS gold structure column **as a per-row consequence of R1's classification**,
  recording the rule applied to each row. Column precedence must not be fixed globally in advance:
  format modernity is not evidence of chemical correctness, and a re-annotation pass that produced
  the standard-form column could equally have introduced errors.
- **R2a.** Distinguish *derivation* from *verification*. Derivation stays offline and single-file.
  Verification may make a one-time, cached, pinned resolution of vendor SMILES to standard InChIKeys
  on a held-out sample, used solely to check R2's precedence rule. Forbidding all external calls
  would make the repair unfalsifiable.
- **R3.** Re-score the existing NECS benchmark results against the repaired gold and report how the
  headline accuracy and the 134-miss disposition move. Some existing "misses" are expected to become
  correct.
- **R4.** Re-compute the 2026-08-04 Unit 0 sizing gate against the repaired gold, reporting the
  verdict under **both** the repaired and the original gold, and state plainly whether the withdrawn
  Arivale precision claim revives or stays withdrawn.
- **R4a.** If R4 finds the precision claim stays withdrawn, groups B–E proceed as a
  coverage-plus-refusal deliverable only; the precision-claim language in Success Criteria and R22 is
  deferred rather than pursued against the current gold.

**B. Harmonize the four cohorts with BioMapper — DELIVERABLE 2**

- **R5.** Resolve each cohort panel's names to CURIE sets with BioMapper, in the three arms defined
  in the Glossary, scored on identical rows.
- **R6.** Arm M's linking rule is CURIE-set intersection and must never be structural identity. If
  the linking rule and the adjudicator were both structural identity, precision would be 100% by
  construction.
- **R6a.** **The adjudicating structures must come from the independent oracle, not from the KG.**
  If a link is asserted because two names resolved to the same KG node, and the certificate then
  compares that node's structure against itself, certification is tautological — the same retrieval
  that produced the link produces the evidence confirming it. R1 already sets the correct standard
  (vendor SMILES and formula); the campaign must use the same standard.
- **R6b.** Persist the provenance of each compared key (vendor annotation column vs KG node). Any
  link whose two compared keys trace to the same KG node is reported separately as **self-certified**
  and excluded from the certified count.
- **R7.** For every asserted link, emit the structural certificate verdict *and* the compared keys,
  persisted rather than discarded. Refusal is a first-class outcome and must be distinguishable from
  "confirmed identical" and from "never checked".
- **R7a.** Define the link-level verdict state table. A certificate is issued per *resolution*, so a
  link has two. The composition rule for present+absent, corroborated+contradicted, and
  lookup-failed+present must be specified before R8's counts mean anything.
- **R8.** Report three numbers per pair, never coverage alone: links asserted, links certified, links
  refused.
- **R8a.** Report **both** refusal-sensitive metrics, because they answer different objections:
  1. **Certified-correct links at a fixed refusal budget** — a single scalar, directly comparable
     across pairs and against the baseline, in which refusing more cannot improve the score.
  2. **A coverage-precision curve with the operating point marked** — shows the whole tradeoff rather
     than one chosen point, and pre-empts "you picked the threshold that flattered you."
  Precision alone rises monotonically with refusal rate, BioMapper controls its own refusal
  threshold, and the baseline has no refusal concept at all — so precision-versus-Monti otherwise
  compares BioMapper after discarding its hard cases against Monti on everything Monti asserted.
- **R8b.** Freeze and hash-pin the refusal threshold and certificate strictness **before the first
  vote is cast**. Any later change is reported as a separate sensitivity run, never as a replacement
  for the primary number.
- **R9.** Exclude the 282 vendor-flagged `UNNAMED` features (`TYPE = UNNAMED`, names of the form
  `x-#####`) from every denominator, and state the exclusion. No tool can resolve a mass-spec peak
  with no proposed structure. State the analogous exclusion for each other panel, or state that none
  applies, so denominators are comparable across arms.

**C. Build the review queue**

- **R10.** Build the queue on BioMapper's **three-valued** output — certified / asserted-but-refused
  / not linked — crossed with the baseline's binary linked/not, rather than flattening BioMapper to
  binary. The most spine-relevant item the campaign can produce is a link *both* methods asserted
  where the structures are not the same molecule: a silent cross-cohort merge caught by refusal. A
  binary 2×2 buries those in the agreement cell.
- **R10a.** Both disagreement cells enter the queue. The agreement cells contribute a control sample.
  Report the human review load per cell, so any asymmetry in scrutiny between arms is visible in the
  artifact rather than hidden in the design.
- **R11.** Triage with the certificate first. Items the certificate can decide are auto-resolved.
  Only refusals, certificate-versus-baseline contradictions, the control sample and the audit sample
  (R11a) are queued.
- **R11a.** **Audit the auto-resolved population.** A random, pre-specified fraction (proposed: 10%,
  minimum 50 items per pair) of certificate-auto-resolved links is injected into the human queue
  indistinguishably from queued items, and the measured auto-resolution error rate is reported
  alongside asserted/certified/refused. Without this the design audits the machine only where it
  declines, and BioMapper's wins are graded by BioMapper while the baseline's wins are graded by
  humans.
- **R11b.** **Seed known-answer controls.** Inject a pre-specified number of synthetic items per
  pair, comprising known-wrong BioMapper-style links (including a same-node self-certification case
  and a stereoisomer-swap case) and known-correct baseline links, indistinguishable in the queue.
  Report detection rate on seeds as a published precondition; if the pipeline fails to surface
  planted BioMapper errors, the precision figures are not reportable. Every guard in this design
  needs a positive control proving it can fire.
- **R11c.** Run certificate triage across all four pairs and report total queue size **before**
  opening the campaign. If it exceeds stated per-reviewer capacity for the campaign window, apply
  stratified sampling before launch, never after — sampling introduced mid-campaign changes the
  denominator of every precision figure in flight.
- **R12.** Report the queue size as a finding in its own right — it measures how often the machine
  declined — not merely as an operational number.
- **R13.** Export queued items into the expert-in-the-loop application's `pairs` model.
- **R13a.** Votes return via a **read-only SQL query against the application's Postgres**, not via
  its HTTP export. The `/export` endpoint emits whole-campaign aggregate rows with no per-reviewer or
  per-vote breakdown and so cannot support R17 or R20; the underlying `votes` table has everything
  needed. The database runs on the same host as the app, so this is an operator step requiring no
  application change. Persist the extracted votes to a timestamped artifact per R23.
- **R14.** Items that are structurally unadjudicable by construction — principally BLSA's
  sum-composition lipid species, which name a *set* of molecules — must be labelled as such before
  queueing and counted as refusals rather than consuming expert time on an impossible judgement. The
  classifier must be validated against known fully-specified species (`ACar 10:0` is
  decanoylcarnitine, a single molecule); the prior chain-notation regex over-flagged these, and
  over-flagging silently converts adjudicable items into refusals in the direction that flatters the
  system under test.
- **R14a.** Define the export representation for refusals, which by definition have no committed
  target CURIE, given that the destination schema requires non-null target fields. Placeholder target
  values must never render to an expert as if they were a real candidate.

**D. Campaign protocol**

- **R15.** Adjudication is two-stage, implemented as **two campaigns, not two UI stages**. The same
  logical item is exported twice: once into a blinded campaign, once into a revealed campaign, as
  distinct `pairs` rows. This is what makes the protocol fit the deployed app — the queue server
  deliberately never re-serves a pair a reviewer has already voted on, so a second stage on the
  *same* row is unreachable, but a new row in a second campaign is served normally.
- **R15a.** **Blinding is an export-time property, not a UI feature.** Blinded-campaign pairs carry
  only cohort-side evidence in `sourceMetadata`/`targetMetadata` — names, SMILES, formula, vendor
  IDs, rendered structures — and leave `llmConfidence`, `llmModel` and `llmReasoning` NULL. Revealed
  campaign pairs carry the arm, CURIEs, compared keys, certificate verdict and reasoning. Nothing
  depends on a display toggle, so nothing leaks through one being misconfigured.
- **R15b.** The evidence panel must be identical in fields and formatting across items regardless of
  proposing arm. Otherwise a BioMapper-proposed item carries a visible fingerprint the baseline items
  lack, the blind breaks on sight, and an evidence-richness gap becomes a measured accuracy
  difference between arms.
- **R15c.** Randomize export order across cells and across the R19 two-structure subpopulation.
  Items exported cell-by-cell present in runs that reveal the cell.
- **R15d.** **Stage two runs on a sample, not a census.** R16 needs enough revealed items to estimate
  the anchoring rate, not every item re-reviewed. Re-reviewing the whole queue would double the human
  cost for no additional claim.
- **R15e.** **Blind-integrity check.** In the blinded campaign, ask each reviewer to guess the
  proposing arm on a sample (captured in `reviewerNotes`) and report guess accuracy. Above chance
  means the precision figures are not unanchored and must not be described as such.
- **R16.** Report how often revelation changes a vote, from the R15d sample. This measures anchoring
  and is a finding.
- **R17.** Every precision figure must be computed from **blinded-campaign** votes. The campaign ID
  *is* the stage marker, so no schema change is needed and a revelation-driven revision cannot be
  confused with any other edit.
- **R18.** Verdict and reason code are captured as **one keystroke**, using the app's numeric scoring
  mode with a labelled 1-7 scale ordered as a structural-identity scale — so the value is meaningful
  to the app's own consensus engine rather than an abuse of it:

  | value | label |
  |---|---|
  | 7 | same molecule |
  | 6 | tautomer or protonation variant |
  | 5 | stereoisomer |
  | 4 | sum-composition ambiguous (one side names a set containing the other) |
  | 3 | evidence shown was insufficient |
  | 2 | undecidable in principle |
  | 1 | different molecule |

  Keys 1-9 are already bound to numeric scores in the review UI and `scoring.numeric.labels` is
  rendered in the vote confirmation, so this is configuration only. `expertSelectedCode` is **not**
  used: its input is a free-text box, which cannot hold a frozen vocabulary reliably.
- **R18a.** Every vote also carries a mandatory free-text `reviewerNotes` entry, so items fitting no
  point on the scale are recoverable post hoc without creating an "other" bucket.
- **R18b.** **Freeze the scale after evidence, not before.** Run R1 and a pilot adjudication of 30-50
  real items, confirm the seven points cover what actually appears, then freeze.
- **R18c.** Commit the **value-to-outcome mapping** before any vote is collected. Proposed primary:
  7 and 6 count as a correct link; 5, 4 and 1 as wrong; 3 and 2 excluded. Two pre-declared
  sensitivity mappings: strict (7 only) and permissive (7, 6, 5). Whether *tautomer* and
  *stereoisomer* count as correct is outcome-determining, and those are exactly where a permissive
  matcher's extra links land.
- **R18d.** Set `numericConfirmThreshold` to 6 and `numericRejectThreshold` to 1, so the app's own
  `evidenceStatus` means "experts assert same molecule or protonation variant" rather than something
  arbitrary.
- **R19.** Where a queued item's own source annotation is internally contradictory (the R1/R2 rows),
  present **both** candidate structures and let the expert adjudicate. Never show a single gold value
  that is known to be disputed. Label the candidates by source ("standard-form InChIKey" versus
  "legacy InChIKey") rather than by position, and randomize left/right placement per item.
- **R20.** Inter-rater agreement is measured in a **dedicated agreement campaign** containing only
  the double-rated subset, with every reviewer a member. Membership is campaign-level and the queue
  server prioritizes zero-vote pairs, so in the main queue reviewers naturally spread out and rarely
  overlap — efficient for throughput, useless for agreement. A separate small campaign makes every
  reviewer see every item and guarantees multiple ratings.
- **R20a.** The agreement campaign's items must be **stratified across both disagreement cells**, not
  drawn only from the agreement cells. Agreement measured where a name-based and a structural method
  already concur is measured on the easiest items in the study and says nothing about the cells every
  reported number comes from.
- **R20b.** Pre-register an agreement floor (proposed: Krippendorff alpha >= 0.6 on the disagreement
  strata). Below it, report the vote distribution and **withhold** the precision headline.
- **R20c.** Confidence intervals must propagate rater disagreement — bootstrap over raters and items
  — not a binomial over adjudicated calls, which treats each expert call as ground truth and yields
  an interval narrower than the evidence supports.
- **R20d.** Report every precision figure **twice**: all raters, and independent raters only with the
  tool author's votes excluded. Require at least two independent raters on the subset backing the
  headline.
- **R20e.** **All adjudicators are internal** (decided 2026-08-22). No reviewer is recruited from
  outside Phenome Health. This is a real limitation on the strongest claim in the paper and must be
  stated plainly in the write-up rather than left for a reviewer to notice — the mitigations are
  R20d's independent-raters-only figure, the R15a-R15e blinding, R18c's pre-committed mapping, and
  R22a's published exemplars, which let a reader re-adjudicate any row without trusting the panel.

**E. Reporting**

- **R21.** Produce a per-pair comparison against Monti's published counts (Arivale 615, Xu 432,
  LLFS 163, BLSA 99), with BioMapper's asserted / certified / refused figures alongside.
- **R21a.** State, per pair, the exact row set each figure was computed on, and mark Monti's
  published counts as computed on a **different inclusion basis** rather than presenting them as
  directly comparable. Where a re-derived arm-B count on the identical row set exists, present that
  as the comparison and Monti's published count as context only.
- **R22.** State the expert-adjudicated precision of each arm's disagreement cell, with confidence
  intervals per R20c, and the count of Monti links the experts judge structurally wrong.
- **R22a.** **Lead with the exemplar set, which already exists.** The 48 InChIKey-disagreeing rows
  from the NECS annotation are a named, individually checkable artifact: each carries a compound
  name, two contradictory candidate keys, both SMILES, and a formula, all from a single published
  file. A reader can verify any one of them without re-running anything. Publish these as the primary
  evidence, with expert adjudication supplying the verdict per row, and report the aggregate rates as
  supporting context rather than as the headline. The project's own audit history is that every claim
  resting on an aggregate rate collapsed and every claim resting on a specific checkable artifact
  survived — this is already the surviving kind.
- **R22b.** Write and hash-pin a **committed analysis plan** before the campaign opens, covering the
  R18b mapping, the sampling design and its variance estimator, and the stopping rule. Report any
  deviation from it explicitly. R23 pins inputs; this pins analysis decisions, which is where the
  August collapses actually happened.
- **R23.** Persist every run's full results to a timestamped path by default, pinning the inputs
  needed to reproduce (source SHAs, KG snapshot, ChEBI release, config).

## Success Criteria

**Deliverable 1**

- Every one of the 48 contradictory rows carries a classification and a recorded per-row precedence
  rule, derived offline from the published file, with R2a verification available to disconfirm it.
- The exemplar set is publishable as-is: a reader can verify any single row without re-running
  anything and without access to BioMapper.
- R3 reports how the NECS headline accuracy and the 134-miss disposition move, under both the
  repaired and the original gold.
- R4 states plainly whether the withdrawn Arivale precision claim revives, and R4a's consequence for
  Deliverable 2 is recorded either way.

**Deliverable 2**

- The claim "BioMapper recovers N links Monti's method missed, at expert-adjudicated precision P,
  while Monti's curated set contains M structurally wrong links" is supported by artifacts, with
  every number traceable to a pinned run **and accompanied by the R22a exemplar set**.
- The campaign can show BioMapper performing **worse**, demonstrated by R11b seed detection rather
  than asserted. A design that cannot fail is not evidence.
- The repaired gold is derived from a single published file, with R2a verification available to
  disconfirm the precedence rule.
- Refusal counts are reported as prominently as coverage counts, and R8a ensures refusing more cannot
  improve the headline.
- Expert time is spent where the machine declined **and** on a measured audit sample of where it did
  not (R11a).

## Scope Boundaries

- **Not** a replication of Monti's numbers. Their method includes hand curation and is not
  reproducible algorithmically. Their published counts are the baseline to beat, not a target to
  match. The replication already performed (Arivale 95%, LLFS 88%, Xu 109%, BLSA 80% of reported)
  served its purpose by surfacing the errors below and is not a deliverable.
- **Not** a coverage-only claim. Coverage is the narrative on-ramp (beat 1), not the destination;
  the claim is structural certification (beats 2–4). A coverage number presented as the headline
  reproduces the limitation being criticised.
- **Not** building or modifying the review application. Verified against the deployed code: the
  protocol fits with **configuration only, no code changes**. Staging is two campaigns rather than
  two UI stages (R15); blinding is an export-time property rather than a display toggle (R15a); the
  seven reason codes ride the existing labelled numeric scale (R18); agreement uses a dedicated
  campaign (R20); vote extraction is a read-only database query (R13a).
- **Not** adjudicating sum-composition lipid species. They name a set of molecules; no structural
  oracle can decide them. They are counted and refused.
- **Not** claiming BioMapper beats name matching on coverage for same-vendor panels. This was
  measured, not assumed: Arivale is 98% covered by name matching alone and the headroom is ~zero.
- **Not** publishing any Monti supplement content without checking Springer supplement terms.

## Key Decisions

- **Symmetric design rather than reviewing only BioMapper's additions**: reviewing only the links
  BioMapper adds measures its precision but never Monti's, and is structurally incapable of finding
  BioMapper worse.
- **All four cohort pairs** (reaffirmed 2026-08-22 after review challenged it): the goal is the
  harmonization picture Monti published, not a convenience subset. Accepted costs, stated so they are
  not rediscovered later: BLSA will yield mostly refusals; Arivale has ~zero recall headroom and
  contributes precision only; and two of the four depend on panel lists that must come from a
  coauthor. The R11c sizing gate is what keeps this from becoming an unbounded commitment.
- **Certificate-triaged queue with a pre-campaign sizing gate (R11c)**: spends expert time where the
  machine declined, while bounding the commitment before reviewers are asked for hours.
- **Two-stage blinded-then-revealed adjudication**: an unanchored precision estimate is the whole
  point, and R15a–R15c are what make the blind real rather than nominal.
- **Reason codes frozen after a pilot, not before (R18a)**: freezing against an unvalidated taxonomy
  risks codes that do not fit the data.
- **Gold repair sequenced classification-first (R1 before R2)**: fixing column precedence before
  gathering the evidence that should determine it would write the wrong structure into the gold and
  R3/R4 would inherit it silently.
- **Use the 408-row LLFS published panel, not the 364-row column supplied in the four-cohort
  spreadsheet**: that column is pre-filtered to the RefMet-standardizable subset (it standardizes
  364/364 with zero drops, which is only possible for an already-filtered list). Benchmarking on it
  would hand the baseline its own advantage by removing exactly the names its method discards.

## Dependencies / Assumptions

- **Corrected baseline figures.** The paper's main Table 2 is authoritative over its Methods prose.
  BLSA overlap is **99**, not the 188 stated in the harmonization paragraph (Table 2 and the BLSA
  cohort section both say 99; 188 appears to be lifted from LLFS's "188 lipid and 220 polar"). Xu is
  **432**, not the 385 in the same paragraph. Arivale is **615 of 626 = 98%**, not the "615 of 766 =
  80%" recorded in the prior benchmark design document — 766 is the full Watanabe panel, Monti used
  a 626 subset. The 80% figure implies recall headroom that does not exist.
- **Panels in hand and verified against Table 2**: BLSA 468 (exact), Xu 821 (exact), NECS 1,213 named
  (exact), LLFS 408 (published supplement).
- **Arivale panel is a GATE, not a caveat.** The available Watanabe panel is 766 analytes against
  Monti's 626. Every analyte in the 140-row difference is one Monti never evaluated, so a BioMapper
  link involving it lands in the "BioMapper linked / Monti did not" cell without Monti having
  declined anything — and the headline "recovers N links Monti missed" is false for each. Until the
  626-analyte list is obtained, the Arivale disagreement cell must be split into in-scope and
  unknown-scope partitions, with N reported only from the in-scope partition. The same constraint
  applies to any revival of the withdrawn Unit 0 precision claim, which is the claim Arivale carries.
- **Prior-branch recovery (R0) is a prerequisite**, not a planning detail. A single laptop-local
  worktree is currently the only copy of code four preprint numbers depend on.
- **The certificate's `refusal_reason` field is reserved but unshipped** (L28), and L30 states refusal
  must not be described as observable in a released artifact until it lands. R7's three-way
  distinction, R8's refused count, R12, R14 and the refusal success criterion are all blocked on that
  follow-up merging first.
- **Tier A resolves nothing on its own.** The certificate reaches corroborated or contradicted only
  in the Tier B branch; Tier A is zero-I/O and emits only uncorroborated or unavailable. The pinned
  audit records `n_tier_b_resolved: 0` and Tier B has never executed. If Tier B stays off, R11 triage
  degrades to "queue everything" and R12's queue-size finding measures the configuration rather than
  the machine. If it is turned on it is a rate-limited external lookup per row and recreates a
  documented cold-versus-warm cache confound at four-panel scale.
- **Deployment and KG snapshot pinning is a prerequisite for the first live run**, not a
  planning-phase research item. This is the defect that already stripped provenance from the existing
  benchmark corpus, and here it gates irreversible human labour: if the snapshot behind the queued
  evidence cannot be named afterwards, every adjudicated vote inherits the ambiguity.
- **The existing NECS results being re-scored** come from `suite_20260805T033340Z`, whose audit records
  `Publishable: False` and which pins no KG snapshot or ChEBI release. R3 and R4 may need re-deriving
  rather than re-scoring.
- **Reviewer pool**: Trent plus 1–2 Phenome colleagues. Recruiting them is a **campaign-open gate**
  (R20d requires at least two independent raters on the headline subset), and the fallback if
  recruitment fails must be written down before the queue is built.
- **Noa Rappaport is a coauthor on this paper** as well as on Monti et al. This is a
  correction-of-record with the original author participating, not an external critique, and she is
  the natural route to the 626-analyte Arivale list and the BLSA list that yields 99. Framing should
  be collaborative throughout, and any count of incorrect links in Monti et al. should reach her
  before it appears in a draft.
- **Live BioMapper runs are a supervised operator step** and must never be fired inside an automated
  pipeline tail.

## Outstanding Questions

### Resolve Before Planning

*(none — all blocking questions resolved 2026-08-22. See the Resolved log under Next Steps.)*

### Deferred to Planning

- [Affects R7a][Technical] The exact link-level verdict state table composing two per-side
  certificates.
- [Affects R11][Technical] Is Tier B on or off, at what per-row lookup budget, and how is the cache
  confound controlled at four-panel scale?
- [Affects R1][Technical] How to decide tautomer versus genuine defect when both candidate structures
  share a molecular formula. Formula settles cortisone (C21H28O8S vs C21H28O5) but not
  gamma-glutamylvaline (both C10H18N2O5).
- [Affects R14][Needs research] The sum-composition classifier, validated against fully-specified
  species so it does not over-flag.
- [Affects R21][Needs research] Whether the exact 626-metabolite Arivale list can be obtained — noting
  this now gates the Arivale claim rather than caveating it.
- [Affects R15][Design] Skip/defer behaviour, session resume, revisit-after-reveal state, whether a
  revision can itself be revised, and whether reviewers can see each other's votes on shared control
  items.
- [Affects R11a][Technical] The audit-sample fraction and per-pair minimum.

## Next Steps

-> `/ce:plan`, scoped to **Deliverable 1** (Group A: gold repair and exemplar set).

*All seven blocking questions resolved 2026-08-22:*
1. **EITL compatibility** — protocol reshaped to run on the deployed app with configuration only, no
   code changes, verified against the running source.
2. **Exemplar versus rate framing** — the 48 InChIKey-disagreeing rows are the exemplar set and now
   lead; rates are supporting context.
3. **Coauthor relationship** — Noa Rappaport is a coauthor on this paper as well as on Monti et al.
   Collaborative correction of record, not external critique.
4. **Refusal-sensitive metric** — both are reported (R8a): certified-correct at a fixed refusal
   budget, and a coverage-precision curve with the operating point marked.
5. **Outside adjudicator** — none at this stage (R20e). The limitation is stated explicitly in the
   write-up rather than left implicit.
6. **Pair scope** — all four, for thoroughness, with the R11c sizing gate bounding the commitment.
7. **Deliverable split** — Group A ships separately as Deliverable 1 and is the current planning
   scope.
