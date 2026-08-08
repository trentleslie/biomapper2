---
title: "A dead-but-200 source URL produced a 0-row dataset that surfaced as a misleading pandas join error"
date: 2026-08-06
category: runtime-errors
module: external_benchmarks
problem_type: runtime_error
component: tooling
symptoms:
  - "RuntimeError: SwissLipids primary vocab 'CHEBI' produced no result (mapper failed: \"columns overlap but no suffix specified\") naming lipid_name/gold_inchikey/assigned_ids"
  - "dataset_card.json recorded n_rows: 0, n_scanned: 0, and the run log showed 'Beginning to map dataset to KG (Empty DataFrame ... Index: [])'"
  - "The pinned source_url returned HTTP 200, content-type text/html, size 0 — no 404, no timeout, no error"
root_cause: missing_validation
resolution_type: code_fix
severity: medium
related_components:
  - testing_framework
  - development_workflow
tags:
  - empty-dataset
  - fail-fast
  - misleading-error
  - external-source
  - swisslipids
  - pandas-join
  - exception-swallowing
---

# A dead-but-200 source URL produced a 0-row dataset that surfaced as a misleading pandas join error

## Problem

A benchmark dataset's pinned `source_url` began returning HTTP 200 with a zero-byte body. The streaming adapter read that as a successful empty file and emitted zero rows. The empty frame travelled all the way into the mapper and failed roughly 20 minutes into a 10-dataset suite with a pandas error that named schema columns and pointed at entirely the wrong problem.

## Symptoms

```
RuntimeError: SwissLipids primary vocab 'CHEBI' produced no result (mapper failed:
"columns overlap but no suffix specified: Index(['lipid_name', 'query_source',
'held_out_pubchem', 'gold_inchikey_swisslipids', 'gold_smiles', 'gold_hmdb',
'gold_inchikey', 'has_gold_pubchem', 'assigned_ids'])")
```

- The run log showed `Beginning to map dataset to KG (Empty DataFrame ... Index: [])`.
- `dataset_card.json` recorded `n_rows: 0`, `n_scanned: 0`.
- The pinned source (`SWISSLIPIDS.source_url`, `studies/external_benchmarks/config.py:320`) returned **HTTP 200, `text/html`, 0 bytes**. Not a 404, not a timeout, not an auth failure.
- It was not a wrong filename: `cast=raw`, `file=lipids`, and `file=lipids.tsv.gz` all returned the same empty 200. The endpoint answers anything with nothing, while the site homepage served 8,682 bytes normally.

## What Didn't Work

**Reading the error message literally.** `assigned_ids` is a mapper-internal `Entity` field, so seeing it in the overlap list makes it look like the orchestrator passed too many columns into the mapper. A first pass concluded exactly that, proposed slicing the input columns to match a sibling orchestrator, and **recorded that diagnosis as fact before checking it.** It was wrong.

The reading was seductive because the error is *specific*. It names real, meaningful columns and matches the shape of a genuine join-key defect. But:

```python
>>> import pandas as pd            # pandas 2.3.3
>>> cols = ['lipid_name', 'gold_inchikey', 'assigned_ids']
>>> a = pd.DataFrame({c: [] for c in cols})   # ZERO rows
>>> b = pd.DataFrame({c: [] for c in cols})   # ZERO rows
>>> a.join(b)
ValueError: columns overlap but no suffix specified:
            Index(['lipid_name', 'gold_inchikey', 'assigned_ids'], dtype='object')
```

pandas validates column overlap **regardless of row count**, so two empty frames raise the identical message. The column names were accurate and irrelevant at the same time.

This error is doubly treacherous here, because the repo *does* contain a real unsuffixed-join defect that produces the same message (`src/biomapper2/mapper.py:230`, tracked as issue #49). That one has no live trigger on any current benchmark path and was **not** what fired. Two different causes, one error string.

What actually found it: reading the run log and `dataset_card.json` instead of the exception text, seeing `n_rows: 0`, and tracing backward to the source URL.

## Solution

A fail-fast guard in `studies/external_benchmarks/runner.py`, called from the two entry points the scheduled suite uses (see "Why This Works" for the third, unguarded one):

```python
class EmptyDatasetError(RuntimeError):
    """Raised when an adapter hands the runner a dataset with zero rows.

    A source that yields nothing is a broken run, not a scorable zero. Without this guard the empty
    frame travels into the mapper and surfaces much later as a confusing pandas join error
    (``columns overlap but no suffix specified``) that names schema columns and points at the wrong
    problem entirely — which is exactly what happened to SwissLipids on 2026-08-05, when its pinned
    ``source_url`` began returning HTTP 200 with a zero-byte body.
    """


# ... (~250 lines below in the same file)


def _assert_dataset_nonempty(input_df: pd.DataFrame, config: RunnableConfig) -> None:
    """..."""  # docstring elided; it restates the rationale above
    if len(input_df) > 0:
        return
    source = getattr(config, "source_url", "") or ""
    where = f" Pinned source: {source}" if source else ""
    raise EmptyDatasetError(
        f"{config.key}: the adapter produced 0 rows, so there is nothing to map. "
        f"This is a broken run, not a score of zero.{where} "
        f"Check that the source still serves data — an HTTP 200 with an empty body reads as success "
        f"to a streaming adapter and yields exactly this."
    )
```

Wired into both paths:

```python
def run_all(...):
    vocabs = vocabs or config.target_vocabs
    _assert_dataset_nonempty(input_df, config)
    kg_prov = kg_provenance(probe_live=True)  # read the KG build once per run, share across vocabs
    ...
        except (TrivialMappingError, EmptyDatasetError):
            # Neither is a per-vocab hiccup: both condemn the whole run. Letting the generic handler
            # below catch them would file the failure as one vocab's error and let the others
            # proceed, turning a loud stop into a quiet partial result.
            raise
        except Exception as exc:  # per-vocab isolation (e.g. Kestrel error)
            results[vocab] = VocabRun(vocab=vocab, ok=False, ..., error=str(exc))


def run_vocab(...) -> VocabRun:
    # Also guarded here, not only in run_all, because orchestrate_metabench calls run_vocab directly.
    # Cheap and idempotent when reached via run_all, which has already checked.
    _assert_dataset_nonempty(input_df, config)
```

Verified end-to-end against the still-dead URL: `orchestrate_swisslipids` now raises `EmptyDatasetError` with the pinned source interpolated into the message, immediately, instead of a pandas join error twenty minutes in.

## Why This Works

The root cause is entirely upstream. The harness cannot fix a third party's server; it can only refuse to proceed on empty input and say so while the cause is still obvious.

`run_all` is the path every suite dataset except metabench takes, and `run_vocab` is what `orchestrate_metabench` calls directly, bypassing `run_all`. Guarding `run_all` alone would miss metabench, so both are needed to cover the 10 datasets in the scheduled suite.

**These two are not, however, every place a DataFrame reaches the mapper.** `run_provided_id` (same file) calls `mapper.map_dataset_to_kg` with no guard at all. It is safe today only because the provided-ID datasets sit in `SUITE_SKIPPED` and never run in the scheduled suite. Move one of them back into the suite and this exact failure mode returns, unguarded. Treat "two entry points" as "the two the suite currently uses," not as an exhaustive list.

The re-raise is load-bearing and easy to get wrong. A reviewer proposed placing the guard *only* in `run_vocab`, since that covers metabench with less code. It would have dropped `EmptyDatasetError` out of the do-not-swallow list and downgraded a whole-run stop into one vocab's error entry, for the reason given in the code comment above.

## Prevention

- **An HTTP 200 is not proof of a successful download.** A tolerant streaming adapter reads "status 200 → success" and happily emits zero rows from an empty body. Check response size or post-parse row count against a nonzero floor, not just the status code. Prefer failing on 0 bytes over silently producing an empty dataset.
- **Check the input row count before believing a downstream error.** When a library error names real schema fields, confirm the data is non-empty before accepting the diagnosis it implies. Trace backward from the log, not forward from the exception string. Here, `n_rows: 0` in `dataset_card.json` and `Empty DataFrame ... Index: []` in the log were both sitting in plain sight while the first diagnosis was being written.
- **The same error string can have more than one cause.** `columns overlap but no suffix specified` is produced both by a genuine unsuffixed join (issue #49) and by joining two empty frames. Matching an error to a known defect is a hypothesis, not an identification.
- **Any new "this run is broken" exception must be added to the do-not-swallow list, not merely raised** — otherwise a surrounding per-item handler absorbs it. `test_empty_dataset_error_is_not_swallowed_as_a_per_vocab_error` pins this.
- **Guard "empty," not "small."** A one-row dataset is legitimate. `test_run_all_still_accepts_a_single_row` exists to keep the guard from drifting into a minimum-size check.
- **Watch for vacuous substring assertions in tests.** `HAJJAR.source_url` is `""`, and `"" in msg` is always true, so asserting the error names the source URL against that config would prove nothing. The suite builds a config with a real URL via `dataclasses.replace(HAJJAR, source_url="https://example.invalid/lipids.tsv")` specifically to avoid that trap.

## Related Issues

- Shipped in **PR #48** (`fix/fail-fast-on-empty-dataset`), fix commit `9f8ce3d`, merged as `b3682bc`.
- **Issue #49** — "Latent: unsuffixed pandas `.join()` in `mapper.py` collides when a mapped frame is re-mapped." Related but distinct: same error message, no live trigger, explicitly not the cause of this failure. Filed so it is not rediscovered as a mystery.
- [`integration-issues/github-actions-schedule-trigger-drops-workflow-dispatch-inputs-2026-08-05.md`](../integration-issues/github-actions-schedule-trigger-drops-workflow-dispatch-inputs-2026-08-05.md) — closest companion, same file and same `run_all` call path. Its lesson is the same in shape: a signal that looks like success (a populated-looking provenance field there, a 200 response here) hiding the absence of real data. PR #48's own description calls it "the same failure shape."
- [`best-practices/trustworthy-gates-invoke-test-real-shape-faithful-fallbacks-2026-08-04.md`](../best-practices/trustworthy-gates-invoke-test-real-shape-faithful-fallbacks-2026-08-04.md) — for the principle that a guard is only trustworthy if it is invoked on the real path and cannot be silently absorbed.

## Still Open

`run_provided_id` is still unguarded. It is harmless while provided-ID datasets stay in `SUITE_SKIPPED`, but the guard should be extended there before any of them re-enter the suite.

The URL remains dead (re-checked at time of writing: 200, 0 bytes), and `swisslipids` is still in `SUITE_DATASETS`. It will therefore fail fast and loudly on every scheduled run until it gets a working source or moves to `SUITE_SKIPPED`. That is a deliberate choice of a visible red over a silent omission, but it is a choice worth revisiting if it becomes alarm fatigue. The durable fix is pinning a hosted copy of the TSV rather than depending on a live third-party endpoint for a reproducibility artifact.
