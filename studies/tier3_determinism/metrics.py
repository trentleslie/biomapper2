"""Tier-3 metrics.

Primary result (answer stability): per query, how many *distinct* top-1 answers the
LLM gives across N repeats -- the gget-virus "106/15/5" shape. BioMapper's counterpart
is a flat 1 for every query (variance = 0), demonstrated by ``is_byte_identical``.

Secondary result (accuracy dispersion): accuracy@1 per run, then mean +/- SD, min-max,
and a seeded bootstrap CI. The *spread* is the headline, not the mean.
"""

from __future__ import annotations

from collections import Counter

import numpy as np
from pydantic import BaseModel

from studies.tier3_determinism.models import ArmACall, ArmBCall

UNKNOWN_BUCKET = "unknown"


class DistinctAnswerStat(BaseModel):
    query_id: str
    n_runs: int
    n_distinct: int
    answer_counts: dict[str, int]
    majority_answer: str
    majority_fraction: float


class Dispersion(BaseModel):
    n_runs: int
    mean: float
    sd: float
    min: float
    max: float
    ci_lower: float
    ci_upper: float


class Contrast(BaseModel):
    arm_a_worst: float
    arm_a_best: float
    arm_a_spread: float
    biomapper_accuracy: float
    gap_worst_vs_biomapper: float
    gap_best_vs_biomapper: float


def _answer_key(call: ArmACall) -> str:
    return call.parsed_curie if call.parsed_curie is not None else UNKNOWN_BUCKET


def distinct_answer_distribution(calls: list[ArmACall]) -> dict[str, DistinctAnswerStat]:
    """Per query, the distribution of distinct top-1 answers across its N repeats."""
    by_query: dict[str, list[ArmACall]] = {}
    for call in calls:
        by_query.setdefault(call.query_id, []).append(call)

    out: dict[str, DistinctAnswerStat] = {}
    for query_id, group in by_query.items():
        counts = Counter(_answer_key(c) for c in group)
        top_answer, top_count = counts.most_common(1)[0]
        n_runs = len(group)
        out[query_id] = DistinctAnswerStat(
            query_id=query_id,
            n_runs=n_runs,
            n_distinct=len(counts),
            answer_counts=dict(counts),
            majority_answer=top_answer,
            majority_fraction=top_count / n_runs,
        )
    return out


def accuracy_per_run(calls: list[ArmACall]) -> list[float]:
    """accuracy@1 for each independent run (grouped by repeat index).

    Queries whose ``is_correct`` is ``None`` (no gold) are excluded from the ratio.
    Returns one accuracy per repeat index, ordered by repeat index.
    """
    by_repeat: dict[int, list[ArmACall]] = {}
    for call in calls:
        by_repeat.setdefault(call.repeat_index, []).append(call)

    accuracies: list[float] = []
    for repeat in sorted(by_repeat):
        scored = [c for c in by_repeat[repeat] if c.is_correct is not None]
        if not scored:
            continue
        accuracies.append(sum(1 for c in scored if c.is_correct) / len(scored))
    return accuracies


def bootstrap_ci(values: list[float], n_boot: int = 2000, seed: int = 0, alpha: float = 0.05) -> tuple[float, float]:
    """Seeded percentile bootstrap CI for the mean of ``values`` (deterministic)."""
    if not values:
        return (0.0, 0.0)
    arr = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    means = arr[rng.integers(0, len(arr), size=(n_boot, len(arr)))].mean(axis=1)
    lo = float(np.quantile(means, alpha / 2))
    hi = float(np.quantile(means, 1 - alpha / 2))
    return (lo, hi)


def dispersion(accuracies: list[float], seed: int = 0, n_boot: int = 2000) -> Dispersion:
    """Mean +/- SD, min-max, and a seeded bootstrap CI over per-run accuracies."""
    arr = np.asarray(accuracies, dtype=float)
    lo, hi = bootstrap_ci(accuracies, n_boot=n_boot, seed=seed)
    sd = float(arr.std(ddof=1)) if arr.size > 1 else 0.0
    return Dispersion(
        n_runs=arr.size,
        mean=float(arr.mean()) if arr.size else 0.0,
        sd=sd,
        min=float(arr.min()) if arr.size else 0.0,
        max=float(arr.max()) if arr.size else 0.0,
        ci_lower=lo,
        ci_upper=hi,
    )


def is_byte_identical(calls: list[ArmBCall]) -> bool:
    """True iff every query resolved to exactly one distinct id across all its repeats."""
    by_query: dict[str, set[str | None]] = {}
    for call in calls:
        by_query.setdefault(call.query_id, set()).add(call.chosen_kg_id)
    return all(len(answers) == 1 for answers in by_query.values())


def contrast(arm_a_accuracies: list[float], arm_b_accuracy: float) -> Contrast:
    """The headline contrast: LLM worst/best-run spread vs BioMapper's single value."""
    worst = min(arm_a_accuracies)
    best = max(arm_a_accuracies)
    return Contrast(
        arm_a_worst=worst,
        arm_a_best=best,
        arm_a_spread=best - worst,
        biomapper_accuracy=arm_b_accuracy,
        gap_worst_vs_biomapper=arm_b_accuracy - worst,
        gap_best_vs_biomapper=arm_b_accuracy - best,
    )
