"""Interval and paired-test primitives for the external-benchmark report.

Pure functions: no I/O, no network, no randomness. Every parameter that shapes a number is an
explicit argument and is echoed back in the returned mapping, so the artifact that consumes these
functions can record how each interval was computed rather than asserting it in prose.

Why closed forms rather than a bootstrap
----------------------------------------
The default paired interval here is a score interval, not a resampled one. Three reasons, in
descending order of how much trouble each would have caused in print:

1. **Coherence with the test.** The score interval for the paired difference and the McNemar test
   are built from the same statistic, so the interval cannot exclude zero while the p-value says
   "no difference", nor span zero while the p-value is vanishingly small. A resampled interval has
   no such guarantee, and an interval spanning zero printed beside a very small McNemar p is
   exactly the kind of internal contradiction a reviewer opens first.
2. **Behaviour at zero discordance.** Several real contrasts in this suite are all-one-way: every
   discordant row moves in the same direction. A percentile bootstrap degenerates there. The score
   interval is defined.
3. **Determinism.** No seed, so the published number cannot depend on a resampling draw. Rerunning
   the report reproduces the table bit for bit.

A resampled interval is retained only if a genuinely non-analytic target statistic is named. None
is, so ``seed`` and ``n_resamples`` appear nowhere in this module; ``TestNoHiddenRandomness`` in the
test suite enforces that, and adding either parameter later is the moment to record it in the
artifact header.

Pairing is a precondition, not a convenience
--------------------------------------------
Every paired function goes through :func:`assert_paired`, which checks row-id *identity* and
row-id *uniqueness* — not merely equal lengths. A join on a non-unique key (a query name that
repeats) manufactures discordant pairs out of nothing, and equal-length arrays cannot detect it.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Any

__all__ = [
    "DEGENERATE_MCNEMAR_P",
    "Z_95",
    "PairingError",
    "assert_paired",
    "discordance",
    "mcnemar",
    "newcombe_difference",
    "newcombe_paired_mover",
    "paired_counts_from_rows",
    "tango_paired_difference",
    "wilson_interval",
]

# Two-sided normal quantile at the conventional level. Named so the artifact can record it.
Z_95 = 1.959963984540054

# The documented return when a test statistic is undefined. ``None`` rather than 1.0: a p-value of
# 1.0 asserts "no evidence of a difference", which is a claim. At zero discordance there is no
# statistic at all, and the artifact must be able to say so.
DEGENERATE_MCNEMAR_P: float | None = None

_DEGENERATE_NOTE = (
    "b + c == 0: no discordant pairs, so the McNemar statistic is undefined. Reported as undefined "
    "rather than as a non-significant p-value, which would be a claim the data cannot support."
)


class PairingError(ValueError):
    """Raised when two arms are not the same rows in the same order, keyed by unique row ids."""


# --------------------------------------------------------------------------------------------
# Single-proportion interval
# --------------------------------------------------------------------------------------------
def wilson_interval(k: int, n: int, z: float = Z_95) -> tuple[float | None, float | None]:
    """Score (Wilson) interval for a single binomial proportion.

    Chosen over the Wald interval because the suite's rates live near both boundaries: Wald emits a
    zero-width interval whenever a regime scores everything or nothing, which is the one place a
    reader most needs a width.

    Returns ``(None, None)`` when ``n == 0`` — an undefined interval, reported as undefined.
    """
    k = int(k)
    n = int(n)
    if k < 0 or n < 0:
        raise ValueError(f"wilson_interval requires non-negative counts, got k={k}, n={n}")
    if k > n:
        raise ValueError(f"wilson_interval requires k <= n, got k={k}, n={n}")
    if n == 0:
        return (None, None)
    denom = n + z * z
    center = (k + z * z / 2) / denom
    half = (z / denom) * math.sqrt(k * (n - k) / n + z * z / 4)
    lower = 0.0 if k == 0 else max(0.0, center - half)
    upper = 1.0 if k == n else min(1.0, center + half)
    return (lower, upper)


# --------------------------------------------------------------------------------------------
# Pairing guards
# --------------------------------------------------------------------------------------------
def assert_paired(
    row_ids_a: Sequence[Any],
    row_ids_b: Sequence[Any],
    flags_a: Sequence[Any],
    flags_b: Sequence[Any],
) -> None:
    """Refuse to treat two arms as paired unless they really are the same rows.

    Three separate failures, because each one has produced a different wrong number:

    * unequal lengths — the arms are not the same population;
    * unequal row ids at the same position — the arms are misaligned, so every "flip" is an
      artefact of ordering;
    * duplicate row ids — the join key is not a key, so a repeated query name silently fans out
      into several manufactured pairs. Length and ordering are both satisfied in that case, so
      only a uniqueness assertion catches it.
    """
    if not (len(row_ids_a) == len(row_ids_b) == len(flags_a) == len(flags_b)):
        raise PairingError(
            f"paired arms differ in length: ids {len(row_ids_a)}/{len(row_ids_b)}, flags {len(flags_a)}/{len(flags_b)}"
        )
    if len(set(row_ids_a)) != len(row_ids_a):
        raise PairingError(
            "row ids in arm A are not unique; a paired test keyed on a non-unique column "
            "manufactures discordant pairs wherever the key repeats"
        )
    if len(set(row_ids_b)) != len(row_ids_b):
        raise PairingError(
            "row ids in arm B are not unique; a paired test keyed on a non-unique column "
            "manufactures discordant pairs wherever the key repeats"
        )
    for i, (ida, idb) in enumerate(zip(row_ids_a, row_ids_b)):
        if ida != idb:
            raise PairingError(f"paired arms are misaligned at position {i}: {ida!r} != {idb!r}")


def discordance(
    arm_a: Sequence[Any],
    arm_b: Sequence[Any],
    row_ids_a: Sequence[Any] | None = None,
    row_ids_b: Sequence[Any] | None = None,
) -> tuple[int, int]:
    """Return ``(b, c)``: rows correct in A only, and rows correct in B only.

    The two directions are never collapsed. A pair of nearly equal opposing counts nets out to a
    negligible accuracy delta while leaving their *sum* of rows unstable, and only the split
    reports the second fact.
    """
    ids_a = list(range(len(arm_a))) if row_ids_a is None else list(row_ids_a)
    ids_b = list(range(len(arm_b))) if row_ids_b is None else list(row_ids_b)
    assert_paired(ids_a, ids_b, arm_a, arm_b)
    b = sum(1 for x, y in zip(arm_a, arm_b) if bool(x) and not bool(y))
    c = sum(1 for x, y in zip(arm_a, arm_b) if not bool(x) and bool(y))
    return (b, c)


def paired_counts_from_rows(
    rows_a: Iterable[dict],
    rows_b: Iterable[dict],
    *,
    id_key: str,
    flag_key: str,
) -> dict[str, Any]:
    """Align two per-row lists by row id (never by position) and return the paired counts.

    This is the only supported way to build a paired contrast from two result files: the row lists
    are aligned on ``id_key``, so a reordered or partially-populated arm cannot silently produce a
    positional pairing.
    """
    list_a = list(rows_a)
    list_b = list(rows_b)
    ids_a = [r.get(id_key) for r in list_a]
    ids_b = [r.get(id_key) for r in list_b]
    if len(set(ids_a)) != len(ids_a) or len(set(ids_b)) != len(ids_b):
        raise PairingError(f"row ids under {id_key!r} are not unique; refusing to pair")
    index_b = {r.get(id_key): r for r in list_b}
    missing = [i for i in ids_a if i not in index_b]
    if missing:
        raise PairingError(f"{len(missing)} row id(s) present in arm A and absent from arm B")
    if len(list_b) != len(list_a):
        raise PairingError(f"arms differ in size: {len(list_a)} vs {len(list_b)}")
    ordered_b = [index_b[i] for i in ids_a]
    flags_a = [bool(r.get(flag_key)) for r in list_a]
    flags_b = [bool(r.get(flag_key)) for r in ordered_b]
    b, c = discordance(flags_a, flags_b, ids_a, ids_a)
    return {
        "n": len(list_a),
        "k_a": sum(flags_a),
        "k_b": sum(flags_b),
        "b": b,
        "c": c,
        "id_key": id_key,
        "flag_key": flag_key,
    }


# --------------------------------------------------------------------------------------------
# McNemar
# --------------------------------------------------------------------------------------------
def _binom_cdf_half(k: int, n: int) -> float:
    """P(X <= k) for X ~ Binomial(n, 1/2), computed exactly from binomial coefficients."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    return sum(math.comb(n, i) for i in range(k + 1)) / (2.0**n)


def _binom_pmf_half(k: int, n: int) -> float:
    if k < 0 or k > n:
        return 0.0
    return math.comb(n, k) / (2.0**n)


def mcnemar(b: int, c: int) -> dict[str, Any]:
    """Exact and mid-p McNemar tests on the two discordant counts.

    Conditional on ``b + c``, the discordant rows are a sign test at one half, so the exact
    two-sided p-value is the binomial tail doubled. The mid-p variant subtracts half the point mass
    at the observed count; it is never more conservative than the exact test and is the one to
    prefer when the discordant total is small.

    At ``b + c == 0`` both are undefined and both are returned as
    :data:`DEGENERATE_MCNEMAR_P`, with ``degenerate`` set. Returning a p-value of one there would
    assert an absence of difference that the data cannot support.
    """
    b = int(b)
    c = int(c)
    if b < 0 or c < 0:
        raise ValueError(f"mcnemar requires non-negative discordant counts, got b={b}, c={c}")
    total = b + c
    if total == 0:
        return {
            "b": b,
            "c": c,
            "n_discordant": 0,
            "p_exact": DEGENERATE_MCNEMAR_P,
            "p_midp": DEGENERATE_MCNEMAR_P,
            "degenerate": True,
            "note": _DEGENERATE_NOTE,
            "method": "exact binomial sign test (two-sided), conditional on b + c",
        }
    m = min(b, c)
    p_exact = min(1.0, 2.0 * _binom_cdf_half(m, total))
    p_midp = min(1.0, 2.0 * (_binom_cdf_half(m - 1, total) + 0.5 * _binom_pmf_half(m, total)))
    return {
        "b": b,
        "c": c,
        "n_discordant": total,
        "p_exact": p_exact,
        "p_midp": p_midp,
        "degenerate": False,
        "note": "",
        "method": "exact binomial sign test (two-sided), conditional on b + c",
    }


# --------------------------------------------------------------------------------------------
# Paired difference intervals
# --------------------------------------------------------------------------------------------
def _constrained_p21(b: int, c: int, m: int, n: int, delta: float) -> float:
    """Constrained MLE of the "B-only" cell probability at a fixed paired difference.

    Profiling the paired multinomial log-likelihood at fixed ``delta`` leaves one free cell
    probability whose score equation is a quadratic; the feasible root is taken. Solved by
    bracketed bisection on the score rather than by the closed-form root so that the sign cases
    (``delta`` positive, negative, at a boundary) cannot be got subtly wrong.
    """
    lo = max(0.0, -delta)
    hi = (1.0 - delta) / 2.0
    if hi <= lo:
        return max(lo, 0.0)
    eps = 1e-12

    def score(x: float) -> float:
        return b / (x + delta) + c / x - 2.0 * m / (1.0 - 2.0 * x - delta)

    left = lo + eps * max(1.0, hi - lo)
    right = hi - eps * max(1.0, hi - lo)
    if left >= right:
        return max(lo, 0.0)
    s_left = score(left)
    s_right = score(right)
    if s_left <= 0.0:
        return left
    if s_right >= 0.0:
        return right
    for _ in range(200):
        mid = 0.5 * (left + right)
        if score(mid) > 0.0:
            left = mid
        else:
            right = mid
    return 0.5 * (left + right)


def _paired_score_z(b: int, c: int, m: int, n: int, delta: float) -> float:
    """Score statistic for the paired difference, evaluated at ``delta``."""
    p21 = _constrained_p21(b, c, m, n, delta)
    var = n * (2.0 * p21 + delta * (1.0 - delta))
    numerator = (b - c) - n * delta
    if var <= 0.0:
        if abs(numerator) < 1e-12:
            return 0.0
        return math.inf if numerator > 0 else -math.inf
    return numerator / math.sqrt(var)


def tango_paired_difference(*, b: int, c: int, n: int, z: float = Z_95) -> dict[str, Any]:
    """Score interval for the difference of two *paired* proportions.

    ``b`` and ``c`` are the discordant counts (correct in the first arm only, and in the second arm
    only); the point estimate is their difference over ``n``. The interval inverts the same score
    statistic McNemar tests, so interval and p-value are coherent by construction, and it remains
    defined when every discordant row moves the same way.
    """
    b = int(b)
    c = int(c)
    n = int(n)
    if b < 0 or c < 0 or n <= 0:
        raise ValueError(f"tango_paired_difference requires b, c >= 0 and n > 0; got b={b}, c={c}, n={n}")
    if b + c > n:
        raise ValueError(f"discordant counts exceed the row count: b + c = {b + c} > n = {n}")
    concordant = n - b - c
    estimate = (b - c) / n

    def solve(target: float, lo: float, hi: float) -> float:
        # Z is decreasing in delta; bisect for the delta where it crosses the target quantile.
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if _paired_score_z(b, c, concordant, n, mid) > target:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    lower = solve(z, -1.0 + 1e-12, estimate)
    upper = solve(-z, estimate, 1.0 - 1e-12)
    return {
        "estimate": estimate,
        "lower": lower,
        "upper": upper,
        "b": b,
        "c": c,
        "n": n,
        "z": z,
        "paired": True,
        "degenerate": (b + c) == 0,
        "method": "score (asymptotic) interval for the paired difference of proportions",
    }


def newcombe_paired_mover(*, k1: int, k2: int, b: int, c: int, n: int, z: float = Z_95) -> dict[str, Any]:
    """Method-of-variance-estimates-recovery interval for the paired difference.

    Built from the two arms' Wilson intervals plus the observed within-pair association, so it
    inherits Wilson's boundary behaviour on each arm. Carried alongside the score interval as a
    second closed form: the two use different information, and a wide disagreement between them is
    a signal that the pairing itself deserves a second look.
    """
    k1, k2, b, c, n = int(k1), int(k2), int(b), int(c), int(n)
    if n <= 0:
        raise ValueError(f"newcombe_paired_mover requires n > 0, got {n}")
    if (k1 - k2) != (b - c):
        raise ValueError(
            f"arms are inconsistent with the discordance: k1 - k2 = {k1 - k2} but b - c = {b - c}; "
            "the two arms are not scored over the same rows"
        )
    a = k1 - b  # correct in both
    d = n - a - b - c  # wrong in both
    if min(a, b, c, d) < 0:
        raise ValueError(f"implied paired table has a negative cell: a={a}, b={b}, c={c}, d={d}")
    p1 = k1 / n
    p2 = k2 / n
    l1, u1 = wilson_interval(k1, n, z)
    l2, u2 = wilson_interval(k2, n, z)
    assert l1 is not None and u1 is not None and l2 is not None and u2 is not None

    margins = (a + b) * (c + d) * (a + c) * (b + d)
    if margins == 0:
        phi = 0.0
    else:
        phi = (a * d - b * c) / math.sqrt(margins)
        if (a * d - b * c) > 0:
            phi = max(phi - 1.0 / (2.0 * n), 0.0)
    estimate = p1 - p2
    lower = estimate - math.sqrt(max(0.0, (p1 - l1) ** 2 - 2 * phi * (p1 - l1) * (u2 - p2) + (u2 - p2) ** 2))
    upper = estimate + math.sqrt(max(0.0, (u1 - p1) ** 2 - 2 * phi * (u1 - p1) * (p2 - l2) + (p2 - l2) ** 2))
    return {
        "estimate": estimate,
        "lower": lower,
        "upper": upper,
        "k1": k1,
        "k2": k2,
        "b": b,
        "c": c,
        "n": n,
        "z": z,
        "phi": phi,
        "paired": True,
        "degenerate": (b + c) == 0,
        "method": "Newcombe MOVER interval for the paired difference of proportions",
    }


def newcombe_difference(k1: int, n1: int, k2: int, n2: int, z: float = Z_95) -> dict[str, Any]:
    """Interval for the difference of two *independent* proportions.

    Reserved for comparison against a published external baseline, and only when its preconditions
    hold. They are returned in the result so the artifact records them next to the number rather
    than leaving them to a reader's charity: the two samples must be independent, must estimate the
    same quantity, and the baseline's denominator must be the one actually reported.

    When the comparison is genuinely paired — the same items scored by both systems — this is the
    wrong function; use :func:`tango_paired_difference`, which is both narrower and coherent with
    the significance test.
    """
    preconditions = (
        "two independent samples; both estimate the same quantity under the same scoring rule; the "
        "external denominator is the one the source reports. If any fails, no difference statistic "
        "is licensed and the two point estimates must be reported side by side without one."
    )
    lo1, hi1 = wilson_interval(k1, n1, z)
    lo2, hi2 = wilson_interval(k2, n2, z)
    if lo1 is None or lo2 is None or hi1 is None or hi2 is None:
        return {
            "estimate": None,
            "lower": None,
            "upper": None,
            "paired": False,
            "preconditions": preconditions,
            "method": "Newcombe square-and-add interval for the difference of independent proportions",
        }
    p1 = k1 / n1
    p2 = k2 / n2
    estimate = p1 - p2
    return {
        "estimate": estimate,
        "lower": estimate - math.sqrt((p1 - lo1) ** 2 + (hi2 - p2) ** 2),
        "upper": estimate + math.sqrt((hi1 - p1) ** 2 + (p2 - lo2) ** 2),
        "k1": k1,
        "n1": n1,
        "k2": k2,
        "n2": n2,
        "z": z,
        "paired": False,
        "preconditions": preconditions,
        "method": "Newcombe square-and-add interval for the difference of independent proportions",
    }
