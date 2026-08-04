"""Shuffled-annotation negative control — the benchmark's own validity gate.

Permute the entity->measurement mapping (right entities, WRONG directions) and
re-run Arm 1. A grounded pipeline should now fail; a prior-parroting LLM will
still 'succeed'. The gap between the real and shuffled runs is the validity check
(spec §5). If the gap is small, the instance is being answered from priors and the
result must be discounted — this is a REQUIRED gate from day one, not an add-on.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .config import NorthStarConfig
from .mess import MessResult

MIN_VALID_GAP = 0.20


def shuffle_measurements(messy_result: MessResult, config: NorthStarConfig, seed: int) -> MessResult:
    df = messy_result.messy_df.copy(deep=True)
    directions = list(df[config.direction_column])
    rng = random.Random(seed)
    # Derangement-ish permutation: reshuffle until at least one row's value moves
    # (for n>1) so the control genuinely mis-assigns measurements.
    if len(directions) > 1 and len(set(directions)) > 1:
        shuffled = directions[:]
        for _ in range(100):
            rng.shuffle(shuffled)
            if shuffled != directions:
                break
        df[config.direction_column] = shuffled
    return MessResult(
        messy_df=df,
        hidden_mapping=messy_result.hidden_mapping,
        operators_applied=messy_result.operators_applied,
    )


@dataclass(frozen=True)
class ValidityReport:
    real_metric: float
    shuffled_metric: float
    gap: float
    passed: bool
    min_gap: float


def validity_gate(real_score: float, shuffled_score: float, min_gap: float = MIN_VALID_GAP) -> ValidityReport:
    gap = real_score - shuffled_score
    return ValidityReport(
        real_metric=real_score,
        shuffled_metric=shuffled_score,
        gap=gap,
        passed=gap >= min_gap,
        min_gap=min_gap,
    )
