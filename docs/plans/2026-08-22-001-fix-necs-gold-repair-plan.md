---
title: "fix: Repair the NECS gold structure column and publish the exemplar set"
type: fix
status: active
date: 2026-08-22
origin: docs/brainstorms/2026-08-22-cross-cohort-eitl-campaign-requirements.md
---

# fix: Repair the NECS gold structure column and publish the exemplar set

## Overview

The NECS benchmark scores against a gold InChIKey column that the source file itself contradicts. The
Monti et al. supplement (`MOESM5`, the paper's Table S1 — Metabolon's vendor annotation of all 1,495
features) ships **two** InChIKey columns: legacy `INCHIKEY` (two-block, 796 filled) and standard
`inchi_key` (three-block, 839 filled). Of the 691 rows carrying both, **48 disagree** at the
connectivity level. The adapter binds the legacy column, so every NECS number published to date is
scored against the contradicted one.

This plan repairs that column, classifies the disagreements by chemical cause, re-scores the existing
benchmark under both golds, recomputes the withdrawn Unit 0 sizing gate, and produces a publishable
exemplar set. **Derivation is offline for the ~640 agreeing rows; the disagreeing rows require one cached, pinned
external resolution** (name/CID → InChIKey), which decision #3 established is the only signal that can
adjudicate them (self-consistency ties on 30 of 48). No BioMapper run and no Kestrel call. The pinned
exceptions are: that adjudication pass (Unit 5), and the
recovered gate scripts' own cached network dependencies (Unit 7 — `adjudicate_conflicts.py` hits
PubChem PUG-REST; `llfs_step1_sizing.py` hits the Metabolomics Workbench RefMet service). Both have
on-disk caches; the caches must be pinned as inputs, not assumed.

This is **Deliverable 1** of the cross-cohort programme. Deliverable 2 (the four-pair benchmark and
the EITL adjudication campaign) is gated on this landing and on R4a's verdict, and is out of scope
here (see origin: `docs/brainstorms/2026-08-22-cross-cohort-eitl-campaign-requirements.md`).

## Problem Frame

Eight of the nine "NECS gold defects" found by the 2026-08-04 Unit 0 gate are among these 48 rows, and
in every case the standard-form column carries exactly the value that gate derived independently from
PubChem. So those were not defects requiring a third adjudication path to discover — **the benchmark
scored against the wrong column, and the right answer was in the same row of the same file.**

That makes the 48 rows a specific, individually checkable artifact: name, two contradictory candidate
keys, both SMILES, a formula, all from one published file, verifiable without re-running anything.
This project's audit history is that claims resting on aggregate rates collapsed and claims resting on
checkable artifacts survived, so the exemplar set — not the rates — is the primary output.

**The correctness hazard this plan must not repeat.** An August 2026 audit established that the
InChIKey first block is invariant to stereochemistry but **not** to ring-chain tautomerism or
protonation state. Reading that artifact class as chemistry killed four headline claims: the
xylose "swap" is the pyranose ring versus the open-chain form (same molecule), and the choline "wrong
molecule" is the inner salt versus the cation (one proton apart). Only cortisone is formula-confirmed;
gamma-glutamylvaline is a genuine regioisomer error but formula-identical. Classification must
therefore run off structures, not off comparing keys to each other.

## Requirements Trace

Carried from the origin document. Deliverable 1 covers R0–R4a, R22a, and R23.

- **R0.** Recover the stranded prior branch before R3/R4 can start.
- **R1.** Classify the 48 disagreeing rows from the file's own `SMILES` and `formula` columns — never
  by comparing InChIKeys to each other — into genuine wrong-molecule defect, tautomer/protonation
  encoding difference, stereochemistry-only difference, or undecidable.
- **R2.** Rebuild the gold column as a **per-row consequence** of R1's classification, recording the
  rule applied to each row. No global "standard column wins" precedence.
- **R2a.** Derivation stays offline; verification may make one cached, pinned external resolution on a
  held-out sample to check the precedence rule.
- **R3.** Re-score the existing NECS benchmark under both the repaired and the original gold.
- **R4.** Recompute the 2026-08-04 Unit 0 sizing gate under both golds; state whether the withdrawn
  Arivale precision claim revives.
- **R4a.** Record the consequence for Deliverable 2 either way.
- **R22a.** Publish the exemplar set as the primary evidence.
- **R23.** Persist every run to a timestamped path by default, with inputs pinned.

## Scope Boundaries

- **Not** running BioMapper, Kestrel, or any live mapping. R3 re-scores from persisted artifacts.
- **Not** the four-pair harmonization benchmark or the EITL campaign — Deliverable 2.
- **Not** re-deriving the Monti overlap replication. Already done; artifacts at
  `~/external_benchmark_runs/monti_string_replication_20260820T182111Z/`.
- **Not** changing the resolver, the mapper, or any `src/biomapper2/core/` behavior. This plan touches
  the study harness and its gold handling only.
- **Not** publishing any Monti supplement content externally without a Springer supplement-terms check.

### Deferred to Separate Tasks

- Backfilling the retraction into
  `docs/solutions/best-practices/adjudicate-benchmark-gold-with-independent-third-path-2026-08-05.md`:
  its choline and xylose examples are dead and its "floor" language is unsafe, but the correction lives
  only in auto-memory. Separate docs PR — but **required before anyone cites that doc again**.
- Deliverable 2 planning, gated on R4a.

## Context & Research

### Relevant Code and Patterns

| Concern | Existing code to reuse or follow |
|---|---|
| Offline re-score from a persisted run | `studies/external_benchmarks/rescore_id_equivalence.py` — clone its shape wholesale, including the `strict_sanity_ok` reproduction guard that requires **both** numerator and denominator to re-derive |
| Charge/protonation normalization | `studies/external_benchmarks/scorers/structure_oracle_scorer.py::neutralize_first_block` (RDKit `Uncharger`) |
| First-block helper | `structure_oracle_scorer.py::first_block` |
| SMILES → full standard InChIKey | `studies/external_benchmarks/adapters/srm1950.py::inchikey_from_smiles` |
| Cached, IPv4-forced, fail-soft external resolver (R2a) | `studies/external_benchmarks/scorers/independent_inchikey.py::PubChemInChIKeyResolver` |
| Fail-closed gold completeness discipline | `studies/external_benchmarks/scorers/cross_source_gold.py::assert_gold_resolution_complete` |
| Per-row derived column precedent | `adapters/necs_metabolon.py` `HAS_STRUCTURE_COL = "has_gold_structure"` |
| Timestamped save-by-default | `studies/external_benchmarks/run.py::default_run_dir`, `runner.py::build_manifest` |
| Positive-control test naming | `test_spot_check_fails_on_swapped_gold_column`, `test_validate_all_catches_injected_corruption`, `test_fallback_recompute_catches_tamper` |

Stack: Python ≥3.10 (CI tests 3.10 **and** 3.12), `uv`, ruff/black at line-length 120, pyright,
pytest with `pythonpath = ["."]`. RDKit is already a dependency (`rdkit>=2025.9.1`) — it is simply not
in the system interpreter, so work runs under `uv`. Repo rule: **≤8 tests per test file**.

### Institutional Learnings

- `docs/solutions/best-practices/absent-evidence-is-unverifiable-not-wrong-2026-08-06.md` — the design
  template for the provenance column. Give "no evidence" its own state; keep infrastructure failure
  distinct from a real negative; record the comparison rule as a **versioned field** so a later
  tightening adds a value rather than mutating one. Also: a rate plotted across the abstention
  boundary is the forbidden claim rendered as a chart.
- `docs/solutions/best-practices/audit-instruments-backing-published-claims-2026-08-05.md` — an audit
  that cannot report the failure it exists to detect will report clean. Prose must name the artifact
  *field*, never restate the value. Run the classifier over a population where each verdict is known
  nonzero and record it as a positive control.
- `docs/solutions/best-practices/fail-closed-guards-must-not-no-op-on-absent-input-2026-07-13.md` — for
  every guard, ask what input makes it do nothing, and whether the output is still produced.
- `docs/solutions/best-practices/trustworthy-gates-invoke-test-real-shape-faithful-fallbacks-2026-08-04.md`
  — a gate declared but never called guards nothing; grep the run path.
- `docs/solutions/runtime-errors/gitignore-globs-exclude-pinned-benchmark-data-2026-08-04.md` —
  `.gitignore` blanket-ignores `*.csv`, `*.tsv`, `*.json`. Artifacts need a `!` negation (precedent:
  `!studies/analysis/results/*.json`) plus `git ls-files` verification.
- `docs/solutions/workflow-issues/shared-clone-concurrent-harness-branch-switch-2026-08-04.md` — the
  nightshift harness force-switches branches in `~/projects/biomapper2` and has silently destroyed
  uncommitted work there four times. **Do this work in an isolated worktree.**
- ⚠️ `docs/solutions/best-practices/adjudicate-benchmark-gold-with-independent-third-path-2026-08-05.md`
  is the closest ancestor of this task **and is partly retracted**, with the retraction recorded only
  in auto-memory. Read it only alongside that correction.

### External References

None gathered. RDKit is an existing dependency with two in-repo usage sites, the chemistry traps came
back from the learnings pass with more specificity than API docs would provide, and the remaining
RDKit surface is parameterization better settled at implementation time.

## Key Technical Decisions

- **Work in an isolated git worktree, not `~/projects/biomapper2` directly.** That clone is driven
  concurrently by the nightshift harness, which force-switches branches and has destroyed uncommitted
  work four times across two dates.
- **The file contains two parallel annotation vintages, not one annotation plus a correction.** Legacy
  block: `INCHIKEY`, `SMILES`, CAS/HMDB/KEGG/PUBCHEM. Modern block: `inchi_key`, `smiles`, `formula`,
  `exactmass`, `pubchem_cid`. Treating the disagreement as vintage-versus-vintage is what makes per-row
  adjudication possible — each vintage carries its own structure, so both candidate structures are
  available in the same row.
- **Precedence is decided per row by which candidate its own vintage's SMILES supports**, never by a
  global rule. Format modernity is not evidence of chemical correctness.
- **Classification runs on structures, not keys.** Canonicalize tautomer and charge state before
  comparing, then decide the class from formula and from the InChIKey stereo layer (block 2) rather
  than from block-1 equality.
- **The taxonomy must separate formula-differing from connectivity-differing-formula-identical.**
  Cortisone is formula-confirmed (C21H28O8S vs C21H28O5); gamma-glutamylvaline is a genuine regioisomer
  error but both sides are C10H18N2O5. Collapsing these would let the exemplar set describe the second
  as if it were the first.
- ⚠️ **UNRESOLVED — the selector and the adjudication key disagree, and this changes the deliverable.**
  Measured against the pinned file: **48 rows disagree at block 1; 182 disagree under
  `block1 + "-" + block2[:8]`.** The 134-row difference is exactly the stereo layer. As drafted the
  plan selects at block 1 while mandating the fuller key everywhere else, which means `stereo_only`
  can almost never be populated from the real population and the exemplar set silently omits the 11
  isomer groups this domain must keep apart. Whether the deliverable is the 48-row set or the 182-row
  set is a decision for the operator, not the implementer — see Open Questions.
- **Adjudication key stays `block1 + "-" + block2[:8]`** for any legacy-versus-standard comparison.
  Block-1 alone silently merges 11 groups this domain must keep apart (fumarate/maleate,
  myo-/chiro-inositol, lactose/maltose, cis/trans-urocanate, bilirubin isomers,
  ursodeoxycholate/isoursodeoxycholate, threonate/erythronate). Now that standard keys are available
  directly, reconstruction is only needed on the legacy side.
- **Record `comparison_rule` as a field on every emitted row.** The 48/691 count is a function of the
  rule that produced it; a later tightening must add a value rather than silently change the number.
- **Fix the `gold_smiles` mis-binding as part of this work.** It is not incidental — R1 needs both
  SMILES columns explicitly bound, and leaving the collision in place would have the classifier compare
  a legacy key against a modern structure.

## Open Questions

### Resolved During Planning

- **Is RDKit available?** Yes — `rdkit>=2025.9.1` in `pyproject.toml`. Absent from the system
  interpreter only; work runs under `uv`.
- **Can R3 re-score without a live run?** Yes. The persisted `CHEBI_results.json` `per_row` entries
  carry `{name, chosen_kg_id, gold_block, predicted_block, correct, needed_fallback,
  charge_normalized_correct, kg_equivalence_set_correct}`. Re-scoring under a repaired gold is a pure
  join of the repaired block against the recorded `predicted_block` — no oracle, no network.
- **Is the stranded branch actually lost?** No. `feat/cross-cohort-harmonization-benchmark` is intact
  locally at 13 commits ahead of dev; only its remote was deleted. R0 is a push-and-cherry-pick, not a
  reconstruction.
- **Where does the repair live?** The adapter transform layer. `build_input_df` is where
  `gold_inchikey` is currently chosen, it is pure and offline, and it already has a per-row derived
  column precedent.

### Blocking — operator decision required before implementation

Surfaced by the persona review; each changes what gets built.

- **Is the deliverable the 48-row set or the 182-row set?** Measured against the pinned file: 48 rows
  disagree at block 1, 182 under the plan's own `block1 + "-" + block2[:8]` key. The 134-row difference
  is the stereo layer. Selecting at block 1 means `stereo_only` is near-unpopulated and the exemplar set
  omits the isomer groups the domain must keep apart; selecting at the fuller key nearly quadruples the
  primary deliverable.
- **Are the charge-normalized and equivalence-set arms in scope for the re-score?** They are not
  recomputable offline — both need live Kestrel. Either accept one supervised live pass, or drop them
  and state that Unit 2's binding fix leaves the published 78.4% stale with no recomputation path.
- ✅ **RESOLVED 2026-08-23 — the self-consistency rule is circular AND undecidable; replaced.** Measured
  on the pinned file: legacy 97.5% / modern 99.9% block-1 self-consistency (the old "0/8 legacy" was a
  two-block format artifact at full-key). Modern's 99.9% = co-derived key+SMILES, so the signal is
  near-worthless; and self-consistency ties on 30 of the 48 disagreeing rows. **Precedence is now decided
  by an independent name/CID anchor** (HMDB 29/30, pubchem_cid 22/30, CAS 20/30 available on the ties).
  Consequence: the disagreeing rows now require one cached, pinned external pass — see decision #2.
- **Does the `gold_smiles` binding fix ship in this PR or its own?** Its blast radius is every row with
  a SMILES value (835–1180), not the disagreeing subset, and it moves an already-published metric.
  Bundling it into the gold repair means one review covers two changes with different risk profiles.

### Deferred to Implementation

- **Exact RDKit parameterization** for tautomer canonicalization — `TautomerEnumerator` settings,
  and whether `Canonicalize` or explicit enumeration is the right call for sugars specifically.
- **Whether `suite_20260805T033340Z` can be re-scored or must be re-derived.** Its own audit records
  `Publishable: False` and it pins no KG snapshot or ChEBI release. Unit 6 establishes this from the
  artifacts before depending on it; if provenance is inadequate the deliverable reports the delta as
  indicative and flags the re-derivation as required.
- **The held-out sample size for R2a verification** — settled once the class distribution from Unit 4
  is known.

## Disagreement Provenance (measured 2026-08-23, RDKit on the pinned file)

The two contradictory columns are two **Metabolon annotation vintages**: legacy (`INCHIKEY` +
`SMILES`, uniformly 25-char two-block keys, 786/786) and modern (`inchi_key` + `smiles`, uniformly
27-char three-block keys, 839/839, key and SMILES 99.9% co-derived). Both carry SMILES; legacy SMILES
are largely correct even where the legacy key is not.

The 48 block-1 disagreements split by whether each key matches **its own** SMILES:

| Kind | n | Mechanism | Resolution |
|---|---|---|---|
| **A — bad legacy key** | 8 | Legacy `INCHIKEY` contradicts its own SMILES; the SMILES is correct and agrees with modern | **Offline** — trust the SMILES-derived key |
| **B — different structure** | 30 | Both keys self-consistent; the two vintages drew genuinely different structures | **External name/CID anchor** (decision #3) |
| corrupt | ~9 | Legacy cell is `"4000"` | Trivial — modern wins |
| unparseable | 1 | — | undecidable |

**This corrects the August audit's framing of the known rows.** cortisone and gamma-glutamylvaline are
**Kind A** — the legacy *key* is wrong (cortisone's legacy key encodes a sulfate ester absent from the
row's own structures; the legacy SMILES is plain cortisone). "Formula-confirmed defect" compared the
bad key's looked-up structure; the row's own SMILES already had the answer, so these are offline-
detectable. xylose and choline are **Kind B** — both keys match their own SMILES, so the vintages
encode different structures (ring form; charge convention).

**RDKit canonicalization cannot classify Kind B, proven on the known rows.** The `TautomerEnumerator`
MISSED xylose's ring-chain interconversion (labelled it a connectivity defect — the retracted verdict
reborn) and OVER-MERGED gamma-glutamylvaline's regioisomers (labelled a real defect a tautomer). Too
weak and too strong, in the two directions we can check. It must not be the arbiter for Kind B.

**Consequence for scope:** ~17 rows (Kind A + corrupt) are fully offline-resolvable; only the 30
Kind-B rows require the external pass. This is the offline/online boundary that decisions #1 and #2
turn on.

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation
> specification. The implementing agent should treat it as context, not code to reproduce.*

The classifier's decision order matters more than any individual comparison. Canonicalization comes
first, because the whole failure mode being guarded against is reading a normalization artifact as
chemistry.

```
for each row where INCHIKEY and inchi_key disagree at connectivity level:

    legacy_struct  <- parse(SMILES)      # legacy vintage's own structure
    modern_struct  <- parse(smiles)      # modern vintage's own structure

    if either unparseable or absent  -> class = UNDECIDABLE
                                        reason = which side was missing
                                        (never "legacy wrong" by default)

    # 1. does each vintage's key match its OWN structure?
    legacy_selfconsistent <- key_from(legacy_struct) ~= INCHIKEY
    modern_selfconsistent <- key_from(modern_struct) ~= inchi_key
        -> this decides PRECEDENCE per row (R2), independently of class

    # 2. canonicalize BEFORE comparing the two structures
    a <- uncharge(canonical_tautomer(legacy_struct))
    b <- uncharge(canonical_tautomer(modern_struct))

    # 3. classify from structure, in this order
    if formula(a) != formula(b)                  -> WRONG_MOLECULE (formula-confirmed)
    elif connectivity(a) != connectivity(b)      -> WRONG_MOLECULE (formula-identical)
    elif stereo_layer(a) != stereo_layer(b)      -> STEREO_ONLY
    else                                         -> TAUTOMER_OR_CHARGE
                                                    (the pre-canonicalization difference was
                                                     an encoding artifact, not chemistry)
```

Steps 1 and 3 are deliberately independent: *which column to trust* and *why they differ* are
different questions, and conflating them is what produced the retracted analysis.

## Implementation Units

- [ ] **Unit 1: Recover the stranded branch**

**Goal:** Get the Unit 0 gate and the miss adjudicator onto a branch with a remote, so R3/R4 can run
and so a single laptop-local worktree is no longer the only copy of code four preprint numbers depend
on.

**Requirements:** R0

**Dependencies:** None. Blocks Units 6 and 7.

**Files:**
- Recover from `feat/cross-cohort-harmonization-benchmark`: **`scripts/adjudicate_conflicts.py`** and
  **`scripts/review_probes.py`** (these two produced the archived STOP verdict — see Unit 7),
  `scripts/llfs_step1_sizing.py`, `scripts/adjudicate_necs_misses.py`,
  `docs/superpowers/specs/2026-08-04-cross-cohort-harmonization-benchmark-design.md`,
  `docs/plans/2026-08-04-001-feat-cross-cohort-harmonization-benchmark-plan.md`
- Untracked inputs that a fresh worktree will NOT carry and that must be copied explicitly:
  `data/NIHMS2038904-supplement-2.xlsx`, plus the run directories
  `~/external_benchmark_runs/scorer_rerun_20260723/`, `~/external_benchmark_runs/necs_arivale_baseline_20260804/`,
  `~/external_benchmark_runs/arivale_public_panel_20260804/`, `~/external_benchmark_runs/cohort_panels_20260804/`

**Approach:**
- Push the intact local branch to its remote first, before any cherry-picking. It is 13 commits ahead
  of dev and currently exists on one disk.
- Cherry-pick only what Deliverable 1 needs; the rest of the branch stays for Deliverable 2.
- Set up an isolated worktree for the remaining units rather than working in the shared clone.
- **`feat/cross-cohort-harmonization-benchmark` is already checked out** at `~/worktrees/cross-cohort`,
  so `git worktree add` on that branch will be refused. Push from there, or branch off it.
- `scripts/review_probes.py` hardcodes the absolute path `~/worktrees/cross-cohort/data/...`, coupling
  the recovered scripts to that directory. Either keep that worktree as their run location or fix the
  path as part of recovery.
- **Springer supplement-terms check is a blocking precondition of this unit, not a Unit 8 caveat.** The
  primary deliverable is derived from MOESM5; if per-row redistribution is restricted, the exemplar set
  ships as row identifiers plus computed verdicts and provenance, with source values *referenced* rather
  than reproduced. Record the answer in writing before any other unit starts.

**Test expectation:** none — recovery and branch hygiene, no behavioral change.

**Verification:**
- The branch exists on the remote and `git log origin/<branch>` shows all 13 commits.
- Each recovered script **runs to completion against its pinned inputs** — not merely imports. Import
  success does not detect a missing untracked data file.
- The Springer answer is written down, with the exemplar-set format decided as a consequence.

---

- [ ] **Unit 2: Bind the annotation columns correctly**

**Goal:** Make both annotation vintages addressable, and fix the column mis-binding that currently
pairs a legacy key with a modern structure.

**Requirements:** R1 (prerequisite — classification is impossible without both structures bound)

**Dependencies:** Unit 1

**Files:**
- Modify: `studies/external_benchmarks/adapters/necs_metabolon.py`
- Modify: `studies/external_benchmarks/config.py` (NECS `DatasetConfig`)
- Test: `studies/external_benchmarks/tests/test_necs_adapter_vintage_binding.py` (new file — `test_necs_adapter.py` already holds 6 tests and the repo caps at 8)

**Approach:**
- `_resolve_column` builds `{col.lower(): col}`, so on a lowercase collision the **last** column wins.
  `SMILES` (col 14, 1180 filled) and `smiles` (col 25, 835 filled) collide, and `gold_smiles` currently
  binds the modern one while `gold_inchikey` binds the legacy one. Confirmed against the persisted
  `dataset_card.json`, which records SMILES coverage 835.
- Bind the two vintages explicitly rather than by candidate ordering: legacy (`INCHIKEY`, `SMILES`) and
  modern (`inchi_key`, `smiles`), plus `formula` and `exactmass`, which the adapter does not read today.
- Note that `inchi_key` already matches the existing `"INCHI_KEY"` candidate — the only thing keeping
  the legacy column selected is candidate ordering. Make that explicit rather than incidental.
- Changing `gold_smiles` moves an existing published number (charge-normalized 78.4% was computed
  across the mismatched pairing). That is expected and is part of what Unit 6 reports.

**Execution note:** Add a characterization test pinning the *current* (mis-bound) behavior before
changing it, so the fix demonstrably moves what it is supposed to move.

**Patterns to follow:**
- `HAS_STRUCTURE_COL` for derived per-row columns; `build_card()` for coverage summaries.
- `test_necs_adapter.py::test_fetch_is_isolated` — network isolation by monkeypatching the
  module-level `fetch_supplement`, not by a mocking library.

**Test scenarios:**
- Happy path: an input frame with both `SMILES` and `smiles` columns binds each to its intended
  vintage, and the resolved column names are recorded on the card.
- Edge case: a frame with only one SMILES column binds it unambiguously and records which vintage is
  absent.
- Error path: a frame missing `formula` entirely fails loud with a message naming the dataset and the
  missing column, rather than silently producing an unclassifiable frame.
- Positive control: a frame where the two SMILES columns are deliberately swapped must produce a
  different binding than the correct frame — proving the binding is actually read, not assumed.
- Integration: `build_card()` reports SMILES coverage 1180 for the legacy binding and 835 for the
  modern one, distinguishing them rather than reporting a single ambiguous number.

**Verification:**
- Coverage counts per bound column match the source file census (INCHIKEY 796, inchi_key 839,
  SMILES 1180, smiles 835, formula 940).
- The card records which physical column each logical role resolved to.

---

- [ ] **Unit 3: Structure-comparison primitives**

**Goal:** The reusable chemistry operations the classifier composes, each independently testable, so
the classifier itself contains decision logic rather than RDKit mechanics.

**Requirements:** R1

**Dependencies:** Unit 2

**Files:**
- Create: `studies/external_benchmarks/scorers/structure_compare.py`
- Test: `studies/external_benchmarks/tests/test_structure_compare.py`

**Approach:**
- Primitives: parse SMILES to a molecule; canonicalize tautomer; neutralize charge; derive full
  standard InChIKey; extract connectivity (block 1) and stereo layer (block 2); compute molecular
  formula.
- Reuse rather than reimplement: `neutralize_first_block` already wraps RDKit `Uncharger`, and
  `inchikey_from_smiles` in `adapters/srm1950.py` already does SMILES → full standard key.
- Tautomer canonicalization is genuinely new — nothing in the repo does it today, and it is the
  operation that prevents the retracted xylose analysis from recurring.
- Block 2 is discarded everywhere in the repo currently. Stereo-only differences are cleanest to read
  from block 2 rather than from SMILES.
- Every primitive returns an explicit "could not" rather than a falsy default, so a parse failure is
  never silently equivalent to a negative result.

**Execution note:** Test-first. The correctness cases are enumerable from known chemistry and each has
a documented expected answer.

**Resolve before writing this unit:** whether stock RDKit canonicalization collapses ring-chain sugar
forms at all. Ring-chain interconversion is not in the standard tautomer transform set, so the xylose
scenario below may be unsatisfiable. **If it is: xylose is classified `undecidable` with an explicit
"canonicalization out of scope" reason — it must NOT fall through to `wrong_molecule_formula_identical`,
which would republish a stronger version of the exact verdict that was retracted.**

**Test scenarios:**
- Happy path: a clean SMILES round-trips to the expected standard InChIKey (use real molecules —
  glucose, L-alanine, caffeine, ethanol, matching existing fixture convention).
- Happy path: charge neutralization collapses the choline cation and inner salt to the same
  connectivity.
- Happy path: tautomer canonicalization collapses open-chain and pyranose xylose to the same form.
- Edge case: a molecule with no stereocentres yields a stereo layer that compares equal to itself and
  does not spuriously differ.
- Error path: unparseable SMILES returns the explicit "could not" value, never an empty string that
  would compare equal to another failure.
- Error path: an empty or whitespace-only cell is distinguished from an unparseable one.
- Positive control: two genuinely different molecules with the same formula (an alpha/gamma
  regioisomer pair) must be reported as connectivity-differing — proving the comparison is not
  formula-only.
- **Over-merge control:** a keto/enol-adjacent pair and a sugar epimer pair that must survive
  canonicalization as *distinct*. `tautomer_or_charge` is the fall-through class in Unit 4's cascade, so
  without this control an over-aggressive canonicalizer silently relabels real chemistry as an encoding
  artifact — the mirror image of the failure this plan exists to correct, and equally publishable.

**Verification:**
- Each primitive has a case that exercises its failure return, not only its success return.

---

- [ ] **Unit 4: The 48-row classifier and taxonomy**

**Goal:** Assign every disagreeing row a class and the evidence behind it (R1), and reconcile the count
against the prior measurement of the same quantity.

**Requirements:** R1

**Dependencies:** Unit 3

**Files:**
- Create: `studies/external_benchmarks/scorers/necs_gold_repair.py`
- Test: `studies/external_benchmarks/tests/test_necs_gold_classifier.py`

**Approach:**
- **First split by KIND, established 2026-08-23 (see Disagreement Provenance).** Kind A (a key
  contradicts its own SMILES → the key is the defect, the SMILES is the arbiter, fully offline) versus
  Kind B (both keys self-consistent, the two SMILES genuinely differ → needs the external anchor).
  This split is computable offline for every row and determines whether external resolution is even
  needed.
- Within-kind classes: `wrong_molecule_formula_confirmed`, `wrong_molecule_formula_identical`,
  `stereo_only`, `tautomer_or_charge`, `undecidable`.
- ⚠️ **RDKit canonicalization is NOT the Kind-B arbiter** — proven to miss ring-chain sugars (xylose)
  and over-merge regioisomers (gamma-glutamylvaline). Kind-B class is decided against the external
  name/CID resolution, with canonicalization used only as a corroborating signal, never the decider.
- **Uncharger cannot neutralize quaternary ammonium** (choline stays C5H14NO+), so charge-convention
  differences on permanently-charged species need a charge-parent standardizer or a charge-insensitive
  comparison layer, not `Uncharger` alone.
- Canonicalize before comparing, per the design sketch. A pre-canonicalization block-1 difference that
  disappears after canonicalization is `tautomer_or_charge`, i.e. an encoding artifact.
- `undecidable` carries the reason (which side was absent or unparseable). It must never be the default
  landing place for a row that simply failed to parse — that is how "legacy key wrong" gets asserted
  without evidence.
- Emit `comparison_rule` as a versioned field on every row.
- **Reconcile against the prior measurement.** A 2026-08-05 run measured the SMILES↔INCHIKEY
  disagreement on this same file at 12 connectivity-level plus 58 stereo-level out of 697 rows. That is
  a different comparison (structure-versus-key) than this one (key-versus-key), so the numbers need not
  match — but the relationship must be explained in the artifact. If they cannot be reconciled, one of
  the two comparison rules is wrong and that must be resolved before either number is published.
- **Known-answer rows (corrected 2026-08-23 to kind-aware verdicts), the classifier's acceptance
  test:** cortisone → **Kind A** (legacy key wrong, legacy SMILES = cortisone); gamma-glutamylvaline →
  **Kind A** (legacy key is a regioisomer's, legacy SMILES correct); choline → **Kind B**,
  charge-convention (Uncharger cannot fix quaternary N); xylose → **Kind B**, ring-chain (RDKit tautomer
  canon does NOT collapse it — must resolve via the external anchor, must NOT fall through to a
  connectivity defect). A classifier that reproduces the old audit verdicts (cortisone as
  formula-confirmed-from-SMILES, xylose as connectivity) is WRONG.

**Execution note:** Test-first, driven by the four known-answer rows.

**Patterns to follow:**
- `scorers/*.py` pure-function shape: frame in, `dict` with a `per_row` list out.
- The `adjudicate_necs_misses.py` taxonomy shape recovered in Unit 1
  (`GOLD_DEFECT / GOLD_CONFIRMED / BOTH / NEITHER / UNRESOLVED`).

**Test scenarios:**
- Happy path: cortisone classifies as formula-confirmed wrong-molecule (C21H28O8S vs C21H28O5).
- Happy path: choline classifies as tautomer-or-charge, **not** wrong-molecule — the retracted verdict
  must not reappear.
- Happy path: xylose classifies as tautomer-or-charge — ring-chain, not a sugar swap.
- Edge case: gamma-glutamylvaline classifies as formula-identical wrong-molecule, distinguishing it
  from cortisone's class.
- Edge case: a legacy `"4000"` corrupt cell classifies as `undecidable` with an explicit corrupt-cell
  reason, not as a wrong-molecule defect.
- Error path: a row whose modern SMILES is absent classifies `undecidable`, and the emitted reason says
  which side was missing.
- Positive control: a fixture set containing at least one row per class produces a nonzero count in
  every class, recorded in the artifact as `classifier_positive_control`. A run reporting zero
  unclassifiable rows from an unexercised classifier is indistinguishable from a broken one.
- Integration: the row-selection cardinality is asserted — 691 rows carry both keys, 48 disagree. A
  selector that silently matches zero must fail rather than sail through as success.

**Verification:**
- All four known-answer rows land in their documented class.
- Every class has a nonzero positive-control count.
- The 48/691 count and its reconciliation against 12+58/697 are both recorded in the artifact.

---

- [ ] **Unit 5: Repaired gold column with per-row provenance**

**Goal:** Produce the repaired gold, where each row records which candidate was chosen and on what
evidence (R2), plus the bounded external check that could disconfirm the precedence rule (R2a).

**Requirements:** R2, R2a

**Dependencies:** Unit 4

**Files:**
- Modify: `studies/external_benchmarks/adapters/necs_metabolon.py` (consume the repair in
  `build_input_df`, summarize onto `build_card`)
- Modify: `studies/external_benchmarks/scorers/necs_gold_repair.py`
- Test: `studies/external_benchmarks/tests/test_necs_gold_precedence.py`

**Approach:**
- ⚠️ **Precedence is NOT decided by self-consistency (resolved 2026-08-23, decision #3).** Measured on
  the pinned file: legacy is 97.5% block-1 self-consistent and modern is 99.9%. The old "legacy 0/8"
  was a full-key comparison defeated by legacy's two-block format, not a chemistry failure. Modern's
  99.9% is the fingerprint of a key and SMILES co-derived from one record, so self-consistency carries
  almost no independent signal — and on the 48 disagreeing rows it is a **tie on 30** (both columns
  self-consistent, keys still disagree; xylose and choline are among them). It resolves only 18.
- **Precedence is decided by an INDEPENDENT anchor: the compound name or a non-SMILES-derived ID**
  (pubchem_cid / HMDB / CAS), resolved externally, then compared to each column's key. This is what the
  2026-08-04 gate did. Anchor availability on the 30 tie rows was verified: HMDB 29/30, pubchem_cid
  22/30, CAS 20/30. A row with no usable anchor, or one that resolves ambiguously, is `undecidable` —
  never defaulted to either column.
- **The repair is a total function over all 1,495 rows, not a patch over the disagreeing subset.**
  Enumerate and name every disposition explicitly — connectivity-disagreeing (adjudicated),
  stereo-disagreeing (currently silent in the draft: decide and record), legacy-only-filled,
  modern-only-filled, both-empty, both-agreeing — and require `comparison_rule` to be non-empty on
  every emitted row including pass-throughs. Without this, R2's "rule recorded per row" cannot be
  satisfied for rows that never entered the classifier, and the coverage rise from 796 to 839 happens
  under a third rule that appears nowhere in R1 or R2.
- Assert the dispositions **partition** the row count exactly (they sum to 1,495), and record whether
  the emitted column is single-convention or carries a per-row convention field.
- Provenance columns: the chosen value, the rule applied, the evidence, and the class from Unit 4.
- **State the strictness at which self-consistency is evaluated** — full standard key, the adjudication
  key, or block 1. The draft left this unspecified and it swings which rows are self-consistent, hence
  the precedence outcome.
- Follow the certificate design template: "no evidence" is its own state, and infrastructure failure is
  distinct from a real negative. A row where neither vintage is self-consistent is not the same as a row
  where the check could not run.
- **The external resolution is now the PRIMARY adjudicator for disagreeing rows, not a held-out
  spot-check.** Decision #3 promoted it: self-consistency cannot break the 30 ties, so name/CID
  resolution is what actually decides precedence. It must be name- or CID-anchored, NOT a SMILES
  round-trip. Resolving vendor SMILES
  externally sends the same structure out and gets its key back — that re-confirms the SMILES→key
  transform on a second implementation, i.e. self-consistency again, and cannot detect a wrong
  structure, which is the failure it exists to detect. Anchor instead on the compound *name* or the
  row's `pubchem_cid` (annotation the modern block already carries and which is not derived from the
  SMILES). This is what the 2026-08-04 gate did, and its agreement with the modern column is this
  plan's central evidence.
- `PubChemInChIKeyResolver` exposes only `block_for_pubchem(cid)` and `block_for_hmdb(hmdb)` — no SMILES
  entry point — and returns **first blocks only**, so it cannot verify a `block1 + "-" + block2[:8]`
  precedence rule. Either state that R2a verification is first-block-only and therefore silent on
  stereo-layer precedence, or extend the resolver with a full-key variant.
- Its `_get_txt_inchikey` returns `None` on an empty body, collapsing throttle and no-match into one
  value — the exact conflation the cited learnings warn against.
  `scripts/adjudicate_conflicts.py::name_to_keys` on the recovered branch already implements the
  retry-on-empty-body discipline; reference that rather than rebuilding it.
- A name that resolves ambiguously is **unverified**, never confirmation.

**Test scenarios:**
- Happy path: a row where only the modern vintage is self-consistent selects the modern key and records
  the self-consistency rule.
- Happy path: a row where both vintages agree (one of the 643) passes through unchanged with a
  no-repair-needed rule.
- Edge case: a row where **both** vintages are self-consistent but disagree with each other records an
  explicit unresolved state rather than defaulting to either.
- Edge case: a row where neither vintage is self-consistent is distinguished from a row where the check
  could not run at all.
- Error path: the external verification being unavailable degrades to "unverified", never to
  "verified" or to a silent skip that still emits the artifact.
- Positive control: injecting a row whose modern key contradicts its own modern SMILES must flip that
  row's precedence to legacy — proving precedence is computed, not hardcoded.

**Verification:**
- Every repaired row carries a rule and evidence; no row has a chosen value with an empty provenance.
- The repaired column's coverage is reported against the original's (796 → expected higher, since
  `inchi_key` fills 839).
- The R2a sample either confirms the precedence rule or names the rows where it fails.

---

- [ ] **Unit 6: Offline re-score under both golds**

**Goal:** Report how the NECS headline accuracy and the 134-miss disposition move under the repaired
gold versus the original (R3), with a guard proving the re-score reproduces the persisted baseline
before any delta is trusted.

**Requirements:** R3, R23

**Dependencies:** Units 1, 5

**Files:**
- Create: `studies/external_benchmarks/rescore_necs_gold.py`
- Test: `studies/external_benchmarks/tests/test_rescore_necs_gold.py`
- Reads: the persisted run at `~/benchmark-runs/suite_20260805T033340Z/necs/` (`CHEBI_results.json`
  `per_row`, `necs-metabolon_CHEBI_MAPPED.tsv`, `dataset_card.json`)

**Approach:**
- Clone the shape of `rescore_id_equivalence.py`: module-level pinned source SHA and commit, `main(argv)`
  with `--run-dir`/`--out`, both `.json` and `.md` output, fail loud when the run dir is absent.
- **Reproduction guard first.** Re-derive the persisted baseline (strict 609/796 = 76.5%,
  charge-normalized 624/796 = 78.4%, KG-equivalence-set 668/796 = 83.9%, coverage 1488/1495) and
  require **both** numerator and denominator to match. Matching the numerator alone would falsely
  certify — this is the documented failure mode in the file being cloned.
- Re-scoring joins the repaired gold against the recorded `predicted_block`. No oracle, no Kestrel.
- ⚠️ **Only the strict arm is genuinely offline.** The charge-normalized arm calls
  `oracle.neutral_block(chosen_id)` and the equivalence-set arm calls `oracle.resolved_blocks(chosen_id)`;
  both route through live Kestrel. Only the per-row booleans were persisted, not the prediction-side
  blocks they came from. So those two numbers are either recounted from persisted booleans (a guard
  that cannot fail) or need a live pass. Decide which — see Open Questions — and do not describe a
  recount as a reproduction.
- ⚠️ **The persisted `predicted_block` values are 14 characters — block 1 only.** The repaired gold's
  whole advantage is that `inchi_key` carries a stereo layer, and that layer is discarded at this join.
  State the comparison granularity explicitly rather than calling the join "pure".
- **Abstention must be costly, not free.** Every accuracy figure is emitted as a triple — scored
  numerator, scored denominator, abstained count — never as a bare rate. Report the pessimistic
  convention (all `undecidable` counted as misses) alongside the abstention-excluded figure and treat
  the spread as the measurement's uncertainty. Pre-register a ceiling on `undecidable`; the run fails
  if abstentions exceed the count observed under the original gold. Otherwise accuracy rises
  monotonically with the undecidable count and the plan violates its own rule against reporting a rate
  across the abstention boundary — in its headline number, while forbidding it in a figure.
- **Report the primary delta on the fixed intersection population** (rows scored under both golds).
  The repaired column is expected to fill 839 against the baseline's 796, so ~43 rows enter that the
  baseline never scored, and they are plausibly easier. Add a `newly_covered` decomposition bucket
  alongside the five correction classes, and verify the per-bucket contributions reconstruct the total
  delta exactly.
- **Report the delta decomposed by correction class**, not as a single number. The prior episode's
  "floor" language broke precisely because 10 of 17 corrections were formula-identical convention
  differences. Do not label either direction a floor.
- **Two controls, because the cross-dataset one is weaker than it looks.** The repair lives in
  `necs_metabolon.py::build_input_df` and never executes for LMSD or REFMET, so a flat cross-dataset
  control proves the shared harness is stable but is blind to a defect inside the NECS repair path —
  and blind by construction to the likeliest inflation mechanism, convention alignment (adopting
  three-block keys moves the gold into the predictions' convention, raising match rate without
  correcting a molecule). Keep it, restated honestly as a shared-harness regression check. **Add a
  within-NECS null control**: run the full repair with precedence forced to "always legacy" and assert
  the score does not move from baseline.
- The delta must clear the documented ~1pt run-to-run noise floor on NECS to be reported as a change.
- Establish whether `suite_20260805T033340Z` carries adequate provenance. Its own audit records
  `Publishable: False` and it pins no KG snapshot or ChEBI release. If inadequate, report the delta as
  indicative and flag re-derivation as required rather than quoting it as final.

**Test scenarios:**
- Happy path: re-scoring with the *original* gold reproduces the persisted baseline exactly on both
  numerator and denominator.
- Happy path: re-scoring with the repaired gold produces a delta decomposed by correction class.
- Edge case: a row whose repaired gold is `undecidable` is excluded from the scored denominator, not
  counted as a miss.
- Error path: an absent or malformed run directory fails loud rather than scoring zero rows.
- Positive control: tampering with one persisted `predicted_block` must trip the reproduction guard.
  A guard that cannot fail reads exactly like one that passes.
- **Identity control on the repaired path itself:** feed the repaired-gold scorer a repair result in
  which every row's chosen value is the legacy key, and assert it reproduces the baseline exactly on
  numerator and denominator. The plain reproduction guard only exercises the original-gold path and
  touches no code unique to the repaired branch; tampering with a shared input proves the guard is
  wired, not that the repaired path is correct.
- Error path: a run dir present but carrying no comparable baseline **aborts**. The cloned
  `rescore_id_equivalence.py` sets `sanity = None` and still emits a complete artifact rendering it as
  "n/a" — cloning its shape wholesale imports that defect. The guard must be tri-state and fail-closed.
- Positive control: the flat-control dataset moving must fail the run.

**Verification:**
- The reproduction guard passes against the untouched baseline.
- The delta is reported per correction class, with the noise floor stated.
- Artifacts land in a timestamped directory with source SHAs pinned.

---

- [ ] **Unit 7: Recompute the Unit 0 sizing gate**

**Goal:** State whether the withdrawn Arivale precision claim revives, under both golds (R4), and record
the consequence for Deliverable 2 (R4a).

**Requirements:** R4, R4a

**Dependencies:** Units 1, 5, 6

**Files:**
- Modify: `scripts/adjudicate_conflicts.py` and `scripts/review_probes.py` (recovered in Unit 1) —
  **these, not `llfs_step1_sizing.py`, produced the archived STOP verdict**
- Modify: `scripts/llfs_step1_sizing.py` (the separate LLFS overlap arm, see below)
- Test: `studies/external_benchmarks/tests/test_unit0_gate_recompute.py`
- Reads: `~/external_benchmark_runs/cohort_panels_20260804/UNIT0_GATE_RESULT.md`,
  `conflict_adjudication.csv`, `~/external_benchmark_runs/necs_arivale_baseline_20260804/`

**Approach:**
- ⚠️ **Correction applied after review — the draft named the wrong script.** `UNIT0_GATE_RESULT.md`
  states its scripts are `adjudicate_conflicts.py` and `review_probes.py`, with artifact
  `conflict_adjudication.csv`. `llfs_step1_sizing.py` answers a *different* question (its own docstring:
  "is the NECS <-> LLFS recall arm viable?") and reads a different run directory. **R4's "withdrawn
  Arivale precision claim" is the `adjudicate_conflicts.py` gate.** Recompute that one.
- **Two gates, kept separate.** (a) The NECS/Arivale precision gate via `adjudicate_conflicts.py` —
  this is what R4 asks about. (b) The NECS/LLFS overlap adjudicability gate via `llfs_step1_sizing.py`,
  where `necs_has_structure` lives. Fixing the predicate does **not** touch the Arivale claim.
- **The structure predicate is duplicated.** `review_probes.py::has_struct` carries its own copy of the
  same two-block test. Fix every site, or factor one shared `has_gold_structure(inchikey)` helper into
  `studies/external_benchmarks/scorers/` and have both import it. Add the grep to verification.
- `llfs_step1_sizing.py` reads `~/external_benchmark_runs/scorer_rerun_20260723/necs/...`, a *different*
  run from the `suite_20260805T033340Z` baseline the rest of this plan uses. "Run under both golds"
  requires either regenerating that TSV through the modified adapter or patching the gold column in —
  and the two runs' populations must be asserted to match.
- **The highest-risk edit in the LLFS arm.** `necs_has_structure()` currently returns
  `len(parts) == 2 and len(parts[0]) == 14` — it requires the legacy two-block form and will **silently
  reject every repaired three-block key**, producing a confident gate verdict computed on almost no
  rows. Fix it to accept both forms before running anything.
- Carry forward the mode-ceiling assertion from the original gate: a naive coverage metric read 100%
  because `chosen_kg_id` was non-empty on all 1,495 rows, with 172 collapsing onto the single catch-all
  node `CHEBI:223492`. Count only structure-bearing, non-degenerate resolutions.
- Note that `conflict_adjudication.csv` stores **first blocks only** (14 characters), so its verdicts
  cannot be re-checked from that artifact — full keys and formulas must be re-read from the source file.
- Run under both golds and report both verdicts side by side.
- Record R4a's consequence explicitly: if the claim stays withdrawn, Deliverable 2 proceeds as a
  coverage-plus-refusal deliverable only.

**Test scenarios:**
- Happy path: `necs_has_structure` accepts a three-block standard key.
- Happy path: it still accepts a legacy two-block key.
- Edge case: it rejects the corrupt `"4000"` cells under both forms.
- Positive control: running the gate with the *unfixed* structure predicate over repaired-gold rows
  must produce a visibly degenerate row count — the test asserts the bug is detectable, so a future
  regression cannot pass silently.
- Positive control: a synthetic panel where >50% of rows collapse onto one node must trip the
  mode-ceiling assertion.
- Integration: **assert the gate's underlying quantities, not its verdict label.** The structure-bearing
  row count, the non-degenerate resolution count, and the precision point estimate must each re-derive
  to the archived 2026-08-04 values within a stated tolerance. A sizing gate returns STOP when the
  sample is too small — which is exactly the symptom of the predicate bug this unit exists to fix — so
  asserting the label alone passes *because of* the failure it guards against.
- Negative control: run the recomputation with the **unfixed** predicate and assert the integration
  check *fails*. This proves the check is capable of failing.

**Verification:**
- Both verdicts are recorded, with the row counts each was computed on.
- The original-gold recomputation matches the archived STOP result.
- R4a's consequence is written down either way.

---

- [ ] **Unit 8: Publish the exemplar set**

**Goal:** The primary deliverable — a named, individually checkable artifact a reader can verify from
one published file without running anything (R22a).

**Requirements:** R22a, R23

**Dependencies:** Units 4, 5

**Files:**
- Create: `studies/external_benchmarks/report/necs_gold_exemplars.py`
- Create: `studies/external_benchmarks/results/necs_gold_exemplars.json` (the artifact)
- Modify: `.gitignore` — **only if a CSV/TSV sibling is also emitted.** The existing negations under
  this tree are `!studies/external_benchmarks/results/*.json` and `!studies/external_benchmarks/manuscript/*.json`,
  i.e. JSON only; a `.csv` exemplar would need `!studies/external_benchmarks/results/*.csv` added.
- Test: `studies/external_benchmarks/tests/test_necs_gold_exemplars.py`

**Approach:**
- One row per disagreement: compound name, both candidate keys, both SMILES, formula, the assigned
  class, the precedence rule applied, and the evidence.
- Follow `report/assemble.py` and `report/campaign.py`: markdown generated from a validated results
  bundle, never hand-typed numbers, never auto-published to the wiki.
- **Prose names the artifact field, never restates the value.** The repo has a test enforcing this
  (`tests/test_no_measured_figures_in_prose.py`) with both a positive and a negative control — extend
  the same discipline here.
- **Do not plot a rate across the abstention boundary.** `undecidable` rows are not a denominator
  component in any figure; that is the forbidden claim rendered as a chart.
- `.gitignore` blanket-ignores `*.csv`, `*.tsv` and `*.json`. The artifact needs an explicit `!`
  negation (precedent: `!studies/analysis/results/*.json`) and verification via `git ls-files` that it
  actually landed — `git add <dir>` skips ignored files silently with no warning and no non-zero exit.
- Springer supplement terms apply to MOESM5 content. Check before anything derived from it goes into a
  public figure or dataset.

**Test scenarios:**
- Happy path: the emitted set contains one row per disagreement with every provenance field populated.
- Edge case: an `undecidable` row appears in the set with its reason, rather than being dropped —
  omitting them would flatter the result.
- Error path: generating from an incomplete bundle fails loud rather than emitting a partial set.
- Positive control: a prose line containing a hardcoded measured figure must fail the prose check.
- Integration: the committed artifact is present in `git ls-files` output, proving the `.gitignore`
  negation works rather than assuming it.

**Verification:**
- The artifact is committed and tracked, confirmed by `git ls-files`.
- Every prose number in the report names a field in the emitted artifact.
- A reader can verify any single row against the source file alone.

## System-Wide Impact

- **Interaction graph:** `necs_metabolon.py` feeds `orchestrate_necs()` in `run.py` and the shared
  `structure_oracle_scorer`. Changing the bound gold columns changes what that scorer sees for NECS
  only — no other dataset shares the NECS adapter.
- **Error propagation:** every new guard must fail loud with a message naming the dataset, the number,
  and the likely cause, matching the repo's house style. A guard that no-ops on absent input while the
  artifact-emitting path stays live is the documented failure mode here.
- **State lifecycle risks:** re-scoring reads persisted artifacts under `~/benchmark-runs/` and
  `~/external_benchmark_runs/`. Those must not live inside a disposable worktree —
  `git worktree remove --force` deletes gitignored artifacts and `git status` will not warn.
- **API surface parity:** `validate.spot_check_gold_column` imports Hajjar-hardcoded column constants
  and `orchestrate_necs` never calls `validate_all` at all (there is an explicit stub comment at
  `run.py:233`). This plan does not close that seam, but Unit 2 makes it closable and it should be
  noted for Deliverable 2.
- **Integration coverage:** the adapter → scorer → report chain for NECS should be exercised end to end
  on fixtures, since unit tests on the classifier alone will not prove the repaired column actually
  reaches the scorer.
- **Unchanged invariants:** no change to `src/biomapper2/core/` — the resolver, mapper, and certificate
  are untouched. Other datasets' gold handling is unchanged, which is what makes the Unit 6 flat
  control meaningful.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `necs_has_structure()` silently rejects repaired three-block keys, producing a confident gate verdict on almost no rows | Unit 7 fixes the predicate first and adds a positive control asserting the unfixed version is detectably degenerate |
| The classifier reports clean because it was never exercised on a class it cannot handle | `classifier_positive_control` counts per class, recorded in the artifact; a zero in any class fails |
| A blanket inflator is mistaken for a real correction in the re-score | Unit 6's flat-control dataset must not move |
| The retracted xylose/choline verdicts reappear | Those two rows are acceptance tests in Unit 4, asserted to classify as tautomer-or-charge |
| Working in the shared clone loses uncommitted work to the nightshift harness | Isolated worktree; commit by explicit path; verify HEAD against origin |
| Artifacts silently not committed due to `.gitignore` globs | Explicit `!` negation plus a `git ls-files` assertion in Unit 8 |
| `suite_20260805T033340Z` provenance is inadequate to publish from | Unit 6 establishes this before depending on it; degrade to "indicative" and flag re-derivation rather than quoting as final |
| Reported delta is inside run-to-run noise | The ~1pt NECS noise floor is stated alongside every delta |
| The stranded branch is lost before Unit 1 completes | Unit 1 pushes the branch before any other work begins |
| Abstention buys accuracy — classifying rows `undecidable` inflates the rate for free | Accuracy emitted as numerator/denominator/abstained triple; pessimistic convention reported alongside; pre-registered ceiling on `undecidable` |
| Coverage growth 796→839 is mistaken for chemical correction | Primary delta on the fixed intersection population; `newly_covered` reported as its own bucket |
| Self-consistency precedence is circular if SMILES was derived from the key | Blocking question; R2a re-anchored on name/CID rather than a SMILES round-trip |
| Tautomer canonicalization over-merges, relabelling real chemistry as an encoding artifact | Unit 3 over-merge control on a keto/enol pair and a sugar epimer pair |
| Unit 7's STOP reproduction passes because of the bug it guards | Assert underlying quantities, not the verdict label; negative control with the unfixed predicate |
| Springer terms prohibit per-row redistribution, stranding the primary deliverable | Moved to Unit 1 as a blocking precondition with a written answer and a specified fallback format |

## Documentation / Operational Notes

- Three `docs/solutions/` documents carry NECS numbers that this deliverable may move
  (`benchmark-scorer-defects-...`, `benchmark-miss-disposition-triage-...`, and the partly-retracted
  `adjudicate-benchmark-gold-...`). If the numbers change, all three need updating — and the existing
  retraction should finally be written into the third, where the next reader will find it.
- **Follow-up owner needed:** if Unit 6 moves the NECS numbers, `benchmark-scorer-defects-...` and
  `benchmark-miss-disposition-triage-...` both need updating. That work is deferred to the same separate
  docs PR as the retraction backfill, so all three move together rather than one document being
  corrected while two stay stale.
- A new `docs/solutions/` entry is warranted for the two-annotation-vintage finding: a vendor
  deliverable shipping two mutually contradictory structure columns, with the benchmark bound to the
  wrong one by accidental candidate ordering.
- No deployment, migration, or rollout impact. Nothing runs in CI beyond the new tests; the live
  benchmark workflow is untouched.

## Sources & References

- **Origin document:** [docs/brainstorms/2026-08-22-cross-cohort-eitl-campaign-requirements.md](docs/brainstorms/2026-08-22-cross-cohort-eitl-campaign-requirements.md)
- Source data: Monti et al. 2026, GeroScience, doi:10.1007/s11357-026-02174-2, supplementary file
  MOESM5 (the paper's Table S1), sha256 `365b7cf304529e7cfa1619134d9d11cc9dade28386e9ea3e8b2dc6bc71eb8457`
- Replication artifacts: `~/external_benchmark_runs/monti_string_replication_20260820T182111Z/`
- Prior gate result: `~/external_benchmark_runs/cohort_panels_20260804/UNIT0_GATE_RESULT.md`
- Baseline run: `~/benchmark-runs/suite_20260805T033340Z/necs/`
- Re-score template: `studies/external_benchmarks/rescore_id_equivalence.py`
