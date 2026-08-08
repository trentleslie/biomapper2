---
title: "Cron runs recorded 'unrecorded' provenance because github.event.inputs.* only exists on workflow_dispatch"
date: 2026-08-05
category: integration-issues
module: external_benchmarks
problem_type: integration_issue
component: tooling
symptoms:
  - "Every scheduled (cron) benchmark run wrote kg_snapshot: \"unrecorded\" into suite_manifest.json, while manual workflow_dispatch runs recorded a value"
  - "No error, no warning, no failed check — the manifest looked complete and the run looked healthy"
  - "_suite_pins() called kg_provenance() with no arguments, so the live probe never ran on ANY trigger, dispatch included"
root_cause: config_error
resolution_type: code_fix
severity: high
related_components:
  - development_workflow
  - testing_framework
tags:
  - github-actions
  - workflow-dispatch-vs-schedule
  - provenance
  - silent-failure
  - reproducibility
  - test-isolation
---

# Cron runs recorded "unrecorded" provenance because `github.event.inputs.*` only exists on `workflow_dispatch`

## Problem

The weekly benchmark suite recorded which knowledge-graph build produced its numbers by reading env vars sourced from `github.event.inputs.*`. GitHub only populates that context on the `workflow_dispatch` trigger, so every scheduled run — the suite's actual production mode — silently wrote the `"unrecorded"` sentinel into its provenance manifest. Benchmark results were being persisted with no attributable backend build.

## Symptoms

- `.github/workflows/weekly-benchmarks.yml` declared both `schedule:` (`cron: '0 8 * * 1'`) and `workflow_dispatch:`, and wired:
  ```yaml
  KG_SNAPSHOT: ${{ github.event.inputs.kg_snapshot }}
  CHEBI_RELEASE: ${{ github.event.inputs.chebi_release }}
  ```
  On the cron path these evaluate to empty, so `kg_provenance()` fell through to `UNRECORDED`.
- **The failure was silent, not loud.** Nothing raised, nothing logged a warning, no check failed. The manifest had a populated `pins` block; one field inside it was just always the same string. A run that recorded nothing looked identical to a run that recorded something.
- **A second, independent instance of the same gap:** `studies/external_benchmarks/run.py::_suite_pins()` called `_runner.kg_provenance()` with no arguments, so `probe_live` defaulted to `False` and the suite-level probe never executed on *any* trigger. Fixing only the workflow YAML would have left this one live.
- Manual dispatch "worked", which is what made it survive review: the path a human tests interactively is precisely the path where the bug does not appear.

## What Didn't Work

**Concluding the graph had no version endpoint, based on guessing endpoint names.** An earlier attempt (2026-07-22) to derive provenance from the KG probed `/version`, `/meta`, and `/meta_knowledge_graph`. All three genuinely 404, and that negative result was written into the `kg_provenance()` docstring as settled fact — which is why env vars remained the only provenance mechanism for two weeks.

The real endpoint is `/metagraph`. The probe used TRAPI-convention names and never tried it. The lesson is not "check harder" but: **a negative result from guessed endpoint names is not evidence of absence, and should not be recorded as an architectural fact.** Read the API's own `openapi.json` before writing "this endpoint does not exist" into a docstring. (Session history confirms the 07-22 commit `226a871` introduced both the env-var scheme and the false-negative docstring together.)

## Solution

### 1. Derive provenance from the system itself

`studies/external_benchmarks/runner.py`:

```python
def kg_provenance(*, probe_live: bool = False) -> dict[str, Any]:
    prov: dict[str, Any] = {
        "kg_snapshot": os.getenv("KG_SNAPSHOT") or UNRECORDED,
        "chebi_release": os.getenv("CHEBI_RELEASE") or UNRECORDED,
    }
    if probe_live:
        mg = _fetch_metagraph()
        prov["kg_metagraph"] = mg
        if mg.get("chebi_node_count") is not None:
            prov["chebi_node_count"] = mg["chebi_node_count"]
        # Derive the snapshot only when the operator did not pin one by hand.
        if prov["kg_snapshot"] == UNRECORDED and mg.get("version"):
            summary = mg.get("summary") or {}
            nodes, edges = summary.get("total_nodes"), summary.get("total_edges")
            fingerprint = f" ({nodes}n/{edges}e)" if nodes and edges else ""
            prov["kg_snapshot"] = f"{mg.get('graph') or 'kg'} {mg['version']}{fingerprint}"

        # ... elided: a second best-effort GET /health, recorded as prov["kg_health_probe"].
        # probe_live=True therefore makes TWO network calls, not one.
    return prov
```

`GET {KESTREL_API_URL}/metagraph` self-reports `graph`, `version`, and a `summary` block used as a **content fingerprint**. Live result with no env vars set:

```
kg_snapshot:          kraken 2.0.1 (14683250n/92233909e)
chebi_node_count:     202220
kg_stable_during_run: true
```

The fingerprint is the part that matters: it distinguishes two builds that both call themselves `2.0.1`, which a hand-typed label cannot.

The env vars survive as an **operator override**, and the fetched metagraph is recorded alongside either way, so an override never hides what was actually served. `chebi_release` stays env-only because `/metagraph` carries no ChEBI version; the CHEBI node count is recorded as its fingerprint stand-in.

### 2. Fix the second instance

```python
def _suite_pins(*, probe_live: bool = True) -> dict[str, Any]:
    """...
    ``probe_live`` defaults to TRUE here, unlike ``kg_provenance`` itself. A suite run is by
    definition a live run, and the whole purpose of these pins is to record which graph produced the
    numbers — pinning "unrecorded" against a live suite is worse than not pinning at all, because it
    looks like provenance. Tests pass False to keep aggregation assertions offline.
    """
```

### 3. Sample before the work, and re-check after

Pins were originally assembled with the manifest, i.e. *after* every dataset finished, so a mid-suite redeploy would attribute earlier results to a build that did not produce them:

```python
    # Pin the backend BEFORE any dataset runs.
    pins = _suite_pins(probe_live=probe_live)
    ...
    # Re-read the build now that the datasets are done. If it moved, the pins above no longer
    # describe every result, and a reader has to know that before trusting the suite as one
    # coherent measurement.
    if probe_live:
        before = (pins.get("kg_metagraph") or {}).get("version"), (pins.get("kg_metagraph") or {}).get("summary")
        end_mg = _runner._fetch_metagraph(refresh=True)
        after = end_mg.get("version"), end_mg.get("summary")
        manifest["kg_stable_during_run"] = before == after
        if before != after:
            manifest["kg_metagraph_at_end"] = end_mg
```

### 4. Memoize the probe, then restore test isolation

Each dataset called `kg_provenance(probe_live=True)`, so an unreachable KG cost a 20s timeout **per dataset** (~3 minutes of dead waiting across a 10-dataset suite). `_fetch_metagraph()` is now memoized per process, failures included, with `refresh=True` for the end-of-suite re-read.

That memo is process-global state, and it broke test isolation immediately — a test that primed the cache silently satisfied a later test expecting a probe failure, making results depend on test **order**:

```python
@pytest.fixture(autouse=True)
def _reset_metagraph_cache():
    from studies.external_benchmarks import runner as _runner
    _runner._METAGRAPH_CACHE = None
    yield
    _runner._METAGRAPH_CACHE = None
```

## Why This Works

Patching the YAML would not have made the pattern safe. The defect is not a mistake *within* the wiring but a category error *about* it: a trigger-conditional CI context was being used as an unconditional provenance source. Adding a future `push:` or `repository_dispatch:` trigger would reintroduce exactly the same gap.

Reading the build from `/metagraph` makes the value self-describing: the graph reports its own identity regardless of *why* the workflow is executing. It also strictly dominates the old scheme even when an operator does supply a label, because a hand-typed version string cannot detect that the underlying build changed while the version number stayed the same.

## Prevention

- **Trace every `github.event.*` reference against every declared trigger.** Before wiring `github.event.inputs.*`, `github.event.pull_request.*`, etc., check the workflow's `on:` block and confirm the field is populated on *all* of them. `workflow_dispatch` inputs exist only under `workflow_dispatch`; `pull_request` fields only under `pull_request`/`pull_request_target`; `schedule` runs carry almost nothing. "It worked when I clicked Run workflow" does not generalize to the cron path — and the cron path is usually the production one.
- **Read provenance from the system that produced the result, and record any operator-supplied label *alongside* the derived value rather than in place of it.** This applies to any value kept for reproducibility or audit: build version, config snapshot, environment identity. An override that replaces the derived value can hide what was actually served.
- **Treat a constant sentinel as a bug signal, not a working default.** `"unrecorded"`, `"unknown"`, `null`, or any default that is *always* present in output deserves an audit. This defect produced a complete-looking manifest every week for two weeks. A sentinel that never varies is indistinguishable from a field nobody populates.
- **Don't record a guessed-endpoint 404 as an architectural fact.** Read `openapi.json` or the service's own docs before writing "no such endpoint exists" into a comment. A false negative in a docstring outlives the session that produced it.
- **Verify test hermeticity by pointing at a dead endpoint.** After wiring a network call into a default-on path, re-run the "offline" suite with an unreachable target (`KESTREL_API_URL=http://127.0.0.1:9/api`). Here the leak was caught by a runtime jump from ~3s to ~9s; assertions alone would not have caught it, because the live calls were succeeding.
- **Give every process-global memo an `autouse` reset fixture.** Module-level caches make test results order-dependent, which stays invisible until someone reorders or runs a subset. Three caveats before reusing this exact pattern elsewhere:
  - An `autouse` fixture only covers tests **under its own conftest's directory tree**. Another test file that imports the same module from a different tree gets no reset and can reintroduce the order-dependency this is meant to prevent.
  - **Caching failures indefinitely is a deliberate trade-off, not a free optimization.** It is right here because the process is a short-lived batch run where an unreachable KG is unlikely to heal mid-run. Anything longer-lived (a service, a retrying job) wants a TTL or explicit invalidation instead.
  - The check-then-set in `_fetch_metagraph` is **not atomic**, which is fine only because the suite is strictly sequential. Under threads or concurrent callers it needs a lock.

## Related Issues

- Shipped in **PR #45** (`feat/kg-provenance-from-metagraph`, merged as `d059564`); follow-up review fixes in `69a9287`. The env-var scheme originated in `226a871` (2026-07-22).
- [`best-practices/trustworthy-gates-invoke-test-real-shape-faithful-fallbacks-2026-08-04.md`](../best-practices/trustworthy-gates-invoke-test-real-shape-faithful-fallbacks-2026-08-04.md) — **closest companion.** Its defect (a), "a declared gate exists but the real run path never invokes it," is the same shape as the `_suite_pins()` instance here: the mechanism existed and was simply never called on the path that mattered. Read both together; that doc generalizes the principle for gates, this one for CI trigger wiring and provenance.
- [`runtime-errors/gitignore-globs-exclude-pinned-benchmark-data-2026-08-04.md`](../runtime-errors/gitignore-globs-exclude-pinned-benchmark-data-2026-08-04.md) — sibling learning from the same review cycle, same "passes in the convenient context, fails in the one that counts" shape.
- Verified in production by the first live suite run (2026-08-05), which recorded a real snapshot and `kg_stable_during_run: true` across a 70-minute run with no env vars set.
