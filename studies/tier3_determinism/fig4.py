"""Fig-4 assembly: the money figure's underlying data.

Left/primary: per-query distinct-answer distribution -- for Arm A a spread of
distinct-answer counts (the "106/15/5" shape), for BioMapper a flat 1 everywhere.
Right/secondary: the accuracy dispersion band -- Arm A's mean+/-SD / min-max /
bootstrap CI vs BioMapper's single point.

One Arm-A panel per (model, temperature) cell so the figure can show a panel per
model with temp overlays.
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel

from studies.tier3_determinism import metrics
from studies.tier3_determinism.metrics import Contrast, Dispersion, DistinctAnswerStat
from studies.tier3_determinism.models import ArmACall, ArmBCall


class ArmAPanel(BaseModel):
    model_label: str
    model_id: str
    provider: str
    temperature: float
    n_queries: int
    distinct_count_histogram: dict[int, int]  # n_distinct -> number of queries
    per_query: list[DistinctAnswerStat]
    dispersion: Dispersion
    contrast: Contrast | None


class BioMapperPanel(BaseModel):
    n_queries: int
    byte_identical: bool
    per_query_distinct: dict[str, int]
    accuracy: float


class Fig4Data(BaseModel):
    arm_a: list[ArmAPanel]
    biomapper: BioMapperPanel


def _biomapper_accuracy(arm_b: list[ArmBCall]) -> tuple[float, dict[str, int]]:
    by_query: dict[str, list[ArmBCall]] = {}
    for call in arm_b:
        by_query.setdefault(call.query_id, []).append(call)
    per_query_distinct = {q: len({c.chosen_kg_id for c in calls}) for q, calls in by_query.items()}
    scored = [calls[0] for calls in by_query.values() if calls[0].is_correct is not None]
    accuracy = (sum(1 for c in scored if c.is_correct) / len(scored)) if scored else 0.0
    return accuracy, per_query_distinct


def build_fig4(arm_a: list[ArmACall], arm_b: list[ArmBCall]) -> Fig4Data:
    arm_b_accuracy, per_query_distinct = _biomapper_accuracy(arm_b)

    # group Arm-A calls into (model, temperature) panels
    groups: dict[tuple[str, float], list[ArmACall]] = {}
    for call in arm_a:
        groups.setdefault((call.model_label, call.temperature), []).append(call)

    panels: list[ArmAPanel] = []
    for (label, temp), calls in sorted(groups.items()):
        dist = metrics.distinct_answer_distribution(calls)
        histogram = dict(Counter(stat.n_distinct for stat in dist.values()))
        accuracies = metrics.accuracy_per_run(calls)
        contrast = metrics.contrast(accuracies, arm_b_accuracy) if accuracies else None
        sample = calls[0]
        panels.append(
            ArmAPanel(
                model_label=label,
                model_id=sample.model_id,
                provider=sample.provider,
                temperature=temp,
                n_queries=len(dist),
                distinct_count_histogram=histogram,
                per_query=list(dist.values()),
                dispersion=metrics.dispersion(accuracies),
                contrast=contrast,
            )
        )

    biomapper = BioMapperPanel(
        n_queries=len(per_query_distinct),
        byte_identical=metrics.is_byte_identical(arm_b) if arm_b else True,
        per_query_distinct=per_query_distinct,
        accuracy=arm_b_accuracy,
    )
    return Fig4Data(arm_a=panels, biomapper=biomapper)
