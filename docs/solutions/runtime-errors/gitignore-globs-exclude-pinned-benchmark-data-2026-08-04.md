---
title: "Pinned benchmark data files silently gitignored, breaking package import on fresh checkout"
date: 2026-08-04
category: runtime-errors
module: biomapper2
problem_type: runtime_error
component: development_workflow
symptoms:
  - "FileNotFoundError on import from a fresh clone/checkout (gold.py opens suhre2010_canonical.csv at module load; the KEGG loader opens kegg_compound_pathway.tsv)"
  - "Local pytest passed (35 tests) because untracked data files still existed on disk in the working tree"
  - "git add studies/northstar_e2e silently skipped the ignored .csv/.tsv files with no warning or error"
  - "git ls-files studies/northstar_e2e/data/ returned empty — code tracked, data not"
  - "Greptile reviewer running against a fresh PR checkout caught the missing data (P1: required benchmark data is absent)"
root_cause: config_error
resolution_type: config_change
severity: high
related_components:
  - testing_framework
  - tooling
tags:
  - gitignore
  - git-add
  - fresh-checkout
  - benchmark-data
  - package-data
  - filenotfounderror
  - git-archive
---

# Pinned benchmark data files silently gitignored, breaking package import on fresh checkout

## Problem
A new study package (`studies/northstar_e2e/`) was committed with its code but not its two required pinned data artifacts, because the repo-wide `.gitignore` globs `*.csv`/`*.tsv` caused `git add <dir>` to silently skip them. The package imports fine locally (the files exist untracked in the working tree) but raises `FileNotFoundError` on any fresh checkout, clone, or `git archive` export.

## Symptoms
On a fresh checkout / clone (what a reviewer or CI sees):
- `FileNotFoundError` at **import time** from `gold.py` (it builds `GOLD_METABOLITES` by opening `data/suhre2010_canonical.csv` at module load) and from the KEGG loader (`data/kegg_compound_pathway.tsv`).
- `git ls-files studies/northstar_e2e/data/` returns **empty** — the code is tracked, the data is not.
- Greptile flagged it P1 ("required benchmark data is absent") with reproduction artifacts, having run the PR against a fresh checkout.

## What Didn't Work
- **Trusting the green local test run.** All 35 offline tests passed locally — but only because the untracked data files still sat in the working tree. Local pytest reads the *working tree*, not the git index, so a passing local run says nothing about whether the *committed* package is complete.
- **`git add studies/northstar_e2e` gave no signal.** When you add a directory, git silently omits any path inside it that matches an ignore rule — no warning, no non-zero exit. The skip is invisible unless you `git add -f` or name an ignored file directly (which *does* error). The author had no reason to suspect the data was left behind.

## Solution
Add explicit `.gitignore` negations (matching the repo's existing allowlist convention, e.g. `!data/examples/metabolites_synthetic.tsv`), then stage the files by explicit path and commit:

```gitignore
# Pinned benchmark artifacts committed as part of study packages (not scratch data).
!studies/northstar_e2e/data/suhre2010_canonical.csv
!studies/northstar_e2e/data/kegg_compound_pathway.tsv
```

```bash
git add .gitignore \
  studies/northstar_e2e/data/suhre2010_canonical.csv \
  studies/northstar_e2e/data/kegg_compound_pathway.tsv
git ls-files studies/northstar_e2e/data/   # now lists both files
git commit -m "Track pinned benchmark data for northstar_e2e study package"
```

## Why This Works
- **Ignore precedence is last-match-wins.** A later pattern overrides an earlier one, so a `!path` negation placed after `*.csv`/`*.tsv` re-includes that specific path while the broad glob still ignores everything else.
- **Negation re-includes the file** so it is no longer ignored, which is what lets it be staged at all.
- **Naming the file explicitly on `git add`** removes the silent-skip behavior — once the path is un-ignored an explicit add stages it, and if it were still ignored an explicit path would *error* rather than skip (a useful signal in its own right).

## Prevention
Never trust a green *local* test run as proof the *committed* package is complete — the working tree lies. Concrete, reusable checks:

1. **After adding any data, confirm it's actually tracked** (not just present on disk):
   ```bash
   git ls-files studies/northstar_e2e/data/          # must list every required artifact
   git status --short                                 # untracked required files show as ?? — a red flag
   git check-ignore -v studies/northstar_e2e/data/*.csv  # shows WHICH .gitignore line ignores a path
   ```

2. **Verify what a fresh checkout sees** by building from tracked-only files and importing from that export — never the working tree:
   ```bash
   rm -rf /tmp/verify && mkdir -p /tmp/verify
   git archive HEAD studies/northstar_e2e | tar -x -C /tmp/verify
   cd /tmp/verify && python -c "from studies.northstar_e2e import gold, kegg; gold.assert_known_answer()"
   # confirmed: 15 gold metabolites + 6679 KEGG entries load from tracked-only files
   ```
   `git archive` emits exactly the tracked tree — the same thing a clone gets — so a clean import here proves the package is self-contained.

3. **Use explicit `!` negation allowlists** for any intentionally-committed artifact in a repo with broad `*.ext` ignores. Group them under a comment noting they are pinned inputs, not scratch, so a future author doesn't "clean up" the globs and silently re-break it.

4. **Add a CI job that builds from `git archive HEAD` (or a clean clone), not the working checkout**, then imports/tests the package. This catches the working-tree-vs-index gap automatically — the exact class of bug that passed locally and only surfaced in review.

## Related Issues
- No related `docs/solutions/` entries or GitHub issues at time of writing (first entry in the `runtime-errors/` category).
- Surfaced during the Greptile review of the northstar-e2e benchmark PR (`trentleslie/biomapper2`, base `dev`), 2026-08-04.
