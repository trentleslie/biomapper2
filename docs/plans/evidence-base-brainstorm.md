# Evidence base for preprint §3 — brainstorm

Axis: `evidence-base`. Project: BioMapper preprint (biomapper2).
Reference run: `~/benchmark-runs/suite_20260805T033340Z/` (public Kraken, `kraken 2.0.1 (14683250n/92233909e)`, biolink `4.2.5`, `git_sha d059564`, `kg_stable_during_run: true`).

Goal: every §3 number comes from one backend, one graph snapshot, one provenance manifest — and carries an interval.

---

## 0. Premise corrections found during investigation

Four of the five briefed work items rest on premises the evidence does not support. Each correction
is stated with the artifact that establishes it, so it can be re-checked rather than believed.

### 0.1 The SwissLipids failure is a dead upstream source, not a join collision

Briefed as: "a pandas overlap-without-suffix inside the mapper where the overlap includes
`assigned_ids`… the obvious fix (slice input columns) risks LEAKING GOLD. Treat that as the primary
hazard."

Evidence: open PR #48 (`fix/fail-fast-on-empty-dataset`) already diagnosed this. The pinned
SwissLipids `source_url` returns **HTTP 200 with a zero-byte body**; `cast=raw`, `file=lipids`, and
`file=lipids.tsv.gz` all return the same empty 200. The adapter reads that as a successful empty
file and emits zero rows; `dataset_card.json` recorded `n_rows: 0`. The pandas message is simply
what joining two zero-row frames produces — pandas validates column overlap regardless of row
count. **The column names in the error, `assigned_ids` included, are a red herring.**

An independent trace of the whole SwissLipids path corroborates this: `bundle.input_df` never
carries an `assigned_ids` column (the adapter emits a fixed 8-column list at
`adapters/swisslipids.py:109-121`), `SWISSLIPIDS.target_vocabs` has one entry so the mapper is
called once, and no annotator overrides `prepare()`, so the caller's frame is never mutated. There
is no live trigger for a column collision on this path.

Consequence: performing the briefed fix would have been actively harmful — it would have masked a
dead data source behind a code change and disturbed the leak surface for no reason. What SwissLipids
actually needs is a live pinned source, or an evidenced "unavailable" record.

**Three things the same trace turned up that are worth keeping**, none of which was the briefed
problem:

1. **A real latent join defect one line up.** `src/biomapper2/mapper.py:230` is
   `df = df.join(annotation_df)` — no `on=`, no `how=`, no `lsuffix`/`rsuffix`; `annotation_df` is
   the single-column `assigned_ids` frame from `core/annotation_engine.py:256`. Three sibling joins
   at `mapper.py:237,242,247` share the defect with their own collision keys, and `lsuffix` /
   `rsuffix` / `suffixes=` appear **zero times** anywhere in `src/`, `studies/`, or `tests/`. It
   fires whenever a frame already carrying mapper-output columns is fed back into
   `map_dataset_to_kg` — re-mapping a `*_MAPPED.tsv`, for instance. Also at `mapper.py:189`,
   `df = dataset` is a bare alias with no `.copy()`.

2. **The anti-trivial guard is near-vacuous on this path** — correcting an assumption I made before
   checking. `TrivialMappingError` (`runner.py:32`, raised at `:247`) tests
   `stats["mapped_to_kg_assigned"] > 0` on the mapper's *output*, so it is indifferent to how many
   input columns you pass. But `run_vocab` hardcodes `provided_id_columns=[]` and
   `annotation_mode="all"` in name-input mode, which makes every mapping "assigned" by construction.
   The guard therefore holds for any run that maps a single row. It detects exactly one failure mode
   — gold leaking in *through* `provided_id_columns` — which the runner makes structurally impossible
   here. **It would not catch gold columns riding along as inert passthrough**, which is what
   SwissLipids does today: `run.py:718` hands all five `gold_*` / `held_out_*` columns to the mapper.
   They are never read (not in `provided_id_columns`, not the `name_column`), but nothing asserts it.
   The nearest precedent for such an assertion is value-level, not column-level:
   `adapters/lmsd.py:181-189`.

3. **Where the gold-leak hazard actually lives.** It is not in slicing; it is in the *re-attach*.
   `orchestrate_swisslipids` reads `held_out_pubchem` back off the mapper's **output** frame
   (`run.py:729-734`, `:740-742`), so slicing the input without an nlmgene-style re-attach raises
   `KeyError` in `cross_source_gold.py:55`. And a careless re-attach is worse than a loud failure:
   `pd.merge` with unsuffixed overlaps **silently renames to `_x`/`_y`** rather than raising the way
   `.join` does, so re-attaching a whole frame would produce `assigned_ids_x`/`assigned_ids_y` and
   quietly break the structure oracle downstream. nlmgene's pattern is the safe one and is narrower
   than "slice input columns": it slices out only the partition label and re-attaches exactly two
   columns by name (`run.py:1453`, `:1466-1467`), leaving the join overlap equal to the join key.

### 0.2 Retry and exponential backoff already exist, ran, and did not help

Briefed as: "Throttling/backoff is required before anything runs unattended."

Evidence: `src/biomapper2/utils.py:175-211` implements bounded exponential retry —
`max_retries=3`, `retry_backoff_base=2.0`, so 4 attempts at 1s / 2s / 4s, with 5xx retried and 4xx
raised immediately. The run log shows it firing and exhausting:

```
21:06:12  Batching 2509 items into 3 chunks of 1000 for hybrid-search
21:06:23  Kestrel API 500 on hybrid-search (attempt 1/4); retrying in 1.0s
21:06:34  Kestrel API 500 on hybrid-search (attempt 2/4); retrying in 2.0s
21:06:47  Kestrel API 500 on hybrid-search (attempt 3/4); retrying in 4.0s
21:07:01  ERROR - Kestrel API HTTP error (hybrid-search): 500 Server Error
```

More backoff cannot help a deterministic failure. Four attempts already failed identically.

### 0.3 The 500s are payload-triggered, not load-triggered

The pipeline has **zero concurrency**: suite→dataset, dataset→vocab, vocab→annotator, and
bulk-call→chunk are all sequential `for` loops. One request is in flight at a time. So there is
nothing to throttle, and a semaphore or rate limiter would be solving a problem that does not exist.

The failures are also not a global outage, and not chunk size alone:

| time | dataset | shape | outcome |
|---|---|---|---|
| 20:51 | metaboliteannotator **positive** | 4314 → 5 chunks of 1000 | **ok** |
| 21:06–21:09 | metaboliteannotator **negative** | 2509 → 3 chunks of 1000 | **500 × 4 vocabs** |
| 21:11–21:13 | metlinkr | 1437 → 2 chunks of 1000 | **ok** |
| 21:20 | nlmgene | 4390 → 5 chunks of 1000 | **500** |

A *larger* payload succeeded 15 minutes before a smaller one failed, and a third dataset succeeded
*between* the two failures. The two datasets that fail are the two with unusual query text: the
MetaboliteAnnotator **negative** arm (deliberately unmappable/adversarial names) and **nlm-gene**
(gene mentions extracted from BioC full text). The working hypothesis is that specific query strings
crash `hybrid-search` server-side.

The right response is **bisect-on-5xx**, not backoff: on a 500, split the chunk and retry the halves.
A single poison item then costs ~log2(1000) ≈ 10 extra requests and loses 1 row instead of 1000 —
and it *isolates the offending payload*, which is the thing worth sending to the Kraken team. It is
also gentler on the shared service than the current 4× full-chunk retry.

Two genuine hardening gaps do exist alongside it, and they matter more for unattended running than
backoff does:

- **No timeout on any Kestrel mapping request.** `bulk_kestrel_request` passes no `timeout=`, and
  `kestrel_request` never forwards one. A hung backend hangs an unattended run indefinitely.
  (Discovery paths set `timeout=10`; the mapping path sets nothing.)
- **A fresh `CachedSession` is constructed per request** (`utils.py:163-168`) — new adapter, new
  urllib3 pool, no keep-alive reuse. This is the most plausible mechanical cause of the
  `RemoteDisconnected` drops.

### 0.4 The error counts in circulation do not reproduce

"22 server errors and 20 dropped connections" cannot be regenerated: **no code counts them.** There
is no counter and no manifest field; the numbers were read off the log by hand. A recount gives 15
retry warnings, 5 terminal 500s, and 3 top-level `ConnectionError`s — different numbers depending on
what you choose to count.

This is precisely the class PR #47 exists to eliminate: a measured figure that lives only in prose.
The fix is to emit request-level counters into the manifest so the number regenerates.

### 0.5 The MetaBench "52.7 vs 40.9" gap does not support a bootstrap CI

Registered from the manuscript axis as: "A bootstrap CI on the MetaBench 52.7-vs-40.9 gap."

Evidence, from `studies/external_benchmarks/config.py:665-673` — the 40.93% is **explicitly marked
unverified in the codebase**, and every baseline value is deliberately set to `None` pending human
transcription from the paper's table:

> the paper's headline (UNVERIFIED, read from the arXiv HTML during acquisition, MUST be re-checked
> against the source table before any is asserted) … a web-search-augmented run reaches at most
> ~40.93%. Do NOT bake those numbers as fact here.

Three independent blockers, in increasing severity:

1. The value is unverified and its own registry entry refuses to assert it.
2. It is a **published aggregate from another system's run**. There are no per-row results for it,
   so there is no pairing — which rules out both McNemar (needs the discordant cells) and a paired
   bootstrap (needs per-row indices).
3. Its denominator and protocol are not established as the same 1000 rows we score.

Bootstrapping a point estimate of unknown provenance against our per-row data would manufacture a
confidence interval for a comparison that was never measured. That is the Metabolon-96.5% failure
shape exactly (see the memory note: a headline with no backing artifact).

**What is legitimately available instead**, and is strictly better:

- A **Wilson interval on BioMapper's own 527/1000** — already computed below, no re-run.
- After a human transcribes the MetaBench table: a **two-proportion (Newcombe) interval on the
  difference**, correctly labelled as an unpaired comparison against a published figure.
- **Genuine McNemar** on the competitor head-to-head, which *is* paired: `orchestrate_competitors`
  (`competitors/orchestrate.py:52`) runs BioMapper and each incumbent on the **identical rows**
  (`bundle.input_df`, same held-out gold) and scores everyone with the **identical** `score_curie`.
  Every scorer emits `per_row`. This is where §2.6's promised McNemar's test belongs.

---

## 1. What the reference run actually establishes

Seven datasets completed on public Kraken. All counts below were read from the committed result
JSONs, not from any summary prose.

| metric | artifact | k/n | rate |
|---|---|---|---|
| HGNC any-namespace | `hgnc/ENSEMBL_results.json` → `comparable_core` | 1442/1496 | 96.4% |
| HGNC → ENSEMBL | `hgnc/ENSEMBL_results.json` → `per_namespace.ENSEMBL` | 1106/1399 | 79.1% |
| HGNC → NCBIGene | `per_namespace.NCBIGene` | 1441/1475 | 97.7% |
| HGNC → UniProtKB | `per_namespace.UniProtKB` | 594/643 | 92.4% |
| RefMet strict | `refmet/CHEBI_results.json` | 1319/1500 | 87.9% |
| RefMet equivalence-set | same, `comparable_core_kg_equivalence_set` | 1347/1500 | 89.8% |
| NECS strict | `necs/CHEBI_results.json` | 609/796 | 76.5% |
| NECS equivalence-set | same | 668/796 | 83.9% |
| MetaBench overall | `metabench/metabench-grounding_results.json` | 527/1000 | 52.7% |
| SRM 1950 strict | `srm1950/CHEBI_results.json` | 411/983 | 41.8% |
| LMSD overall | `lmsd/CHEBI_results.json` | 255/1500 | 17.0% |
| LMSD systematic | same, `by_name_source_regime.common_systematic` | 189/451 | 41.9% |
| LMSD shorthand | same, `by_name_source_regime.shorthand` | 66/1049 | 6.3% |

### 1.1 A numerator/denominator mismatch in the briefed Wilson inputs

The brief pairs "LMSD 41.9% systematic" with the count "LMSD 255/1500". Those belong to **different
rows of the table above**: 255/1500 is the *overall* rate (17.0%), while 41.9% is the
*common_systematic* regime at 189/451. Computing a Wilson interval on 255/1500 and labelling it
"systematic" would put a 17.0% interval under a 41.9% headline.

The interval widths are also materially different — ±1.90pt for the overall rate versus ±4.53pt for
the systematic regime — so the error is not cosmetic. LMSD must be carried as **three separate
(k, n) pairs**, never one.

This is the strongest argument for the whole workstream: the mismatch is invisible in prose and
obvious the moment the numbers are regenerated from the artifact.

### 1.2 Three datasets failed, three were skipped — and the reasons differ in kind

| dataset | status | real blocker |
|---|---|---|
| metaboliteannotator | failed | 5xx on the **negative** arm only. The positive arm completed clean (4 vocabs, `per_row` n=4314) and its artifacts are on disk — but the suite marks the whole dataset failed, so clean data sits outside the ok-count. |
| nlmgene | failed | 5xx |
| swisslipids | failed | dead upstream source (§0.1) |
| hajjar | **skipped** | "no pinned `source_url`; the supplement is hand-passed via `--supplement`" |
| pham | **skipped** | "source is a MetaNetX FTP path requiring hand reconstruction" |
| provided-id | **skipped** | "needs a pinned artifact, not a URL" |

The three *skipped* datasets are blocked on **input pinning, not backend availability**. That work is
free, offline, and can be completed before any backend time is spent — which changes the sequencing:
pin first, then run, rather than treating all six as one live-compute problem.

### 1.3 The per-row surface exists, with one gap

Every scorer emits a `per_row` array inside its `*_results.json`, carrying the correctness flag. This
is what makes the L7 per-row A/B gate and a paired McNemar possible at all.

One exception: **metlinkr builds `struct_per_row` in the scorer but never persists it**
(`scorers/metlinkr_scorer.py:333,389`). metlinkr cannot participate in a per-row gate until that
array is written out — a small, offline, no-backend-cost change.

Two shape hazards for any A/B comparison:

- Structure-oracle datasets (refmet, lmsd, srm1950, necs) carry **three** correctness flags —
  `correct`, `charge_normalized_correct`, `kg_equivalence_set_correct`. An A/B that does not pin
  which one it compares will silently compare different metrics across runs.
- MetaboliteAnnotator's flag is `hit`, not `correct`, and it has no gold/predicted pair.

---

## 2. Wilson intervals — computed, from the artifacts

Wilson score interval, 95%, no continuity correction. Pure arithmetic over the counts in §1; no
re-run, no backend call. All seventeen reproduce.

| metric | k/n | rate | 95% Wilson | ± |
|---|---|---|---|---|
| HGNC any-namespace | 1442/1496 | 96.4% | [95.3, 97.2] | 0.95pt |
| HGNC → ENSEMBL | 1106/1399 | 79.1% | [76.8, 81.1] | 2.13pt |
| HGNC → NCBIGene | 1441/1475 | 97.7% | [96.8, 98.3] | 0.77pt |
| HGNC → UniProtKB | 594/643 | 92.4% | [90.1, 94.2] | 2.06pt |
| RefMet strict | 1319/1500 | 87.9% | [86.2, 89.5] | 1.65pt |
| RefMet equivalence-set | 1347/1500 | 89.8% | [88.2, 91.2] | 1.53pt |
| NECS strict | 609/796 | 76.5% | [73.4, 79.3] | 2.94pt |
| NECS equivalence-set | 668/796 | 83.9% | [81.2, 86.3] | 2.55pt |
| MetaBench overall | 527/1000 | 52.7% | [49.6, 55.8] | 3.09pt |
| MetaBench KEGG | 303/400 | 75.8% | [71.3, 79.7] | 4.19pt |
| MetaBench HMDB | 69/400 | 17.2% | [13.9, 21.3] | 3.70pt |
| MetaBench CHEBI | 155/200 | 77.5% | [71.2, 82.7] | 5.76pt |
| SRM 1950 strict | 411/983 | 41.8% | [38.8, 44.9] | 3.08pt |
| SRM 1950 equivalence-set | 450/983 | 45.8% | [42.7, 48.9] | 3.11pt |
| LMSD overall | 255/1500 | 17.0% | [15.2, 19.0] | 1.90pt |
| LMSD systematic | 189/451 | 41.9% | [37.4, 46.5] | 4.53pt |
| LMSD shorthand | 66/1049 | 6.3% | [5.0, 7.9] | 1.48pt |

These are shown here to demonstrate the arithmetic reproduces. The deliverable is the **script and
its committed artifact**, not this table — per the provenance standard, prose names the field.

### 2.1 A consequence worth stating up front

The narrowest interval is ±0.77pt and the widest ±5.76pt. The "~1pt run-to-run noise floor" figure
in circulation is **inside the sampling interval of nearly every dataset**. That does not make the
noise floor uninteresting, but it does mean the two quantities answer different questions and must
not be conflated:

- The Wilson interval covers **sampling error over items** — would a different 1500-row subsample
  give this rate?
- The repeat-run experiment covers **backend non-determinism over the same items** — would the same
  1500 rows score the same tomorrow?

They are orthogonal. Reporting one as though it bounded the other would be wrong in both directions.

---

## 3. Designing the noise floor experiment properly

The registered request is a repeat-run on the public backend to establish a run-to-run noise floor,
because the ~1pt figure was measured on the internal host and cannot be reported.

**Measure the per-row flip rate, not the accuracy delta.** An accuracy delta is a lossy summary of
run-to-run instability: 60 rows flipping correct→wrong and 55 flipping wrong→correct shows up as a
0.5pt delta while representing 115 unstable rows. The flip rate is the honest quantity, it is far
more sensitive, and — critically — it is *the same measurement the L7 A/B gate makes*. Building it
once serves both.

That also supplies the A-A null control L7 requires: **a repeat run of the unchanged code IS the A-A
control.** Its flip rate is the threshold below which an A/B flip count means nothing. Designing
these as one experiment rather than two is the main efficiency available here.

Scope: repeats of **one** mid-cost dataset with a large per-row surface, not the whole suite. RefMet
(1500 rows, `per_row` complete, ~1 vocab) is the natural candidate. Three repeats give a range; two
give only a difference.

---

## 4. Shape of the work

Ordered so that everything free and offline lands before any backend time is spent.

**A — Make §3 regenerate (offline, zero backend cost).**
A new `stats` module (Wilson, McNemar exact/mid-p, paired bootstrap) plus a report script that reads
a suite directory and emits a committed `confidence_intervals_<suite>.{json,md}` artifact. Ships with
a positive control (must detect a real difference), a negative control (an A-A comparison must come
back non-significant), and the LMSD three-regime split. No stats module exists in the repo today.

**B — Harden the client for unattended running (offline-testable).**
Bisect-on-5xx; an explicit timeout on the mapping path; one reused session; request-level error
counters written into the manifest. All four are unit-testable against a fake transport with no live
calls. A production-quality `RateLimiter` and `with_retries` already exist at
`competitors/base.py:133-212` and are not reused by `src/` — worth harvesting rather than rewriting.

**C — Pin the inputs (offline, unblocks the runs).**
Hajjar supplement, Pham MetaNetX reconstruction, provided-id backbone → pinned artifacts with SHAs.
Persist metlinkr's `struct_per_row`. Establish a live SwissLipids source or record its unavailability
with evidence. Note the `.gitignore` hazard: blanket globs have already silently excluded pinned
benchmark data once, so every committed artifact needs an explicit negation.

**D — Live runs (gated, sequenced, costed).**
Cheapest-first, because the first run doubles as the validation of B: metaboliteannotator-negative
alone is 2509 names and directly exercises the bisect fix. Then nlmgene, then the newly pinned
datasets, then the competitor head-to-head (three live external APIs, already rate-limited), then the
repeat runs.

**E — Backend pinning is already solved; depend on it, do not duplicate it.**
`config.py:21` does default to the internal host — but open PR #46 (`chore/default-public-kestrel-kg`)
already flips the default to public *and* adds a credential guard so a stale `KESTREL_API_KEY` is
never sent to the third-party host. Separately, `.github/workflows/weekly-benchmarks.yml:38` already
pins `KESTREL_API_URL` to public Kraken for scheduled runs. Running via `workflow_dispatch` on that
workflow enforces backend pinning structurally rather than relying on operator memory — which is what
allowed 117 prior runs to hit the internal host silently.

---

## 5. Constraints carried into planning

- **Provenance standard.** `tests/test_no_measured_figures_in_prose.py` scans an explicit
  `GUARDED_FILES` tuple (currently 19 files, none under `studies/external_benchmarks/`). Comments
  and docstrings may not contain 3+ digit numbers, comma-grouped numbers, or any percentage;
  identifiers, semver, SHAs, and text inside double backticks are stripped first. Values belong in
  code or in a regenerable artifact.
- **Analysis code that backs a published claim needs `src/`-grade coverage and a positive control.**
  A zero from an unexercised instrument is indistinguishable from a broken instrument.
- **Never blend internal-host and public-Kraken numbers** in one table or figure.
- **metLinkR is 5x file-weighted** (five replica target-vocab files, 904 unique commits counted as
  1,412). Any aggregate needs a deduplicated companion emitted *in the artifact*, not disclosed in
  prose. Quote the deduplicated rate.
- **LIPID MAPS is absent from the public build**, so LMSD/SwissLipids degradation is more likely
  backend composition than code regression. `orchestrate_lmsd` enforces a regime-strict capability
  floor that raises `ValueError` and never passes on blended coverage.
- **Baseline is pre-existing lint-red**: dev carries ruff errors and `KESTREL_API_KEY`-dependent test
  failures. State the baseline so "tests pass" is not read as a claim the branch cannot support.
- **Worktree gotcha**: the shared venv's editable install points at the main checkout, so plain
  `pytest` in a worktree silently tests the wrong source. `PYTHONPATH=<worktree>/src` is required.
  Related: the suite runner (`run_suite`, `SUITE_DATASETS`, the `all` subcommand) exists only on
  `origin/dev`, not on the current checkout.
- **Three PRs are open, not one**: #46 (public Kestrel default), #47 (provenance standard),
  #48 (fail fast on empty dataset / SwissLipids). Branch off `dev`; rebase as they land.
