---
title: "requests_cache redaction is case-sensitive, so the Kestrel API key was written to disk in cleartext for seven months"
date: 2026-08-05
category: security-issues
module: biomapper2/http-cache
problem_type: security_issue
component: authentication
symptoms:
  - "11,123 cleartext copies of a live 43-character API key across six world-readable (0644) requests_cache SQLite files, largest 380 MB, inside repo working trees"
  - "Nothing failed: no error, no warning, all tests green — and the same files held 1,151 REDACTED strings, so redaction visibly appeared to be working"
  - "requests_cache's default ignored_parameters already contains \"X-API-KEY\" but matches case-sensitively, and the code sends \"X-API-Key\""
  - "allowable_methods=[\"GET\",\"POST\"] made every search POST a leaking cache record"
  - "The host guard added days earlier was still defeatable: a trailing FQDN dot sent the key to the public host, and a cross-origin redirect replayed it"
root_cause: wrong_api
resolution_type: code_fix
severity: critical
related_components:
  - tooling
  - testing_framework
  - service_object
tags:
  - kestrel
  - api-key
  - credential-at-rest
  - requests-cache
  - header-redaction
  - case-sensitivity
  - file-permissions
  - vacuous-test
---

# requests_cache redaction is case-sensitive, so the Kestrel API key was written to disk in cleartext for seven months

## Problem

`requests_cache` persisted the Kestrel API key unredacted into every cache database, because its secret-redaction list matches parameter names **case-sensitively** and its default entry `"X-API-KEY"` never matched the `"X-API-Key"` spelling the code sends. With `allowable_methods=["GET", "POST"]`, every search POST became a leaking record: **11,123 cleartext copies of a live 43-character credential across six world-readable (0644) SQLite files**, the largest 380 MB, sitting inside repo working trees.

**This is not a regression from the endpoint work that uncovered it.** The caching commit (`37cb7cd`, 2025-12-31) already sent `X-API-Key` unconditionally with `allowable_methods=["GET","POST"]`; the default-endpoint change (`968be00`) landed seven months later. The credential had been accumulating on disk that entire time, back when the default host was internal and the key was mandatory.

## Symptoms

The defining symptom is that **there is no symptom**. Nothing raised, nothing logged, nothing failed, tests were green, and the code that leaks looks exactly like code that does not:

```python
session = requests_cache.CachedSession(
    CACHE_DIR / "kestrel_http",
    expire_after=timedelta(hours=1),
    allowable_methods=["GET", "POST"],
)
```

What is observable, only if you go looking:

- Grepping the literal key value across `cache/*.sqlite` returns thousands of hits — 11,123 across six files, 496 MB total.
- Those same files contained **1,151 occurrences of the string `REDACTED`**. This is what hid the bug for its whole lifetime: redaction *was* running on every write and *was* successfully scrubbing other parameters. A spot check would show the machinery working. Only this one header, off by a single character of case, silently no-opped.
- Mode `0644` on the databases, inside a git working tree — so anything that tarballs, syncs, or backs up the repo carries the credential.
- Two further silent exposures found while fixing this: a 301 from the internal Kestrel host to the public one would replay `X-API-Key` to a third party (`requests` strips only `Authorization` across origins), and `https://kestrel.krakenkg.com./api` — a valid FQDN with a trailing dot — compared unequal to the public host and therefore *sent* the key to it.

## What Didn't Work

**1. Trusting the library default.** `requests_cache` documents `ignored_parameters` and ships a default that already includes `"X-API-KEY"`. Reading that list, the header appears covered. It is not: `filter_sort_dict` builds a plain `dict` from `sorted(data.items())`, discarding the `CaseInsensitiveDict` semantics that make header lookup case-insensitive everywhere else in `requests`. The contract silently degrades from "redact this header" to "redact this exact byte string." *Why it misled:* the feature exists, is on by default, is documented, and demonstrably works — on other parameters.

**2. A mock-based at-rest test. This is the important failure.** The first version of the regression test used a mocked transport adapter and was **vacuous**. With a mock, `requests_cache` writes nothing to the database at all, so the assertion "the secret does not appear in the cache files" passed **with the bug fully present**. It was a green test asserting the exact property that was, at that moment, false.

*Why it misled:* it read as a strong at-rest proof and cost nothing to run. It was caught only by deliberately running the same check against the known-broken configuration and expecting a failure that never came. That non-failure — not any failing test — is what exposed the test as hollow.

**3. The URL-string-level guard alone.** The guard added days earlier compared the configured URL's hostname against the public one:

```python
return urlparse(url).hostname != urlparse(PUBLIC_KESTREL_API_URL).hostname
```

*Why it misled:* it correctly answers a question that is not the question. It validates the *configured* URL, not the *actual destination*, so a redirect bypasses it. And it fails **open** twice: `urlparse("kestrel.krakenkg.com/api").hostname` is `None`, which compares unequal and therefore sends the key; and a trailing FQDN dot produces a different string for the same destination.

## Solution

**Enumerate the casings actually sent, in one place** (`src/biomapper2/config.py`):

```python
# requests_cache ships a default list that already contains "X-API-KEY", but it matches
# CASE-SENSITIVELY (`filter_sort_dict` sorts a plain dict, discarding the CaseInsensitiveDict
# semantics), and we send the header spelled "X-API-Key". That one-character mismatch persisted the
# Kestrel credential in cleartext into every cached record. Enumerate the casings we actually send
# rather than relying on the library default.
CACHE_IGNORED_PARAMETERS = [
    "X-API-Key",
    "X-API-KEY",
    "x-api-key",
    "Authorization",
    "api_key",
    "access_token",
]
```

Pass it explicitly at **all three** `CachedSession` sites (`utils.py`, `core/annotators/metabolomics_workbench.py`, `core/structure_resolver.py`).

**Treat the cache directory as secret-bearing.** Note `mode=` applies only on creation, so an existing directory needs an explicit chmod:

```python
CACHE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
with contextlib.suppress(OSError):
    CACHE_DIR.chmod(0o700)
```

**Scrub on cross-origin redirect, at the transport layer where the real destination is known:**

```python
class _KestrelCachedSession(requests_cache.CachedSession):
    def rebuild_auth(self, prepared_request, response):
        super().rebuild_auth(prepared_request, response)
        if response.request.url and self.should_strip_auth(response.request.url, prepared_request.url):
            prepared_request.headers.pop(_KESTREL_KEY_HEADER, None)
```

**Normalize the host and fail closed:**

```python
def _normalized_host(url: str) -> str | None:
    host = urlparse(url).hostname
    return host.rstrip(".") if host else None


def kestrel_host_accepts_credentials(url: str) -> bool:
    host = _normalized_host(url)
    if host is None:          # unparseable -> withhold, we cannot prove where it would go
        return False
    return host != _normalized_host(PUBLIC_KESTREL_API_URL)
```

**The test that actually proves it** — a real localhost server, asserting on bytes on disk, with two anti-vacuity devices:

```python
def _cleartext_occurrences(cache_dir, base_url, ignored_parameters) -> int:
    session = requests_cache.CachedSession(
        str(cache_dir / "kestrel_http"),
        allowable_methods=["GET", "POST"],
        ignored_parameters=ignored_parameters,
    )
    session.post(f"{base_url}/hybrid-search", headers={"X-API-Key": SECRET}, json={"q": 1})
    written = [p for p in cache_dir.iterdir() if p.is_file()]
    assert written, "cache wrote no file, so this test would prove nothing"   # tripwire
    return sum(p.read_bytes().count(SECRET.encode()) for p in written)


def test_key_is_not_written_to_the_on_disk_cache(tmp_path, local_json_server):
    assert _cleartext_occurrences(tmp_path, local_json_server, CACHE_IGNORED_PARAMETERS) == 0


def test_the_library_default_would_leak_the_key(tmp_path, local_json_server):
    """Positive control: pins the buggy config at >0 so the guard cannot go hollow."""
    assert _cleartext_occurrences(tmp_path, local_json_server, ["X-API-KEY"]) > 0
```

Measured against that fixture: library default = 1 cleartext copy, `["X-API-KEY"]` = 1, `CACHE_IGNORED_PARAMETERS` = 0.

**Remediation performed:** six cache databases (496 MB) deleted, all cache directories chmod 700, and a rescan of 51,543 files under cache paths confirmed zero remaining cleartext copies. 888 tests pass, ruff clean.

## Why This Works

The root cause is a class, not an incident: **the library's secret redaction is keyed on a case-sensitive name match over a string the caller controls.** `requests` treats header names case-insensitively everywhere a caller touches them, so `"X-API-Key"` and `"X-API-KEY"` are the same header — right up until `filter_sort_dict` flattens the `CaseInsensitiveDict` into a plain `dict` for the redaction pass, at which point they become two different keys and one of them is not on the list. The security control and the calling convention disagreed about identity, and the disagreement had no failure mode: redaction ran, reported success, and skipped the one entry that mattered.

The fix works because it stops depending on that agreement. `CACHE_IGNORED_PARAMETERS` enumerates the exact byte strings the codebase emits and is passed at every construction site, so correctness no longer rests on the library's list matching our spelling. `0700` reduces the blast radius of any *future* redaction miss from world-readable to owner-only. `rebuild_auth` moves the destination check from the configured URL to the resolved one, and normalization plus fail-closed removes the two inputs that made the URL guard silently permissive.

## Prevention

- **Assert on bytes, not on mocks.** Any "the secret is not persisted / not transmitted" test must exercise a real writer — a localhost server, a real file, a real database — and read the resulting bytes. A mocked transport writes nothing, so an absence assertion over it is unconditionally true.
- **Prove the negative test can fail.** Before trusting a guard test, run it against the known-broken configuration and confirm it goes red. Then *keep* that run as a positive control (`test_the_library_default_would_leak_the_key`, asserting `> 0`). Add an in-test tripwire for the vacuity condition itself: `assert written, "cache wrote no file, so this test would prove nothing"`.
- **Don't trust a library's default secret list — enumerate.** When a security control matches on a name you supply, list every casing you actually emit, pass it explicitly at every call site, and pin the call-site constant to the list in a test (`assert utils._KESTREL_KEY_HEADER in CACHE_IGNORED_PARAMETERS`).
- **`0700` on any directory that can hold request or response records.** `Path.mkdir(mode=...)` is a no-op on an existing directory — chmod separately, best-effort.
- **Grep caches and artifacts for the live secret in CI.** A periodic scan of cache paths for the credential value would have caught this on day one and will catch the *next* redaction miss regardless of cause.
- **Deleting the artifact is containment, not remediation — rotate.** The key was world-readable for seven months and may exist in backups. Cache deletion does not invalidate a credential. Worth naming as a recurring gap: "rotate exposed secret" is an open item on at least two other active projects here, and nothing tracks it. (auto memory [claude])
- **Watch for preconditions that quietly go dead.** `try: f() / except: ok = False` becomes a permanent `True` the moment `f` stops raising — which is exactly what happened to `gate.py`'s documented "missing key → stop" condition when the key became optional. Prefer preconditions asserting a positive fact over ones inferring from an absent exception, and when you remove a `raise`, grep for tests that only ever saw it through a mock.
- **Treat cache scope and lifetime as a design decision, not a default.** These same on-disk caches independently invalidated a Tier-3 benchmark determinism measurement, where N repeats replayed SQLite instead of exercising the pipeline. One caching decision, two unrelated classes of harm — "what does this persist, and who can read it" belongs on the review checklist wherever a `CachedSession` is constructed. (auto memory [claude])

## Related Issues

- [`internal-api-key-leaked-to-public-kestrel-after-default-endpoint-swap-2026-08-05.md`](internal-api-key-leaked-to-public-kestrel-after-default-endpoint-swap-2026-08-05.md) — the **in-transit half** of the same credential's exposure, and the source of the follow-up gaps this work closed. Note the two are causally independent: that doc's guard was working correctly while this leak was active, and this leak predates it by seven months.
- `docs/solutions/best-practices/audit-instruments-backing-published-claims-2026-08-05.md` — same principle on a different axis: prove your instrument could have failed before trusting what it reports.
- `docs/solutions/best-practices/trustworthy-gates-invoke-test-real-shape-faithful-fallbacks-2026-08-04.md` — same failure class as the dead `gate.py` precondition fixed here: a declared gate condition the run path could not actually trip.
- PR [trentleslie/biomapper2#50](https://github.com/trentleslie/biomapper2/pull/50) — this work (`6f23ddf`, merged 2026-08-06, Greptile 5/5). Predecessors: [#46](https://github.com/trentleslie/biomapper2/pull/46) (host guard), [#45](https://github.com/trentleslie/biomapper2/pull/45) (`/metagraph` provenance).
- **Still open.** The credential has **not** been rotated. `.github/workflows/weekly-benchmarks.yml:38-41` still injects a placeholder key with a now-false comment. `CLAUDE.md:84` still calls `KESTREL_API_KEY` required. Neither #46 nor #50 is promoted to `Phenome-Health/biomapper2`, which still carries the internal default and neither fix.
