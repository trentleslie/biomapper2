"""Unit 3 — comparable-core scorer: structure-oracle Top-1 accuracy.

Correctness is adjudicated by InChIKey *connectivity* (first block), never by identifier
identity. The gold block comes from the dataset's own curated InChIKey column (no resolver,
zero shared infra with the SUT — the circularity guard). Only BioMapper's *prediction*
(``chosen_kg_id``) is resolved through the KG structure oracle.

A prediction whose ChEBI id differs from gold but shares connectivity is CORRECT; a
prediction with different connectivity is INCORRECT. Rows whose gold has no InChIKey are
excluded from the accuracy denominator but still counted in coverage. Rows whose predicted
structure had to come from the name fallback (not the KG record) are flagged into a
segregation bucket so a reviewer can see how many corrects leaned on the fallback path.
"""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd

from ..config import DatasetConfig

CHOSEN_COL = "chosen_kg_id"


class StructureOracle(Protocol):
    """KG-first structure resolution for a predicted node id.

    ``kg_block`` returns the InChIKey first-block from the KG record alone (None if the KG
    carries no structure). ``resolved_block`` additionally consults the name fallback
    (MW -> PubChem). The gap between the two is the fallback-segregation signal.
    """

    def kg_block(self, node_id: str) -> str | None: ...
    def resolved_block(self, node_id: str) -> str | None: ...


def first_block(inchikey: Any) -> str | None:
    """First InChIKey block (the 2-D connectivity skeleton), or None if absent/blank."""
    if inchikey is None:
        return None
    if isinstance(inchikey, float):  # NaN
        return None
    s = str(inchikey).strip()
    if not s or s.lower() == "nan":
        return None
    return s.split("-")[0]


def _has_prediction(chosen: Any) -> bool:
    if chosen is None or (isinstance(chosen, float) and pd.isna(chosen)):
        return False
    s = str(chosen).strip()
    return bool(s) and s.lower() != "nan"


def score_structure_oracle(
    mapped_df: pd.DataFrame,
    config: DatasetConfig,
    oracle: StructureOracle,
    vocab: str | None = None,
) -> dict[str, Any]:
    """Compute Top-1 accuracy (structure-oracle) + coverage + the fallback bucket."""
    total = len(mapped_df)
    n_predicted = 0
    scored = 0  # accuracy denominator: rows with gold structure
    correct = 0
    fallback_rows: list[str] = []
    per_row: list[dict[str, Any]] = []

    for _, row in mapped_df.iterrows():
        gold_block = first_block(row.get(config.gold_inchikey_column))
        chosen = row.get(CHOSEN_COL)
        has_pred = _has_prediction(chosen)
        if has_pred:
            n_predicted += 1

        predicted_block: str | None = None
        needed_fallback = False
        if has_pred:
            chosen_id = str(chosen).strip()
            kg_b = oracle.kg_block(chosen_id)
            predicted_block = oracle.resolved_block(chosen_id)
            needed_fallback = kg_b is None and predicted_block is not None
            if needed_fallback:
                fallback_rows.append(chosen_id)

        is_scored = gold_block is not None
        is_correct = bool(is_scored and predicted_block is not None and predicted_block == gold_block)
        if is_scored:
            scored += 1
            if is_correct:
                correct += 1

        per_row.append(
            {
                "name": row.get(config.name_column),
                "chosen_kg_id": None if not has_pred else str(chosen).strip(),
                "gold_block": gold_block,
                "predicted_block": predicted_block,
                "scored": is_scored,
                "correct": is_correct,
                "needed_fallback": needed_fallback,
            }
        )

    accuracy = (correct / scored) if scored else None
    return {
        "vocab": vocab,
        "input_type": config.input_type,
        "comparable_core": {
            "metric": "top1_accuracy",
            "top1_accuracy": accuracy,
            "correct": correct,
            "scored_denominator": scored,
        },
        "coverage": {
            "n_predicted": n_predicted,
            "total": total,
            "fraction": (n_predicted / total) if total else 0.0,
        },
        "fallback_bucket": {"count": len(fallback_rows), "rows": fallback_rows},
        "per_row": per_row,
    }
