---
title: "Moving the default Kestrel endpoint to the public host leaked the internal API key to a third party"
date: 2026-08-05
category: security-issues
module: biomapper2/config
problem_type: security_issue
component: authentication
symptoms:
  - "Internal X-API-Key transmitted to the public third-party host with no error, warning, or failing test"
  - "The vulnerable configuration was the documented one: deploy/README.md set KESTREL_API_KEY but never KESTREL_API_URL"
  - "Suite failed 18 tests with 'KESTREL_API_KEY environment variable is not set' when no .env was present"
  - "The two backends disagree on results (6/25 top-1 metabolite hits differ), so the swap silently changed benchmark numbers too"
root_cause: missing_validation
resolution_type: code_fix
severity: high
related_components:
  - tooling
  - testing_framework
  - documentation
tags:
  - kestrel
  - api-key
  - credential-leak
  - default-endpoint
  - host-binding
  - metagraph
  - reproducibility
  - regression-test
---

# Moving the default Kestrel endpoint to the public host leaked the internal API key to a third party

## Problem

biomapper2 selects its knowledge-graph backend with `KESTREL_API_URL`. The packaged default pointed at the internal, auth-gated host, which meant a fresh clone could not run without credentials and any deployment silently inherited whichever backend the code default named. Switching the default to the public keyless endpoint required relaxing `get_kestrel_api_key()` from raising to returning `None` — but header construction still attached `X-API-Key` whenever a key happened to exist, with no binding to the destination. Every environment that had set `KESTREL_API_KEY` for the internal endpoint and never set `KESTREL_API_URL` would begin transmitting that internal credential to a third-party host on upgrade.

## Symptoms

- **Nothing observably breaks.** The public Kestrel ignores `X-API-Key` entirely: no key, a valid internal key, and a junk key all return identical HTTP 200s. No 401, no warning, no changed result. The only consequence is that a third party now holds the credential in its request logs.
- **The vulnerable configuration was the documented one.** `deploy/README.md` instructed operators to write exactly this `.env`:
  ```bash
  cat > .env << 'EOF'
  KESTREL_API_KEY=your-kestrel-api-key
  BIOMAPPER_API_KEY=your-biomapper-api-key
  EOF
  ```
  No `KESTREL_API_URL` line, so every deployment provisioned from the template inherited the code default — and the code default was the thing that moved.
- **Reviewer-visible only.** Greptile flagged the disclosure at 4/5 confidence. No test, log line, or runtime behavior would have surfaced it.
- The adjacent symptom that motivated making the key optional: with the old `get_kestrel_api_key()`, running the suite with no `.env` failed 18 tests with `KESTREL_API_KEY environment variable is not set`. An outside reader could not run the tests, let alone reproduce a benchmark.

## What Didn't Work

- **Probing `app.krakenkg.com` for the API.** It is a static S3/CloudFront SPA that serves `index.html` with HTTP 200 for *every* path. `GET /api/health` and `GET /openapi.json` both return 200 with HTML bodies, which reads exactly like a live API. Misleading because a 200 was treated as proof of endpoint existence. What worked instead: fetch the SPA's JS bundle (`/assets/index-*.js`) and grep it for the API base URL.
- **Concluding "no provenance endpoint exists" from a 404 sweep.** A probe on 2026-07-22 tried the TRAPI-style names `/version`, `/meta`, and `/meta_knowledge_graph`, got 404 on all three, and wrote that conclusion into a `studies/external_benchmarks/runner.py` docstring. The real endpoint, `/metagraph`, was simply never tried. Multiple later sessions read that docstring and relied on it as fact. (session history) A negative result over an *assumed naming convention* was recorded as a fact about the service. Worse, `/metagraph` had already been visible in a 2026-07-13 session's `GET /openapi.json` output — the information was in hand weeks before it was "discovered." (session history)
- **Reading `graph: "kraken"` as the source composition.** `/metagraph`'s top-level `graph` field is the **build name**, not the set of ingested sources. Both endpoints report `graph: "kraken"`, from which we wrongly concluded that neither backend was SPOKE-backed. In fact the internal build's `knowledge_sources` includes `infores:spoke` with 1,494,308 edges; the public build does not list it at all.
- **Treating the endpoint swap as a re-point rather than a re-run.** The backends genuinely disagree: internal is version 2.0.0 with 147 knowledge sources; public is 2.0.1 with 100, SPOKE/ClinGen/MolePro absent. On a 25-name metabolite panel, 6/25 top-1 hybrid-search hits differed, including whole-namespace flips (`LOINC:45207-8` → `EFO:0800030`, `CHEBI:4260` → `CHEBI:29026`).
- **A placeholder API key as the keyless workaround.** Because `bulk_kestrel_request` always sent the header, CI originally supplied `KESTREL_API_KEY: ${{ secrets.KESTREL_API_KEY || 'public-kraken-no-auth' }}`. That treated the symptom (a header is always sent) instead of the cause (the header is not bound to a host), and it was retired once the guard landed. (session history)
- **`git branch -d` as a merge check.** It reported "not fully merged" for a branch that *was* merged into `dev`, because `-d` compares against the currently checked-out branch. The check to trust is `git rev-list --count origin/dev..<branch>`.

## Solution

**Before** (`b08be60^1`) — key mandatory, internal default:

```python
# src/biomapper2/config.py
KESTREL_API_URL = os.getenv("KESTREL_API_URL", "https://kestrel.nathanpricelab.com/api")

def get_kestrel_api_key() -> str:
    global _kestrel_api_key
    if _kestrel_api_key is None:
        _kestrel_api_key = os.getenv("KESTREL_API_KEY")
        if not _kestrel_api_key:
            raise ValueError("KESTREL_API_KEY environment variable is not set")
    return _kestrel_api_key
```

```python
# src/biomapper2/utils.py
headers: dict[str, str] = {}
if auth_required:
    headers["X-API-Key"] = get_kestrel_api_key()
```

**The vulnerable intermediate** (commit `968be00`) — this is the state the disclosure lived in:

```python
KESTREL_API_URL = os.getenv("KESTREL_API_URL", "https://kestrel.krakenkg.com/api")
```

```python
api_key = get_kestrel_api_key() if auth_required else None
if api_key:
    headers["X-API-Key"] = api_key      # <-- no destination check
```

**After** (commit `e659bc8`) — the public host is named so request construction can refuse it:

```python
# src/biomapper2/config.py
# Named separately so request construction can refuse to send credentials here: an environment
# that set KESTREL_API_KEY for the internal endpoint and never set KESTREL_API_URL would
# otherwise start leaking that key to a third-party host the moment this default changed.
PUBLIC_KESTREL_API_URL = "https://kestrel.krakenkg.com/api"
KESTREL_API_URL = os.getenv("KESTREL_API_URL", PUBLIC_KESTREL_API_URL)
```

```python
# src/biomapper2/utils.py
def _accepts_credentials(url: str) -> bool:
    """False for the public Kestrel, which needs no key and must never receive one.

    Compared by hostname so a trailing slash or a different path does not defeat the check.
    """
    return urlparse(url).hostname != urlparse(PUBLIC_KESTREL_API_URL).hostname
```

Header construction becomes a three-way decision instead of a two-way one:

```python
api_key = get_kestrel_api_key() if auth_required else None
if api_key and _accepts_credentials(KESTREL_API_URL):
    headers["X-API-Key"] = api_key
elif api_key:
    _warn_key_withheld_once()
```

The 401/403 path also gained an actionable message, so the *opposite* misconfiguration (pointed at the internal endpoint with no key) is self-diagnosing rather than a bare raise.

Verified: full suite **365 passed with no `.env` present** (the same tree before the key-optional change failed 18 tests), ruff clean. Merged as `trentleslie/biomapper2#46` → `b08be60`.

## Why This Works

The root cause is that the credential was bound to the **request** rather than to the **host**. `if api_key: headers["X-API-Key"] = api_key` encodes "we have a key, therefore send it" — a statement about local state with no reference to who is on the other end of the socket. That predicate was correct only because a second, entirely separate piece of configuration (`KESTREL_API_URL`'s default) happened to name the one host the key was issued for. Moving that default silently invalidated it. Two independent pieces of configuration held the invariant between them, and nothing in the code expressed the dependency.

The fix moves the invariant into the code path that actually forms the request. `_accepts_credentials(KESTREL_API_URL)` asks about the destination, so no future change to a default, an env var, or a deploy template can reintroduce the leak. Comparing `urlparse(url).hostname` rather than the raw string means `https://kestrel.krakenkg.com/api/`, `.../api`, and any other path on that host all resolve to the same answer.

The `elif api_key: _warn_key_withheld_once()` branch matters as much as the guard. Silently dropping auth would convert a credential-disclosure bug into a confusing-401 bug for anyone legitimately using the internal endpoint. Instead the operator is told, once per process, that their configuration is stale and which of the two knobs to change.

## Prevention

**1. Bind credentials to hosts, not to requests.** Any time a secret is attached to an outbound call, the condition must mention the destination. `if api_key:` is a smell in any codebase where the destination is configurable. When a config default that selects an external host changes, grep every place the corresponding secret is read and confirm each one re-derives its decision from the current destination.

**2. A code default is not a substitute for an explicit env var.** The deploy template was the vulnerability. It now pins the URL rather than inheriting it:

```bash
cat > .env << 'EOF'
KESTREL_API_URL=https://kestrel.krakenkg.com/api
BIOMAPPER_API_KEY=your-biomapper-api-key
EOF
```

Rule: if a deploy template sets a secret, it must also set the destination that secret is scoped to. Leaving the destination implicit means a library upgrade can silently re-target the secret.

**3. Verify backend identity from `knowledge_sources`, not from the build label.** Before quoting any benchmark number:

```bash
curl $KESTREL_API_URL/metagraph
```

Read `version` and `knowledge_sources`. The top-level `graph` field is identical ("kraken") across both deployments and tells you nothing about composition. Internal: 2.0.0, 147 sources, includes `infores:spoke`. Public: 2.0.1, 100 sources, no SPOKE/ClinGen/MolePro. Corollary: switching endpoints is a **benchmark re-run**, not a re-point. Pin the endpoint *and* the `/metagraph` version alongside every published number.

**4. The guard is pinned by tests** in `tests/test_kestrel_auth_header.py`, which capture the headers actually handed to `session.request` rather than asserting on internals:

```python
def test_key_is_withheld_from_the_public_endpoint():
    """A retained internal key must NOT be sent to the public host (the upgrade leak path)."""
    assert "X-API-Key" not in _capture_headers(PUBLIC_KESTREL_API_URL, "internal-secret")

def test_key_is_sent_to_the_internal_endpoint():
    """The guard must not break the endpoint that actually requires authentication."""
    assert _capture_headers(INTERNAL_URL, "internal-secret")["X-API-Key"] == "internal-secret"

def test_public_endpoint_matched_by_host_not_exact_string():
    """A trailing slash or differing path must not defeat the guard."""
    assert "X-API-Key" not in _capture_headers("https://kestrel.krakenkg.com/api/", "internal-secret")
```

The negative test is the load-bearing one: it is the only thing standing between this codebase and a leak that produces no error. A fifth test asserts the warning fires exactly once across three requests, so the operator-facing signal cannot regress into either silence or per-request log spam.

**5. Operational caveats when pointing benchmarks at the public endpoint.** It has no rate limiting and is unstable under suite load: one full run produced 22 5xx responses, 20 dropped connections, and 24 JSON-decode failures, all on `/api/hybrid-search`. (auto memory [claude]) It also lacks LIPID MAPS, which degrades lipid-shorthand benchmarks — LMSD shorthand scored 6.3% against 41.9% for systematic names. (auto memory [claude]) Reproducibility gained; throughput and lipid coverage lost.

**6. Follow-up gaps left by this change.** The two marked ✅ below were closed later the same day by PR #50, which also found that the host guard here was still defeatable — a trailing FQDN dot (`https://kestrel.krakenkg.com./api`) compared unequal and *sent* the key to the public host, and a cross-origin redirect replayed it regardless, since `requests` strips only `Authorization`. See [the at-rest companion doc](kestrel-api-key-persisted-in-cleartext-to-http-cache-2026-08-05.md).

- `studies/external_benchmarks/runner.py` records only `n_knowledge_sources` (a count) and builds `kg_snapshot` from `graph` + `version`. Since both endpoints report `graph: "kraken"`, the manifest cannot yet honor prevention rule 3 — it should record source identities, or at least SPOKE presence, not just a count.
- ✅ **An orphaned test** (fixed in PR #50). `tests/test_kestrel_discovery.py:133` raises `ValueError("KESTREL_API_KEY environment variable is not set")` through a mock `side_effect`. That exception no longer exists in production code — this change removed the only `raise` that produced it. The test still passes, so it silently became fiction: it asserts graceful handling of a failure mode that can no longer occur, while the real new failure at that layer (an `HTTPError` 401 from the endpoint) goes untested. **Removing a raise is not done until you re-check the tests that only ever saw it through a mock** — a green suite is not evidence those tests still mean anything.
- ✅ **A now-dead memoization** (fixed in PR #50). `get_kestrel_api_key()` caches into a module global under `if _kestrel_api_key is None`, but the unset case now *returns* `None`, so the global never populates and every call re-reads `os.getenv`. The cache only works in the case that no longer needs it. It is harmless for performance (a dict lookup) but is mutable module state doing nothing, and it makes results depend on call order if a test sets the env var mid-process. `return os.getenv("KESTREL_API_KEY") or None` is the whole function.

## Related Issues

- `docs/solutions/integration-issues/github-actions-schedule-trigger-drops-workflow-dispatch-inputs-2026-08-05.md` — the companion doc that established `/metagraph` as the real backend-identity endpoint and corrected the earlier "no such endpoint" conclusion. This doc uses that probe to prove the two endpoints serve different builds.
- PR [trentleslie/biomapper2#46](https://github.com/trentleslie/biomapper2/pull/46) — this work (`968be00` enabling commit, `e659bc8` credential guard, merged `b08be60`).
- PR [trentleslie/biomapper2#45](https://github.com/trentleslie/biomapper2/pull/45) — the `/metagraph` provenance fix this depends on.
- **Not yet promoted upstream:** `Phenome-Health/biomapper2` still carries the internal default, so the fix is fork-only as of 2026-08-05.
- Deliberately unchanged: `scripts/spike_microbiome_taxon_probe.py` still hardcodes the internal URL — a historical one-off probe.
