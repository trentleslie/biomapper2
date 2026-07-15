"""Provided-ID arm scorer — is the held-out TARGET cross-ref in BioMapper's equivalence set?

The SOURCE identifier is handed to BioMapper as a provided id (``provided_id_columns=[source]``,
``annotation_mode='none'``); the TARGET cross-ref is held out (scorer-only). Correctness is: the
held-out gold TARGET CURIE is present in BioMapper's returned equivalence set for the source —
i.e. ``chosen_kg_id`` (drawn from ``kg_ids_provided``) plus its ``kg_equivalent_ids`` expansion.

This is the same CURIE-equality comparison as ``curie_scorer`` (it reuses its
``predicted_curies`` helper), but the input regime is different: there is NO name-annotation path,
so the prediction is a pure provided-ID equivalence expansion. The reported metrics match the
``score_curie`` shape (comparable_core / coverage / curie_stats / per_namespace / per_row) so the
campaign report renders provided-ID datasets with the existing CURIE-arm row.

ANTI-TRIVIAL-100% GUARD (fail-loud, ``assert_target_held_out``): the scored TARGET column must be
disjoint from the provided source column AND the source namespace must be disjoint from every
target namespace. Either overlap would let the provided source id trivially self-match the gold,
scoring a fake 100%. The scorer refuses (raises ``TargetInProvidedError``) before scoring a row.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..config import ProvidedIdDatasetConfig
from .curie_scorer import _f1, predicted_curies, split_gold_curies


class TargetInProvidedError(ValueError):
    """Raised when the held-out gold TARGET is not actually held out (trivial-100% trap)."""


def assert_target_held_out(config: ProvidedIdDatasetConfig) -> None:
    """Fail loud if the gold target could self-match the provided source (anti-trivial-100%).

    Two ways the target can leak: (1) a gold target *column* equal to the provided source column,
    or (2) a gold target *namespace* equal to the source namespace (same-namespace round-trip). Both
    would silently score 100% off the provided id alone — so we refuse rather than report it.
    """
    provided = {config.source_id_column}
    gold_cols = {col for _, col in config.gold_target_columns}
    overlap = provided & gold_cols
    if overlap:
        raise TargetInProvidedError(
            f"{config.key}: TARGET column(s) {sorted(overlap)} are in provided_id_columns "
            f"({sorted(provided)}); the gold must be held out. Refusing to score a trivial 100%."
        )
    gold_ns = {ns.upper() for ns, _ in config.gold_target_columns}
    if config.source_namespace.upper() in gold_ns:
        raise TargetInProvidedError(
            f"{config.key}: source namespace {config.source_namespace!r} is also a target namespace "
            f"({sorted(gold_ns)}); a same-namespace round-trip self-matches. Refusing to score."
        )


def gold_target_curies(row: pd.Series, config: ProvidedIdDatasetConfig) -> set[str]:
    """Union of the held-out TARGET cross-ref CURIEs across the target namespaces for a row.

    Bare gold values (e.g. a raw InChIKey) are prefixed to their DECLARED target namespace so they
    match BioMapper's prefixed equivalence-set predictions; already-prefixed golds are untouched.
    """
    out: set[str] = set()
    for namespace, column in config.gold_target_columns:
        out |= split_gold_curies(row.get(column), namespace)
    return out


def score_provided_id(
    mapped_df: pd.DataFrame, config: ProvidedIdDatasetConfig, vocab: str | None = None
) -> dict[str, Any]:
    """Provided-ID CURIE-reachability scoring. One headline accuracy + coverage/precision/recall/F1.

    - scored denominator = rows carrying >=1 held-out gold TARGET cross-ref (accuracy/recall base).
    - correct = the row's predicted equivalence-set CURIEs intersect its gold TARGET CURIEs.
    - coverage = rows with >=1 predicted CURIE / total.
    - precision = correct / (rows with BOTH a prediction and a gold TARGET).
    - recall = correct / scored.
    """
    assert_target_held_out(config)  # fail-loud anti-trivial-100% guard, before any row is scored

    total = len(mapped_df)
    n_predicted = 0
    scored = 0
    both = 0
    correct = 0
    per_namespace: dict[str, dict[str, int]] = {ns: {"correct": 0, "scored": 0} for ns, _ in config.gold_target_columns}
    per_row: list[dict[str, Any]] = []

    for _, row in mapped_df.iterrows():
        preds = predicted_curies(row)  # chosen_kg_id + kg_equivalent_ids (the equivalence expansion)
        golds = gold_target_curies(row, config)
        has_pred = bool(preds)
        has_gold = bool(golds)
        if has_pred:
            n_predicted += 1
        if has_gold:
            scored += 1
        row_correct = bool(preds & golds)
        if has_pred and has_gold:
            both += 1
            if row_correct:
                correct += 1
        for namespace, column in config.gold_target_columns:
            ns_gold = split_gold_curies(row.get(column), namespace)
            if ns_gold:
                per_namespace[namespace]["scored"] += 1
                if preds & ns_gold:
                    per_namespace[namespace]["correct"] += 1
        per_row.append(
            {
                "source": row.get(config.source_id_column),
                "predicted": sorted(preds),
                "gold": sorted(golds),
                "scored": has_gold,
                "correct": has_gold and row_correct,
            }
        )

    top1 = (correct / scored) if scored else None
    precision = (correct / both) if both else None
    recall = (correct / scored) if scored else None
    return {
        "vocab": vocab,
        "arm": config.arm,
        "input_type": config.input_type,
        "mode": "provided_id",
        "source_namespace": config.source_namespace,
        "comparable_core": {
            "metric": "top1_accuracy",
            "top1_accuracy": top1,
            "correct": correct,
            "scored_denominator": scored,
        },
        "coverage": {"n_predicted": n_predicted, "total": total, "fraction": (n_predicted / total) if total else 0.0},
        "curie_stats": {
            "precision": precision,
            "recall": recall,
            "f1": _f1(precision, recall),
            "predicted_and_gold": both,
        },
        "per_namespace": per_namespace,
        "per_row": per_row,
    }
