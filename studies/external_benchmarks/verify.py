"""Unit 4 (layer a) — reconciliation.

Recomputes every run-derived number in ``results.json`` from the raw mapped splits via an
*independent* path (not by calling the scorer module), and blocks on any mismatch, naming
the metric. This catches a tampered/stale results file — a self-consistent-but-wrong number
cannot silently reach a figure. It does NOT check whether the artifacts reflect reality;
that is validation's job (see validate.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .config import DatasetConfig
from .scorers.structure_oracle_scorer import CHOSEN_COL, StructureOracle, _has_prediction, first_block

TOL = 1e-9


@dataclass
class ReconcileReport:
    passed: bool
    mismatches: list[dict[str, Any]] = field(default_factory=list)

    def add(self, metric: str, expected: Any, recomputed: Any) -> None:
        self.passed = False
        self.mismatches.append({"metric": metric, "expected": expected, "recomputed": recomputed})


def _independent_recompute(mapped_df: pd.DataFrame, config: DatasetConfig, oracle: StructureOracle) -> dict[str, Any]:
    """A deliberately separate recomputation (no scorer import for the arithmetic)."""
    total = len(mapped_df)
    predicted = 0
    scored = 0
    correct = 0
    fallback = 0
    for _, row in mapped_df.iterrows():
        gb = first_block(row.get(config.gold_inchikey_column))
        chosen = row.get(CHOSEN_COL)
        if _has_prediction(chosen):
            predicted += 1
            cid = str(chosen).strip()
            kg = oracle.kg_block(cid)
            rb = oracle.resolved_block(cid)
            if kg is None and rb is not None:
                fallback += 1
            if gb is not None and rb is not None and rb == gb:
                correct += 1
        if gb is not None:
            scored += 1
    return {
        "top1_accuracy": (correct / scored) if scored else None,
        "correct": correct,
        "scored_denominator": scored,
        "coverage_fraction": (predicted / total) if total else 0.0,
        "n_predicted": predicted,
        "match_rate": (predicted / total) if total else None,
        "matched": predicted,
        "fallback_count": fallback,
    }


def _num_eq(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= TOL


def reconcile(
    results: dict[str, Any],
    mapped_df: pd.DataFrame,
    config: DatasetConfig,
    oracle: StructureOracle,
) -> ReconcileReport:
    """Recompute and compare. ``results`` is the structure-oracle + paper-metric bundle
    for one vocab: ``{"structure": <score_structure_oracle out>, "paper": <paper_metric out>}``.
    """
    report = ReconcileReport(passed=True)
    recomputed = _independent_recompute(mapped_df, config, oracle)

    core = results.get("structure", {}).get("comparable_core", {})
    cov = results.get("structure", {}).get("coverage", {})
    bucket = results.get("structure", {}).get("fallback_bucket", {})
    paper = results.get("paper", {})

    if not _num_eq(core.get("top1_accuracy"), recomputed["top1_accuracy"]):
        report.add("top1_accuracy", core.get("top1_accuracy"), recomputed["top1_accuracy"])
    if core.get("correct") != recomputed["correct"]:
        report.add("correct", core.get("correct"), recomputed["correct"])
    if core.get("scored_denominator") != recomputed["scored_denominator"]:
        report.add("scored_denominator", core.get("scored_denominator"), recomputed["scored_denominator"])
    if not _num_eq(cov.get("fraction"), recomputed["coverage_fraction"]):
        report.add("coverage_fraction", cov.get("fraction"), recomputed["coverage_fraction"])
    if bucket.get("count") != recomputed["fallback_count"]:
        report.add("fallback_count", bucket.get("count"), recomputed["fallback_count"])
    if paper and not _num_eq(paper.get("match_rate"), recomputed["match_rate"]):
        report.add("match_rate", paper.get("match_rate"), recomputed["match_rate"])

    return report
