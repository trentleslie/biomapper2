"""Pham name-disambiguation scorer — referent-set structural membership + ambiguity diagnostics.

The comparable core is a REFERENT-MEMBERSHIP rate, not a Top-1 identity match. A genuinely ambiguous
name (Pham et al. 2019) maps to a SET of structurally-distinct referents, so there is no single
"correct" structure to demand. Correctness is: given the bare ambiguous name, is BioMapper's chosen
structure (``chosen_kg_id`` -> InChIKey first-block via the KG oracle) a MEMBER of the name's
legitimate referent set? — i.e. did BioMapper land on a REAL referent rather than an off-target /
hallucinated structure.

Circularity guard (identical discipline to ``structure_oracle_scorer``): the gold referent blocks come
from the dataset's own held-out InChIKey column (INDEPENDENT MetaNetX ``chem_prop`` source — no
resolver, zero shared infra with the SUT). Only BioMapper's PREDICTION is resolved through the oracle.

Two reported numbers over ONE denominator (the ambiguous-name population), plus a diagnostic:
  - ``comparable_core`` = referent-membership rate = (# names whose chosen block is in the referent
    set) / (# scored names). A name with no prediction is a miss.
  - ``structural_precision`` = (# member) / (# names with a prediction) — of the names BioMapper
    answered, how often was the answer a legitimate referent (the hallucination guard).
  - ``ambiguity`` diagnostic = the paper's silent-collapse concern made measurable: mean gold referent
    count vs how many distinct referent structures BioMapper surfaced. A Top-1 mapper surfaces one, so
    a high ``collapse_rate`` is EXPECTED and is reported as context (never gated) — it quantifies the
    ambiguity the mapper does not expose, exactly the danger Pham et al. warn about.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..config import PhamDisambiguationDatasetConfig
from .structure_oracle_scorer import CHOSEN_COL, StructureOracle, _has_prediction, first_block


class UnscorableRunError(RuntimeError):
    """Raised when there is nothing to score (zero ambiguous names) — never report a hollow rate."""


def _referent_blocks(cell: Any) -> set[str]:
    """Distinct InChIKey first-blocks from a ``|``-delimited held-out referent cell."""
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return set()
    blocks: set[str] = set()
    for part in str(cell).split("|"):
        b = first_block(part)
        if b is not None:
            blocks.add(b)
    return blocks


def score_pham_disambiguation(
    mapped_df: pd.DataFrame,
    config: PhamDisambiguationDatasetConfig,
    oracle: StructureOracle,
    vocab: str | None = None,
) -> dict[str, Any]:
    """Referent-membership rate + structural precision + ambiguity-collapse diagnostic.

    Fail-loud on an empty frame (nothing to score). The gold referent set is read from
    ``config.gold_referent_inchikey_column`` (independent source); only ``chosen_kg_id`` is resolved
    through the oracle. A row whose gold referent set is empty is excluded from the denominator
    (coverage-only) rather than scored against nothing.
    """
    total = len(mapped_df)
    if total == 0:
        raise UnscorableRunError(
            f"{config.key}: zero ambiguous names — nothing to score. Refusing to report a hollow "
            f"referent-membership rate for a run that measured nothing."
        )

    scored = 0  # names with a non-empty gold referent set
    n_predicted = 0
    member = 0
    gold_referent_total = 0
    collapsed = 0  # names where BioMapper surfaced fewer distinct referents than the gold set holds
    predicted_referents_total = 0
    per_row: list[dict[str, Any]] = []

    for _, row in mapped_df.iterrows():
        gold_blocks = _referent_blocks(row.get(config.gold_referent_inchikey_column))
        chosen = row.get(CHOSEN_COL)
        has_pred = _has_prediction(chosen)
        if has_pred:
            n_predicted += 1

        predicted_block: str | None = None
        if has_pred:
            predicted_block = oracle.resolved_block(str(chosen).strip())

        # Distinct structural referents BioMapper surfaced for this name. With a Top-1 mapper this is
        # {chosen block} (size 0 or 1); kept as a set so a future candidate-returning mapper measures
        # true ambiguity recall without a scorer change.
        predicted_blocks = {predicted_block} if predicted_block is not None else set()

        is_scored = bool(gold_blocks)
        is_member = bool(is_scored and predicted_block is not None and predicted_block in gold_blocks)
        if is_scored:
            scored += 1
            gold_referent_total += len(gold_blocks)
            predicted_referents_total += len(predicted_blocks)
            if is_member:
                member += 1
            # Collapse: BioMapper exposed fewer distinct referents than genuinely exist for the name.
            if len(predicted_blocks) < len(gold_blocks):
                collapsed += 1

        per_row.append(
            {
                "name": row.get(config.name_column),
                "chosen_kg_id": str(chosen).strip() if has_pred else None,
                "predicted_block": predicted_block,
                "gold_referent_blocks": sorted(gold_blocks),
                "n_gold_referents": len(gold_blocks),
                "n_predicted_referents": len(predicted_blocks),
                "scored": is_scored,
                "member": is_member,
            }
        )

    membership_rate = (member / scored) if scored else None
    structural_precision = (member / n_predicted) if n_predicted else None
    return {
        "vocab": vocab,
        "input_type": config.input_type,
        "comparable_core": {
            "metric": "referent_membership_rate",
            "referent_membership_rate": membership_rate,
            "member": member,
            "scored_denominator": scored,
        },
        "structural_precision": {
            "metric": "structural_precision",
            "precision": structural_precision,
            "member": member,
            "predicted_denominator": n_predicted,
        },
        # Diagnostic (never gated): quantifies the ambiguity BioMapper does not expose (Pham's concern).
        "ambiguity": {
            "mean_gold_referents": (gold_referent_total / scored) if scored else None,
            "mean_predicted_referents": (predicted_referents_total / scored) if scored else None,
            "collapse_rate": (collapsed / scored) if scored else None,
            "collapsed": collapsed,
        },
        "coverage": {
            "n_predicted": n_predicted,
            "total": total,
            "fraction": (n_predicted / total) if total else 0.0,
        },
        "per_row": per_row,
    }
