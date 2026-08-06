# Evidence base for preprint §3 — implementation plan (rev 4, split code-now / runs-gated)

Companion to `docs/plans/evidence-base-brainstorm.md`. Read §0 of that document first: four of the
five briefed work items rest on premises the evidence overturns.

> # ⛔ READ THIS BEFORE IMPLEMENTING ANYTHING ⛔
>
> **This plan is split into two parts. Only PART I is in scope for the dispatched PR.**
>
> - **PART I — CODE ONLY. No network calls of any kind.** This is what you implement.
> - **PART II — GATED LIVE COMPUTE. DO NOT EXECUTE. DO NOT SCHEDULE. DO NOT "JUST VERIFY".**
>
> **L29: the automated pipeline never fires live or paid compute against a shared external
> service.** Public Kraken is somebody else's server, it has no rate limiting on either side, and
> the single run this plan is built on returned 42 transient failures whose root cause is *still
> undiagnosed*. Every command in Part II is fired by a human, deliberately, as a supervised step.
>
> If a task seems to need a live call to finish, **it belongs in Part II** — stop and say so rather
> than making the call. Every Part I acceptance criterion is verifiable against a fixture or an
> already-committed artifact on disk. If you find one that is not, that is a bug in this plan;
> report it instead of reaching for the network.

---

## Decisions (all fixed — none reopened)

Rev 2 incorporated an adversarial and a feasibility review; findings that changed the plan are marked
**[R]**. Rev 3 folded in the coordinator's answers, marked **[D]**. Rev 4 applies the code-now /
runs-gated split (L29).

| item | decision | part |
|---|---|---|
| cross-run-provenance | Unified full-suite re-run under final code **and** per-row `git_sha` + `kg_snapshot` columns. Cost approved (L22). | run: **II** · columns: **I** |
| metabench-comparison | Per-item-predictions check first; fall back to the labelled Wilson interval. Coordinate with the floats axis — Figure 2 gates on the same finding (L23). | **II** (web fetch) |
| swisslipids | Dropped. `mapper.py` join defect filed as **issue #49**. | done |
| d0-diagnostic | One live request before building bisect; vary the mojibake in the same request. | **II** |
| bisect-request-budget | Full budget option: ladder disabled inside bisect, request + wall-clock caps, inter-request delay, fail loud at any cap. | build: **I** · exercise: **II** |
| interval-method | Closed-form paired intervals + `independence_family`. | **I** |
| noise-floor | 3 repeats of RefMet only, cache bypassed, labelled a lower bound, baseline arm fresh per A/B. | machinery: **I** · repeats: **II** |
| prereg-d4 + sequencing | Pre-register the test family and correction; branch A off PR #47's head (merged-ready, Greptile 5/5). | declare: **I** · run: **II** |

**Correction carried into the numbers.** The briefed pairing of "LMSD 41.9% systematic" with 255/1500
was an error, acknowledged by the coordinator. Authoritative pairings: LMSD overall 255/1500
(17.0%, ±1.90pt), common_systematic 189/451 (41.9%, ±4.53pt), shorthand 66/1049 (6.3%, ±1.48pt).
The wrong pairing would have been off by more than a factor of two on half-width in print.

---

## Two review findings that were checked and refuted

Recorded so they are not re-litigated.

**"The succeeding datasets may have been requests-cache hits, so the payload-vs-load comparison is
uncontrolled."** The run executed from `/home/trentleslie/worktrees/bm2-live-run`, whose `cache/`
directory and `kestrel_http.sqlite` were **created at 20:33**, four minutes before the run began at
20:37, and last written at 21:44 — exactly the suite's end. The cache was empty at start and
accumulated 7,384 responses during the run. **Every request in the reference run was live.**

The underlying hazard is real for *future* runs and is handled in Part II — a repeat from that
worktree would replay a 346 MB cache and report a flip rate near zero.

**"Aggregate payload bytes, not item count, may explain the 500s."** nlm-gene is **4,390 mentions
totalling ~44 KB**, mean length 10 characters — a tiny payload that failed, versus
MetaboliteAnnotator-positive's 4,314 longer metabolite names that succeeded. Byte size does not
explain the split.

What the check *did* surface, strengthening the content hypothesis: nlm-gene mentions carry
mis-decoded Unicode — `Î³`, `Î±`, `Â\xa0`, `â\x80\x91`, i.e. UTF-8 read as Latin-1. **[R]**

---

# PART I — DISPATCHED. CODE ONLY, NO NETWORK.

Everything below is implementable and fully testable offline. Inputs are fixtures, plus the
**already-committed** reference artifacts under `~/benchmark-runs/suite_20260805T033340Z/`, which are
files on disk and require no calls to produce.

**Branching. [R] Updated — rebase onto the certificate axis's branch, not PR #47's head.**
`tests/test_no_measured_figures_in_prose.py` and `studies/analysis/off_category_audit.py` do not exist
on `dev`, so the guard work is unsatisfiable from a branch cut there. But the certificate axis has
since **rewritten** that guard on `feat/resolution-certificate-impl` (**HEAD `e208107`** — four
commits past the `5bd65fc` first reported; worktree `/home/trentleslie/worktrees/bm2-certificate`),
which already contains #47's version. Branch from there and **rebase rather than resolving by hand** —
see A4. Their offline suite at that head: 842 passed, 216 skipped. PRs go to the personal fork
`trentleslie/biomapper2`, base `dev`, Greptile first.

**Workspace.** Dedicated worktree. `PYTHONPATH=<worktree>/src` is required or `pytest` silently tests
the wrong source. The suite runner (`run_suite`, `SUITE_DATASETS`, the `all` subcommand) lives only on
`origin/dev`.

**Baseline.** `dev` is pre-existing lint-red. State the baseline in the PR body.

**Sequencing within Part I.** Ship **B as one PR after #46 lands** — #46's diff rewrites the header
block immediately above `bulk_kestrel_request` and B1/B2/B3 all edit adjacent lines; three sequential
PRs on one function means two rebases each against a moving `dev`.

---

## A — Make §3 regenerate

No stats module exists in the repo. This closes "no significance test and no confidence interval
anywhere" against §2.6's promise.

### A1. `studies/analysis/stats.py`

> **Path note (see A4):** these two modules live under `studies/analysis/`, **not**
> `studies/external_benchmarks/`. That tree is covered by the rewritten prose guard; the benchmarks
> tree is not. Placing them in `external_benchmarks/` would leave them silently unguarded.

Pure functions, no I/O, no network, seeded, all parameters recorded in the artifact.

- `wilson_interval(k, n, z)`.
- `mcnemar(b, c)` — exact binomial and mid-p. **[R] Define and test behavior at `b + c == 0`**; both
  are undefined there.
- **[R] `tango_paired_difference` / `newcombe_paired_mover`** — closed-form score intervals for the
  difference of *paired* proportions. These are the default, replacing the bootstrap: seed-free,
  stable on the k/1500 lattice, defined at zero discordance, and **coherent with McNemar**, so the
  interval and the p-value cannot contradict each other. A bootstrap CI spanning zero next to a
  McNemar p of 7e-9 is exactly what draws reviewer attention.
- `newcombe_difference(k1, n1, k2, n2)` — *unpaired*, for a published external baseline only, gated
  on the preconditions in A5.
- `paired_bootstrap_difference(..., seed)` — **retained only if a genuinely non-analytic target
  statistic is named** in the artifact. Otherwise drop it, along with `n_resamples` and `seed` from
  the header. Resamples row indices, never the two arms independently.

### A2. `studies/analysis/confidence_report.py`

Reads a suite directory **already on disk** and emits
`studies/analysis/results/confidence_intervals_<suite>.{json,md}`.

**[R] A per-dataset registry, not a generic reader.** The shapes diverge more than one reader can
absorb, and a glob would silently drop a suite dataset:

| dataset | file | shape hazard |
|---|---|---|
| nlmgene | **no `*_results.json` at all** — `unambiguous_accuracy.json` + `ambiguous_flagrate.json` | a `*_results.json` glob drops it silently |
| metaboliteannotator | `<mode>/name_hit_results.json`, per-mode subdirs | per-row key is `hit`, no gold/predicted pair |
| metlinkr | `metlinkr_results.json` | no `per_row` until C4; per-row key is `concordant` |
| lmsd / refmet / srm1950 / necs | `{primary}_results.json` | **3×3**: {overall, common_systematic, shorthand} × {strict, charge-normalized, equivalence-set} |
| hajjar | `{vocab}_results.json` | wrapped `{"structure":…, "paper":…}` |
| hgnc | `{VOCAB}_results.json` | `per_namespace` union, not independent |

Registry is `dataset_key -> (filename_pattern, extractor)` and **raises on an unregistered suite
dataset**. Distinguish that loudly from *"dataset absent from this suite because its run failed"* —
nlmgene, swisslipids and metaboliteannotator-negative are absent from the reference suite, and the
reader must report them as missing rather than skipping or crashing. Silent-skip is the failure mode
this script exists to prevent. `suite_manifest.json` carries no pointer to result files, so the
reader globs per dataset regardless.

Artifact requirements:

- **Saves by default** to a timestamped path, prints where; `--out` is an override.
- **[R] The artifact path is already un-ignored — a second reason the `studies/analysis/` move is
  right.** Verified on **`origin/dev`**, so it is branch-stable and not an artifact of whichever
  branch happens to be checked out: `.gitignore:40` is a blanket `*.json`, and `.gitignore:57` is
  `!studies/analysis/results/*.json`. Confirmed by probe —
  `studies/external_benchmarks/results/probe.json` matches the `:40` blanket rule, while
  `studies/analysis/results/probe.json` is rescued by `:57`. Under the original
  `studies/external_benchmarks/results/` plan the artifact every cited number depends on would have
  been silently un-committed: green locally, absent on a fresh clone. `origin/dev` already tracks the
  `off_category_audit` JSON+MD pair under that negation, which is what establishes the convention.
- **Still assert tracking explicitly** — `git ls-files` the emitted JSON *and* Markdown, with a test
  that fails if either is untracked. **[R] Justified as a regression guard, not a present hazard:**
  there is currently **no `*.md` ignore rule anywhere in the repo**, so the Markdown artifact is not
  at risk today under either path. The test exists so that adding one later cannot silently orphan
  half the artifact. Stating it that way matters — justifying a test with a hazard that is not in the
  tree is the same failure mode this whole standard exists to prevent. The certificate axis was bitten
  by the *real* version of this with a `*.tsv` fixture (now covered by `!tests/fixtures/**/*`), which
  with the earlier pinned-benchmark-data incident makes the `.json` half of this the third recurrence.
- Header pins suite id, `git_sha`, `kg_snapshot`, `biolink_version`, graph census, copied from
  `suite_manifest.json`. `chebi_release` is `"unrecorded"`; record it as-is with `chebi_node_count`
  as fingerprint rather than omitting the field.
- **[D] Per-row `git_sha` + `kg_snapshot` columns on every emitted row** (L22). Free, and it keeps
  the table honest for as long as any row could come from a different run.
- **LMSD emits every regime separately with its labelled core.** Carrying LMSD as one row is exactly
  how the corrected pairing error happens; half-widths differ ±1.90pt vs ±4.53pt.
- Every interval names **which correctness flag** it was computed from. An unlabelled interval on a
  structure-oracle dataset is a silent metric switch.
- **[R][D] Per-row `independence_family` field.** Several rows are *not* independent: RefMet strict
  1319/1500 and equivalence-set 1347/1500 are nested subsets of the same 1500 rows — their Wilson
  intervals overlap heavily and read as "no difference" while the paired truth is b=28, c=0, exact
  McNemar p ≈ 7e-9. Same for NECS and SRM 1950. MetaBench overall is the exact sum of its sub-rows.
  HGNC any-namespace is a union over overlapping subsets. **Emit the strict rate as the primary
  interval and the equivalence-set gain as a paired difference**; mark unions and aggregates derived.
- **[R] `independence_assumption` field + cluster-robust companions.** Wilson assumes independent
  items. LMSD shorthand is 1,049 templated names from homologous lipid series; LMSD and RefMet
  cluster by lipid class; SRM 1950 is a single reference material. Effective n is below nominal n, so
  ±1.48pt on LMSD shorthand is the most over-precise number in the table. Emit a cluster key where
  one exists and a cluster-robust companion; where no clustering is plausible, record that assertion.
- **metLinkR deduplicated companion** in the artifact alongside the file-weighted figure and a
  `weighting_warning`, per the `off_category_audit.py` pattern. **Quote 4.05% deduplicated, never
  9.03%** (L13).
- **[R] State in the artifact that the intervals are marginal, not simultaneous**, and forbid any
  "X exceeds Y" claim derived from non-overlap.

### A3. Tests — `src/`-grade, with real controls

> **Working rule for every test justification in this workstream: when a guard's rationale is a
> hazard, probe the hazard before writing the rationale.** This plan shipped a test justified by a
> `*.md` ignore rule that does not exist in the repo; one `git check-ignore` would have caught it at
> authoring time instead of review time. The rule generalizes past `.gitignore` — before writing
> "this test exists because X can happen," make X happen, or confirm it already has. An unprobed
> hazard produces a test that looks principled and guards nothing, which is the same defect class as
> a restated figure: confident, plausible, and unfalsifiable by reading.

**[R] The originally specified "negative control" was a tautology.** Comparing an array to itself
gives b=c=0 by arithmetic identity; it tests nothing beyond `x == x`, and it is *not* the L7 A-A null.
Split into three:

1. **Identity test** — `x` vs `x` returns zero discordance (arithmetic).
2. **Degenerate-discordance test** — asserts the documented return at `b + c == 0` for McNemar and
   every interval function.
3. **Empirical A-A calibration** — two independent runs of unchanged code. **This is Part II** and
   must not be attempted here.

Plus:

- **Positive control**: McNemar returns significant on a constructed real difference. A suite that
  only asserts non-significance cannot distinguish a working test from a broken one.
- Wilson checked against published reference values at k=0, k=n, small n.
- **Pairing guard**: paired functions *raise* on misaligned arrays. **[R] Assert row-id uniqueness**,
  not just equal length — a join on query name manufactures flips wherever names repeat.
- **Mutation check**: deleting the row-index pairing from any paired function must turn a test red.
  If no test dies, the pairing is untested.
- **Fixture-based end-to-end**: `confidence_report.py` over a small committed fixture suite
  reproducing every shape in the A2 table, including a deliberately-absent dataset.

### A4. **[SUPERSEDED — no `GUARDED_FILES` edit. Put the new modules under `studies/analysis/`.**

The certificate axis rewrote the prose guard on `feat/resolution-certificate-impl` (L31, worktree
`/home/trentleslie/worktrees/bm2-certificate`, HEAD `5bd65fc`). **There is no hand-maintained
`GUARDED_FILES` list any more** — it is derived, fail-closed, from:

- `GUARDED_TREES = ("src/biomapper2/core", "studies/analysis", "studies/shared_gold_set", "tests")`
- `GUARDED_EXTRA_FILES` — `config.py`, `mapper.py`, `models.py`
- `SKIPPED` — 12 documented exemptions, plus a meta-test deleting any skip that outlives its reason

**Rebase onto that branch; do not resolve by hand.**

**[R] The handoff contained one path error, and it matters.** The certificate axis stated that
"`studies/analysis/stats.py` and `confidence_report.py` are now guarded automatically." They would
be — but this plan put them in **`studies/external_benchmarks/`**, which is **not** a guarded tree.
Left as planned, both files would land completely unguarded, which is the exact silent-green failure
the rewrite exists to kill.

**Resolution: put `stats.py` and `confidence_report.py` under `studies/analysis/`, not
`studies/external_benchmarks/`.** This is the right home on the merits, independent of the guard:

- Their nearest sibling is `studies/analysis/off_category_audit.py` — the same species of thing, an
  analysis script that reads a pinned suite and emits a committed artifact.
- They never run a benchmark. They read artifacts that already exist on disk. `external_benchmarks`
  is runner code; this is not.
- It costs zero edits to the certificate axis's file, so the two branches do not collide at all.

New tests are auto-guarded too, since `tests` is a guarded tree.

**[R] Budget a cleanliness pass.** The certificate axis reports the guard caught two restated figures
in its own new files on first run. Write these modules under the rule from the start: comments name
the artifact field, never the value.

**Measured, for whoever picks up the follow-up:** applying the new guard's own `_violations` to
`studies/external_benchmarks/` returns **273 findings across 62 files** (`config.py` alone accounts
for 101). So that tree cannot simply be added to `GUARDED_TREES` — it is a separate cleanup of real
size, and it is currently the largest body of measurement code in the repo sitting outside the
standard. Flagged to the certificate axis; **explicitly not this axis's work.**

Still true, and the reason `studies/external_benchmarks/config.py` should not be individually added:
it carries an unverified MetaBench baseline in a comment *deliberately* flagged needs-verification
with its registry value `None`. Guarding it would turn the suite red for a comment doing the right
thing.

### A5. [R] Bind manuscript numbers to artifact fields

The provenance guard covers source files; **the manuscript is not in this repo** (it lives in the
vault), so guarding `stats.py` — a file that by construction contains no prose numbers — protects a
surface that was never at risk.

Add a reconciliation check shaped like the existing `reconcile_ms1_concordance.py` pin: resolve every
numeric claim in §3 to a named field in `confidence_intervals_<suite>.json`, and fail on any claim
with no resolving field and any artifact field silently renamed. Runs against the committed artifact
and a committed copy of §3 — no network.

### A6. [D] Declare the D4 test family and multiplicity correction

Three competitors × ~7 datasets × multiple vocabularies is plausibly 20–60 McNemar tests; under the
null several clear 0.05. **Declared in this PR as a committed, machine-readable pre-registration
file** — which comparison is primary, what the family is, whether Holm or BH applies — and consumed
by the reporting code. Choosing after seeing output is p-hacking, so the declaration must land
*before* the gated run, which is precisely why it belongs in Part I while the run does not.

---

## B — Harden the client for unattended running

Retry and exponential backoff already exist (`utils.py:175-211`) and are **not** what is missing.
All four items are unit-testable against a fake transport. **Built here, exercised in Part II.**

### B1. Bisect-on-5xx — **[R] in `kestrel_request`, not `bulk_kestrel_request`**

The lower function structurally cannot bisect: it receives an opaque `json` dict and does not know
which key holds the batch (`search_text` for search, `curies` for `/canonicalize` and `/get-nodes`);
its return is `Any`, not necessarily a dict (`/categories` returns a list); and the acceptance
assertion ("999 mapped rows plus one poison item") describes the *higher* function's return. The right
seam is the chunk loop at **`utils.py:256-268`**, which alone has `batch_field`, the chunk list, and
the dict-merge — and which catches the `HTTPError` the lower function raises once its ladder exhausts.

> **[R][D] The bisect code is BUILT here but its diagnosis is confirmed by D0 in Part II.** Build it
> behind a flag, default **off**. Do not enable by default and do not run it live to "check". If D0
> shows a load or timeout condition rather than content-determinism, bisect is a retry storm that
> amplifies the cause, and this code gets deleted rather than shipped.

**[R][D] Budget by request volume, not recursion depth.** Depth is bounded at ~10 by construction and
bounds nothing that matters. The brainstorm's "~10 extra requests" was wrong: bisect composes with the
existing 4-attempt ladder, so one poison item is ~20 nodes ≈ 80 requests plus minutes of sleep, and
*m* independent bad items cost O(m·log(N/m)) nodes — 50 bad items is 800+ requests per chunk per vocab
per dataset. At ~10s per failing request that is hours of load on someone else's service. Implement:

- **The 4-attempt ladder is disabled inside bisect** — at most one retry per node.
- Total extra-request budget per dataset and per suite; wall-clock budget; abort on consecutive-
  failure rate. **Fail loud at any cap.**
- Minimum inter-request delay while bisecting. Sequential is not the same as polite.
- Record every isolated poison payload to a run-local file — the deliverable that turns a failed run
  into an upstream bug report.

**[R] The tests must discriminate, not confirm.** "A fake transport that 500s on exactly one item"
passes under the hypothesis and cannot distinguish it from alternatives. Add fixtures where the
transport 500s on *size* above a threshold and where it 500s *nondeterministically*, and assert the
budget caps fire rather than a storm.

Verified non-issues, stated so a reviewer does not invent them: requests-cache defaults to
`allowable_codes=(200,)`, so 500s are never cached and sub-chunks are fresh keys — bisect and the
cache do not fight. Slice the already-sorted chunk so sub-chunk cache keys stay stable across reruns.

### B2. Default timeout on the mapping path

**[R] Correction:** `kestrel_request` *does* forward `**kwargs` to `session.request`, so `timeout=`
passes today. What is missing is a **default** and callers supplying it — `kestrel_text.py:90-97`,
`linker.py:96-102`, `linker.py:115-122` pass none, while `api/kestrel_discovery.py:86,125` do. The fix
is a default parameter, not kwarg plumbing.

**[R] Size the default from data.** Every failing request took ~10–11s before returning 500 (attempts
at 21:06:23 / :34 / :47 / 21:07:01, minus 1s/2s/4s sleeps). A default below the server's own limit
would convert recoverable 500s into client-side aborts. Derive it from the *successful* request
duration distribution in the committed log and record the chosen value in the manifest.

### B3. Reuse one session

`utils.py:163-168` builds a fresh `CachedSession` per request — new adapter, new pool, no keep-alive.
Most plausible mechanical cause of the `RemoteDisconnected` drops.

**[R]** Lazy-init the global (`_session = None`, build on first use), not at import, so `CACHE_DIR`'s
import-time mkdir and monkeypatching still work. **Ship a `tests/conftest.py` autouse reset in the
same PR** — that tree has *no* autouse fixture today; the one cited elsewhere is under
`studies/external_benchmarks/tests/` and does not cover it. #46 is already adding a second
process-global (`_key_withheld_warned`) here with no reset; B3 makes it three.

Verified: `expire_after` is a per-entry TTL from insertion, so a longer-lived session does **not**
extend staleness. Non-issue.

### B4 + B5. **[R] One plumbing job, not two**

Nothing counts 5xx or dropped connections today. The circulating "22 server errors and 20 dropped
connections" was read off a 2.3 MB log by hand and recounts differently depending on what you count.
Emit per-endpoint counters — retries, terminal 5xx, transient errors, bisect-isolated poison items,
**and `from_cache` hit/miss [R]** — into the manifests.

MetaboliteAnnotator's positive arm completed clean (4 vocabs, `per_row` n=4314) but the dataset reads
`status: "failed"` because the negative arm 5xx'd, so usable public-Kraken data sits outside the
ok-count. The abort fires mid-loop *after* the positive arm's `name_hit_results.json` is on disk —
only the status is wrong.

Three injection points, all required:

1. `build_manifest` (`runner.py:185-194`, `:256-265`) — per-vocab.
2. `run_suite`'s result record (`run.py:1623-1625`) — currently discards everything an orchestrator
   returns except `dataset`, `status`, `out_dir`, `report`. Widen once, for both counters and per-arm
   status.
3. Each `orchestrate_*` returns counters.

**[R] Per-dataset counter reset is mandatory.** `run_suite` runs all ten datasets in **one process**,
so a process-global counter without reset makes every dataset after the first cumulative and wrong —
the identical bug class that `_METAGRAPH_CACHE` needed an autouse fixture for. Test with a fake
two-dataset suite.

---

## C — Offline data-correctness work

### [D] C7 — srm1950 `gold_hmdb` is a row index (L25). **Drop the column.**

Routed from the certificate axis and **independently confirmed against the full
`srm1950_CHEBI_MAPPED.tsv`**: `gold_hmdb` runs `HMDB0000001, HMDB0000002, HMDB0000003, …` in file
order against Cholic acid / Deoxycholic acid / Lithocholic acid. All 1,058 values are unique and the
numeric parts are **exactly the sequence 1..1058**. Cholic acid's real accession is HMDB0000619;
HMDB0000001 is 1-methylhistidine. The column is a row index wearing an accession's format.

Heed the routed gotcha: the `*_f_one_to_many.tsv` subset is filtered and shows gaps that look like
genuine sorted accessions. **Check the full file**, as done here.

**Blast radius is bounded, and this bounds the fix.** `SRM1950` at `config.py:234-252` sets
`gold_chebi_column=""` with the comment that the oracle is the SMILES-derived InChIKey, and scores on
`gold_inchikey_column` / `gold_smiles_column`. `gold_hmdb` appears **only** in
`gold_coverage_columns`, never in the scoring path. Verified: `gold_inchikey` holds 983 well-formed,
genuine keys (cholic acid → `BHQCQFFYRZLCQQ-OELDTZBJSA-N`, correct), and 983 is exactly the
`scored_denominator` of the headline.

So **411/983 = 41.8% strict and 450/983 = 45.8% equivalence-set are structure-scored and are NOT
corrupt.** The corruption is confined to identifier-based coverage reporting off `gold_hmdb` — the
source of the 0.1% precision that read as catastrophic resolver failure. **Retract that figure
explicitly wherever it has circulated**: it was an artifact of a synthetic gold column, not a resolver
result.

**Drop, do not quarantine.** Remove `("HMDB", "gold_hmdb")` from `gold_coverage_columns` and stop
emitting the column from the srm1950 adapter. A quarantined-but-present gold column is a trap for the
next person who greps for a gold identifier; a dropped column cannot be misread.

Add an acquisition-time assertion shaped like the value-level check at `adapters/lmsd.py:181-189`:
**a gold accession column whose numeric parts are unique, monotonic, and equal to `1..n` is a row
index and must fail the run loudly.** The certificate axis ships a generic uniqueness+monotonicity
quarantine guard; this is the srm1950-specific complement and the two should not be merged — theirs
quarantines unknown columns, this one refuses a known-bad one at acquisition.

Re-derive srm1950's coverage figures after the drop from the committed artifact, and record them in
the A2 artifact. **Accuracy needs no re-run.**

### C4 — persist metlinkr `struct_per_row`

Pure code change, no network, so it is Part I. **[R] Smaller than previously stated**: `struct_per_row`
is declared at `scorers/metlinkr_scorer.py:333`, appended at `:389-398`, dropped at the return; the
`structural` dict at `:408-418` already persists a sibling list. It is **one key added**, ~2 lines
plus a test.

**[R] Not sufficient for an A/B on its own**, and the plan must say so: rows carry `concordant` (a
third per-row vocabulary alongside `correct` and `hit`); rows are skipped at `:340,344,351,372,383` so
`len(struct_per_row) != n_rows`; and it is only populated when `struct_available` (`:335`), which is
False on offline paths — **specify and test the nil behavior**.

### Not on the critical path

The latent unsuffixed-join defect at `mapper.py:230,237,242,247` (brainstorm §0.1). No live trigger on
any benchmark path. **[D] Filed as issue #49**; not fixed here.

---

## PART I acceptance — every criterion verifiable offline

1. Wilson and closed-form paired intervals for every metric in the reference suite regenerate from a
   committed script over `~/benchmark-runs/suite_20260805T033340Z/`, with LMSD as separately labelled
   regime rows, `independence_family` and `independence_assumption` on every row, and per-row
   `git_sha` + `kg_snapshot`. **Enforced by the A5 reconciliation check, not by assertion.**
2. No measured figure in any comment or docstring in the files this work owns. **[R] Satisfied by
   placement, not by a list edit**: `stats.py` and `confidence_report.py` land under
   `studies/analysis/` and their tests under `tests/`, both of which the rewritten guard globs
   automatically. Verify by running the guard and confirming both files appear in the derived
   `GUARDED_FILES` — a green suite that never scanned them is the failure mode the rewrite exists to
   kill.
3. **[R] No two dependent intervals are presented side by side as if independent**; nested pairs are
   reported as paired differences; aggregates and unions marked derived.
4. **[D] srm1950's `gold_hmdb` is gone** from the adapter and `gold_coverage_columns`; the
   acquisition-time `1..n` assertion refuses any row-index gold column and is verified red-green
   against a fixture; the 0.1% precision figure is retracted in the PR body.
5. The bisect machinery, budgets, and caps are implemented behind a default-off flag and verified
   against fixtures **including** the size-triggered and nondeterministic cases, with cap-firing
   asserted. **No live call was made.**
6. Timeout default, single session + `tests/conftest.py` autouse reset, and error/cache counters are
   implemented, with per-dataset counter reset verified on a fake two-dataset suite.
7. metlinkr `struct_per_row` is persisted, with nil-path behavior specified and tested.
8. The D4 pre-registration file is committed and consumed by the reporting code.
9. **L13 holds**: the artifact quotes the deduplicated 4.05%, never 9.03%.

---

# ⛔ PART II — GATED: LIVE COMPUTE AGAINST A SHARED PUBLIC SERVICE ⛔
# OUT OF SCOPE FOR THE DISPATCHED PR — DO NOT EXECUTE

**Nothing in this section runs inside the automated pipeline (L29).** Each item is fired by a human as
a supervised step, in the order given, checking the result before proceeding to the next. D6's budget
is approved (L22); **the sequencing is what is gated, not the money.**

Standing requirements for every run below:

- Set `KESTREL_API_URL` explicitly and **verify the manifest fingerprint before trusting any number**.
  This is how 117 prior runs silently hit the internal host. Preferred mechanism is
  `workflow_dispatch` on `.github/workflows/weekly-benchmarks.yml`, which pins the public endpoint at
  line 38 so pinning is structural rather than dependent on operator memory. (Documented gotcha:
  `github.event.inputs.*` is populated only on `workflow_dispatch`, never on `schedule`.)
- Never blend internal-host and public-Kraken numbers in one table or figure.
- Wall-clock estimates are anchored to the reference run (7 datasets in ~71 minutes) and are
  approximate.
- Confirm each subcommand's exact flags against `uv run python -m studies.external_benchmarks.run
  --help` before firing; the command lines below are shape-accurate but the source arguments differ
  per dataset.

### D0 — the diagnostic. **One request. Do this first; everything else depends on it.**

```bash
# Resubmit an archived failing chunk verbatim, cache bypassed. Capture the chunk to a file first
# (reconstructable from the nlmgene / metaboliteannotator-negative pinned inputs), then POST it
# unchanged. Then repeat with the mojibake normalized to proper UTF-8.
KESTREL_API_URL=https://kestrel.krakenkg.com/api \
  uv run python -m studies.external_benchmarks.verify --replay-chunk <chunk.json> --no-cache
```

**[D] Vary the mojibake in the same session if cheap** — a second submission with `Î³`, `Â\xa0`,
`â\x80\x91` normalized.

- **Wall-clock:** seconds. Two requests at most.
- **Produces:** a yes/no on content-determinism, and — if the normalized variant succeeds — the
  *identity* of the poison rather than merely its isolation, which is a far better upstream bug report
  for the Kraken team.
- **Gates:** B1. If the original chunk succeeds, the payload hypothesis is dead and the bisect code
  built in Part I is deleted rather than enabled. **Do not enable bisect before this returns.**

### D1 — MetaboliteAnnotator negative arm (2,509 names)

```bash
KESTREL_API_URL=https://kestrel.krakenkg.com/api \
  uv run python -m studies.external_benchmarks.run metaboliteannotator --out <dir>
```

- **Wall-clock:** ~5–8 min (the positive arm's 4,314 names took ~8 min across 4 vocabs).
- **Produces:** the missing negative arm, plus in-situ validation of B1 and B5's per-arm status.

### D2 — nlm-gene (4,390 mentions)

```bash
KESTREL_API_URL=https://kestrel.krakenkg.com/api \
  uv run python -m studies.external_benchmarks.run nlmgene --source <local BioC dir> --out <dir>
```

- **Wall-clock:** ~8–12 min. **Produces:** `unambiguous_accuracy.json` + `ambiguous_flagrate.json`.
- Best case for the content hypothesis — this is where the mojibake lives.

### D3 — the input-pinning datasets

**These need network fetches for their inputs (supplements, MetaNetX FTP, multi-GB bulk backbones),
which is why they are here and not in Part I** — even though the fetches are not Kestrel calls. Pin
each with a SHA on the dataset card before the mapping run.

- **C1 Hajjar** — no pinned `source_url`; supplement hand-passed via `--supplement`.
- **C2 Pham** — MetaNetX 4.5 FTP *directory* (`chem_xref.tsv` + `chem_prop.tsv`) needing hand
  reconstruction; sentinel `PHAM_NEEDS_RECONSTRUCTION_SENTINEL` at `config.py:908`.
- **C3 provided-id / gene2ensembl** — multi-GB bulk backbones; needs a pinned artifact, not a URL.
- **C5 SwissLipids** — establish a live source or record unavailability with evidence. The pinned URL
  returns a zero-byte 200 across every parameter variant while the site is up. A data-acquisition
  decision, not a code fix; #48 already makes the failure loud.

```bash
KESTREL_API_URL=https://kestrel.krakenkg.com/api \
  uv run python -m studies.external_benchmarks.run pham --source <pinned local artifact> --out <dir>
```

- **Wall-clock:** downloads dominate; mapping ~5–10 min each.

### C6 — MetaBench per-item predictions (**web fetch, no Kestrel**)

A literature/repo check for whether MetaBench released per-item predictions. If they exist over the
same 1000 items, the comparison becomes **genuinely paired** and McNemar is available — strictly
better than every fallback.

- **Wall-clock:** ~30 min, human-driven.
- **[D] Report the result to the floats axis**, which has gated Figure 2 on the same finding (L23).
  Do the check once; do not duplicate it.
- If it comes up empty: publish BioMapper's own Wilson interval **[49.6, 55.8]** beside the published
  point, explicitly labelled "not a significance test," with no difference statistic.
  **Never fabricate an interval for this comparison** (L23).

### D4 — competitor head-to-head (**three external hosted APIs**)

```bash
uv run python -m studies.external_benchmarks.competitors.orchestrate \
  --dataset <curie backbone key> --source <pinned backbone> --out <dir>
```

Already rate-limited at 0.5s (g:Convert) / 1.0s (bioDBnet, UniProt) in
`competitors/orchestrate.py:46-48` and gated behind a Phase-0 liveness check. Runs BioMapper and each
incumbent on **identical rows** with the **identical** scorer — the genuinely paired comparison, and
where §2.6's McNemar belongs.

- **Wall-clock:** dominated by the competitors' rate limits; budget generously.
- **Precondition:** the A6 pre-registration file must already be committed. Firing D4 before the test
  family is declared forfeits the pre-registration.

### D5 — noise floor: 3 repeats of RefMet, cache bypassed

```bash
for i in 1 2 3; do
  KESTREL_API_URL=https://kestrel.krakenkg.com/api \
    uv run python -m studies.external_benchmarks.run refmet --source <pinned> --out <dir>/rep$i
done
```

- **Wall-clock:** ~5 min × 3.
- **[R] Cache must be bypassed and the flag recorded.** Without it, a repeat replays a 346 MB cache
  and reports a flip rate near zero — publishing "the public backend is perfectly stable" from an
  instrument that cannot report its own failure mode. **Without this, D5 must not be run at all.**
- **Produces:** a per-row flip rate, not an accuracy delta. 60 rows flipping correct→wrong and 55
  wrong→correct is a 0.5pt delta and 115 unstable rows.
- **[R] Report b and c separately**, and classify flips into `correct↔wrong` vs `present↔absent` —
  once bisect is enabled the set of dropped rows differs between runs *by construction*, so
  availability noise would otherwise inflate the number with something that is not determinism.
- **[R] Label it measured-on-RefMet; do not apply it as a suite-wide gate.** RefMet at 87.9% has far
  fewer boundary-adjacent rows than LMSD shorthand at 6.3% or SRM 1950 at 41.8%, so its flip rate is a
  lower bound for the suite.
- **[R] Correct use of the A-A control**: it is *not* a threshold below which an A/B flip count means
  nothing. McNemar conditions on b+c, so symmetric noise costs power rather than inflating type-I
  error. Its jobs are to confirm the null asymmetry is calibrated and to give the minimum detectable
  effect at the observed b+c. **Run the baseline arm fresh alongside each A/B** rather than storing a
  constant — a stored rate assumes stationarity and carries a KG-drift confound.
- Report as orthogonal to the Wilson intervals, never as a substitute: Wilson covers sampling error
  over items, the flip rate covers backend non-determinism over the same items.

### D6 — [D] the unified full-suite re-run. **The source of every published §3 number.** (L22)

```bash
KESTREL_API_URL=https://kestrel.krakenkg.com/api \
  uv run python -m studies.external_benchmarks.run all --out <dir>
```

- **Wall-clock:** ~71 min for the 7 previously-completing datasets; expect longer with the restored
  datasets — budget ~2 hours.
- **Precondition:** runs **last**, after C is complete and B is merged, so every dataset is runnable
  and the whole table shares one `git_sha` and one `kg_snapshot`.
- **Produces:** the single coherent suite that §3 is computed from. **D0–D5 are diagnostic and
  enabling; only D6's output is published.** That deliberately lowers the stakes on a partial D1–D3
  failure (it costs information, not a table row) and raises them on D6.
- **[D] Cost approved.** Sequencing is gated; the budget is not.

### LMSD — expect red, check the census before calling it a regression

**LIPID MAPS is absent from the public build** (confirmed via `/metagraph`), and `orchestrate_lmsd`
enforces a regime-strict capability floor (`regression_floor = 0.90` on `shorthand`,
`scorers/regression.py:35`) that raises `ValueError` and never passes on blended coverage. A red LMSD
is more likely backend composition than a code regression.

---

## PART II acceptance (verifiable only after the gated runs)

- Every live run's manifest records `https://kestrel.krakenkg.com/api`, fingerprint verified before
  any number is quoted.
- §3 rests on the D6 unified re-run under final code **and** every §3 row carries its own `git_sha`
  and `kg_snapshot` (L22) — both, not either.
- Significance testing is present where pairing genuinely exists (D4, A/B gate) and explicitly absent,
  with the reason recorded, where it does not.
- D4 was fired only after the A6 pre-registration was committed.
- The noise floor is an artifact field, labelled measured-on-RefMet, with b and c reported separately
  and the cache-bypass flag recorded.

---

## What this axis will not do

- **Not re-pin the backend default.** PR #46 already flips `config.py:21` to public and adds a
  credential guard. Depend on it. (After #46, `weekly-benchmarks.yml`'s
  `KESTREL_API_KEY: 'public-kraken-no-auth'` default becomes dead config.)
- **Not bootstrap the MetaBench 52.7-vs-40.9 gap.** The 40.93% is unverified, its registry value is
  `None` pending transcription, and it is a published aggregate with no per-row data — no pairing for
  McNemar or a paired bootstrap. **[R] Transcription clears only one of three blockers**; the
  denominator problem is arithmetic, since 40.93% is unattainable on n=1000 (nearest 409/1000 =
  40.9%), and Newcombe assumes two independent binomials estimating the *same* estimand.
- **Not slice SwissLipids' input columns.** No join collision to fix; the source is dead.
- **Not add throttling as a general measure** — the pipeline is strictly sequential. **[R] But B1's
  budgets and inter-request delay are not optional**, because bisect changes request *volume*, which
  is what a shared unrated service actually cares about.
- **Not fix the latent `mapper.py` join defect.** Real, no live trigger. **Issue #49.**
- **Not re-run srm1950 for accuracy.** Its 41.8% / 45.8% are structure-scored on genuine InChIKeys
  and survive the `gold_hmdb` corruption; only coverage figures are re-derived (C7).
