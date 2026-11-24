---
title: "One caller could open the process-wide Kestrel circuit breaker and fail every user's Kestrel lookups"
date: 2026-11-21
category: security-issues
module: biomapper2/utils
problem_type: security_issue
component: service_object
symptoms:
  - "A single /map/batch or multi-chunk /map/dataset request could record all six breaker failures by itself, opening the breaker for every caller."
  - "A plain 500, which Kestrel returns for an input it cannot process, counted as an outage, so a payload alone could trip the breaker."
  - "While open, every user's Kestrel-backed rows came back as errors for the cooldown, although Kestrel was healthy."
  - "Nothing failed in CI, the fault gate, or three rounds of automated code review; an automated security review of the org promotion found it."
root_cause: scope_issue
resolution_type: code_fix
severity: high
related_components:
  - testing_framework
tags:
  - kestrel
  - circuit-breaker
  - denial-of-service
  - shared-state
  - availability
  - fastapi
  - per-request-scope
  - regression-test
---

# One caller could open the process-wide Kestrel circuit breaker and fail every user's Kestrel lookups

## Problem

The Kestrel circuit breaker added for API fault isolation is one object for the whole API process.
It counted every failed attempt, from any request, toward opening, and it counted a plain 500 as an
outage. One caller, careless or malicious, could therefore open it repeatedly and make every other
user's Kestrel lookups fail fast for the cooldown. Rows came back as retryable errors, never wrong
answers, but it was an availability hole on a public API.

## Symptoms

- One request could open the breaker on its own, because `record_failure()` ran once per failed
  Kestrel call and the threshold is 6 consecutive failures. A `/map/batch` makes one Kestrel call per
  item inside a single worker; a `/map/dataset` sends one call per chunk (1,000 items for search,
  2,000 for `canonicalize`); and the 5xx
  bisect (off by default, `KESTREL_BISECT_ON_5XX_ENABLED = False`) re-sends halves of a failing chunk.
- A payload Kestrel rejects with a 500 counted the same as Kestrel being down.
- Once open, `bulk_kestrel_request` raised `CircuitBreakerOpenError` for every caller until the
  5 s cooldown passed, and the caller could simply repeat.
- Nothing flagged it. CI, the fault gate and Greptile (three rounds, ending at 5/5) all passed. It was
  caught by an automated security review when the change was promoted to the org repo, before prod.

## What Didn't Work

- **Reviewing the breaker's state machine.** Earlier review rounds fixed real breaker bugs, all about
  *how* a failure is recorded (an unsettled half-open probe, cache hits resetting the count). None
  asked *whose* failure it is, which is the question that matters when the state is shared by every
  caller.
- **Per-client accounting**, the obvious full fix, was not possible here: the engine has no notion of
  client identity; that lives in the nginx layer in front of it.
- **Counting only single-item requests** was considered and dropped: it would leave multi-item
  requests unable to open the breaker during a real outage.

## Solution

Two changes in `src/biomapper2/utils.py`, plus wiring in `src/biomapper2/api/routes/mapping.py`.

**1. One failure per HTTP request.** Each mapping route creates a `BreakerScope` once and passes it to
every executor call it makes:

```python
# utils.py
class BreakerScope:
    """One API request's share of the shared breaker: it can add at most one failure."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failure_counted = False

    def claim_failure(self) -> bool:
        with self._lock:
            if self._failure_counted:
                return False
            self._failure_counted = True
            return True


def record_breaker_failure(api_ctx: "ApiRequestContext | None") -> None:
    scope = api_ctx.breaker_scope if api_ctx is not None else None
    if scope is None or scope.claim_failure():
        _CIRCUIT_BREAKER.record_failure()
    else:
        _CIRCUIT_BREAKER.settle_unsettled()  # already counted: still reopen a failed half-open probe
```

```python
# routes/mapping.py
def _run_with_api_context(func: Any, *args: Any, _breaker_scope: utils.BreakerScope, **kwargs: Any) -> Any:
    token = utils.set_api_context(breaker_scope=_breaker_scope)
    ...

async def map_batch(...):
    breaker_scope = utils.BreakerScope()
    ...
    await loop.run_in_executor(executor, partial(_run_with_api_context, _breaker_scope=breaker_scope), ...)
```

`_breaker_scope` is a required keyword-only argument, so a call site that omits it raises `TypeError`
(and is a type error where the checker understands `partial`). `run_in_executor` does not copy context
into the worker thread (unlike `asyncio.to_thread`), so the scope crosses the thread boundary as an
explicit argument and `_run_with_api_context` sets the `ContextVar` inside the worker.

**2. Only availability failures count.** A plain 500 means Kestrel answered about this input:

```python
_BREAKER_UNAVAILABLE_STATUSES: frozenset[int] = frozenset({429, 502, 503, 504})

if status in _BREAKER_UNAVAILABLE_STATUSES:
    record_breaker_failure(api_ctx)
elif status is not None and 500 <= status < 600:
    _CIRCUIT_BREAKER.record_answered()  # closes a HALF_OPEN probe; leaves CLOSED counts alone
# (all guarded by breaker_active; a non-429 4xx still settles as record_success())
```

Timeouts and connection errors still count, through the same per-request helper; `provenance.py`'s
`/health` probe uses it too. Startup sets `use_circuit_breaker=False`, so it never touches the breaker.

## Why This Works

The breaker is shared, so its input must be a signal about Kestrel, not about any one caller. Two
things made it a per-caller signal: failures were counted per attempt rather than per request, and a
per-input error (500) was read as unavailability. Scoping counts to the request means opening needs
6 *distinct* failing requests, and a payload can no longer produce a 500-driven failure. The fault
gate (Lines 1a to 6) still passes, so real outages still open the breaker.

**What this does not close** (found by review of this doc; tracked in Phenome-Health/biomapper2#176):

- **A payload-induced timeout still counts.** A request that makes Kestrel exceed the timeout (a very
  large batch, a pathological search string) adds one failure, so 6 such requests can open the breaker.
- **Keeping it open is cheap.** After the cooldown the breaker is half-open and one failing request
  reopens it, so after the first 6, one failure per 5 s cooldown sustains the outage. The nginx per-IP
  limit does not bound that.
- **429 may be the caller's own volume.** It counts as unavailability, so a few bursty callers can open
  the breaker for everyone.
- **A non-429 4xx resets the count.** That branch calls `record_success()`, so a caller who sends
  inputs Kestrel rejects with 400/404/422 can keep the breaker closed during a flapping outage.
- **Unscoped contexts count every failure.** Only the route wrapper requires a scope;
  `set_api_context` defaults it to `None`, so a new entry point (a job runner, a CLI) that builds a
  context without one regains the original flaw.

## Prevention

- **Ask "whose failure is this?" for any process-wide counter fed by request traffic.** A breaker,
  rate budget or health score shared across callers needs its inputs scoped so one caller cannot move
  it for everyone, in either direction (opening it, or clearing it).
- **Separate per-input errors from availability errors before they reach a breaker,** and write the
  set down as a named constant (as above) so it is reviewed as policy.
- **Require the scope at every context entry point,** not only at the route wrapper.
- **One test per rule** in `tests/test_kestrel_breaker_scope.py`.
- **Run a security review on promotion,** not just a code review. This passed every functional check
  and an automated reviewer at 5/5; only a security-focused pass looked at shared state as an attack
  surface.

## Related Issues

- trentleslie/biomapper2 #112 (breaker introduced) and #113 (this fix); Phenome-Health/biomapper2
  #165 and #166 (promotion), released in v1.5.1.
- Phenome-Health/biomapper2#168: the same class of flaw on the RefMet breaker, where an id-lookup
  miss counted toward a process-wide breaker and dropped RefMet for unrelated names. Fixed in
  trentleslie/biomapper2#115 (promoted as Phenome-Health/biomapper2 #169 and #170, released in v1.5.2).
- `docs/solutions/integration-issues/slash-encoding-breaks-refmet-lipidmaps-name-lookups-2026-10-27.md`:
  the RefMet breaker, and the rule that downgrading errors to protect a breaker needs a per-class canary.
- `docs/solutions/best-practices/nginx-edge-rate-limit-for-sync-blocking-fastapi-2026-11-05.md`:
  the per-IP edge limit in front of the API.
