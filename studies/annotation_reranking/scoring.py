import math
from studies.annotation_reranking.models_data import RerankResult


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def accuracy(
    results: list[RerankResult],
    retrievable_only: bool = False,
) -> tuple[float, tuple[float, float]]:
    """Return (point estimate, Wilson 95% CI) for accuracy.

    Parameters
    ----------
    results:
        All RerankResult objects to consider.
    retrievable_only:
        When True, restrict to results whose ``regime`` is ``"retrievable"``
        (in addition to the usual ``is_correct is not None`` filter).
        This properly conditions accuracy on retrievability — cases where the
        correct answer was not in the candidate window cannot be reranked
        correctly and should be excluded from the reranker's skill estimate.
    """
    scored = [r for r in results if r.is_correct is not None]
    if retrievable_only:
        scored = [r for r in scored if r.regime == "retrievable"]
    n = len(scored)
    k = sum(1 for r in scored if r.is_correct)
    return (k / n if n else 0.0, wilson_ci(k, n))


def _binom_pmf(k: int, n: int, p: float = 0.5) -> float:
    return math.comb(n, k) * p**k * (1 - p) ** (n - k)


def mcnemar_exact(
    a_correct: list[bool], b_correct: list[bool]
) -> tuple[int, int, float]:
    b01 = sum(1 for a, b in zip(a_correct, b_correct) if (not a) and b)
    b10 = sum(1 for a, b in zip(a_correct, b_correct) if a and (not b))
    n = b01 + b10
    if n == 0:
        return (b01, b10, 1.0)
    x = min(b01, b10)
    tail = sum(_binom_pmf(i, n) for i in range(0, x + 1))
    return (b01, b10, min(1.0, 2 * tail))


def min_discordant_for_sig(n_discordant: int, alpha: float = 0.05) -> int:
    """Smallest all-one-direction discordant count whose two-sided exact p < alpha."""
    for m in range(1, n_discordant + 1):
        if 2 * _binom_pmf(0, m) < alpha:
            return m
    return n_discordant + 1
