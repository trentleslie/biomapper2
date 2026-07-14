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

from collections.abc import Callable
from typing import Any, Protocol

import pandas as pd

from ..config import DatasetConfig

CHOSEN_COL = "chosen_kg_id"


class StructureOracle(Protocol):
    """KG-first structure resolution for a predicted node id.

    ``kg_block`` returns the InChIKey first-block from the KG record alone (None if the KG
    carries no structure). ``resolved_block`` additionally consults the name fallback
    (MW -> PubChem). The gap between the two is the fallback-segregation signal.

    ``neutral_block`` (optional; probed via ``hasattr``) returns the *charge/protonation-
    normalized* InChIKey first-block of the prediction — the connectivity after neutralizing
    the structure. It powers the charge-normalized accuracy variant (Hajjar's dominant miss was
    protonation state).
    """

    def kg_block(self, node_id: str) -> str | None: ...
    def resolved_block(self, node_id: str) -> str | None: ...


def neutralize_first_block(smiles: Any) -> str | None:
    """Charge/protonation-normalized InChIKey first-block from a SMILES, or None.

    Neutralizes the molecule (RDKit ``Uncharger``) before hashing so charged/protonated forms
    (e.g. a carboxylate vs its acid, a zwitterion vs the neutral species, a source table using a
    fixed-H convention) collapse to one connectivity skeleton. Standard InChI already routes
    most protonation into the second block, so this only moves the residual cases where the
    recorded first block itself differs by charge state — but those were the dominant Hajjar
    miss, so the variant is reported alongside the strict number.
    """
    if smiles is None or (isinstance(smiles, float) and pd.isna(smiles)):
        return None
    s = str(smiles).strip()
    if not s or s.lower() == "nan":
        return None
    from rdkit import Chem, RDLogger
    from rdkit.Chem.MolStandardize import rdMolStandardize

    RDLogger.DisableLog("rdApp.*")  # type: ignore[attr-defined]
    mol = Chem.MolFromSmiles(s)
    if mol is None:
        return None
    mol = rdMolStandardize.Uncharger().uncharge(mol)
    key = Chem.MolToInchiKey(mol)
    return first_block(key)


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
    *,
    gold_smiles_normalizer: Callable[[Any], str | None] | None = None,
) -> dict[str, Any]:
    """Compute Top-1 accuracy (structure-oracle) + coverage + the fallback bucket.

    When a charge-normalization capability is available — a ``gold_smiles_normalizer`` for the
    gold side AND an ``oracle.neutral_block`` for the prediction side — a SECOND accuracy is
    reported under ``comparable_core_charge_normalized``: the same Top-1 accuracy but with both
    blocks neutralized for charge/protonation state. Both numbers are reported; neither replaces
    the other (protonation was the dominant Hajjar miss). When the capability is absent the
    charge-normalized core is ``None`` with a recorded reason.
    """
    smiles_col = config.gold_smiles_column
    cn_available = gold_smiles_normalizer is not None and hasattr(oracle, "neutral_block")

    total = len(mapped_df)
    n_predicted = 0
    scored = 0  # accuracy denominator: rows with gold structure
    correct = 0
    fallback_rows: list[str] = []
    # Charge-normalized tallies (only meaningful when cn_available).
    cn_scored = 0
    cn_correct = 0
    per_row: list[dict[str, Any]] = []

    for _, row in mapped_df.iterrows():
        gold_block = first_block(row.get(config.gold_inchikey_column))
        chosen = row.get(CHOSEN_COL)
        has_pred = _has_prediction(chosen)
        if has_pred:
            n_predicted += 1

        predicted_block: str | None = None
        needed_fallback = False
        chosen_id: str | None = None
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

        cn_correct_row: bool | None = None
        # Gate the charge-normalized tally on the SAME population as strict (``gold_block is not
        # None``), so both accuracies share one denominator and stay comparable. A row with a
        # parseable gold SMILES but no gold InChIKey must NOT inflate the normalized denominator
        # (coverage-only rule): it is not in the strict scored set, so it is not in the cn set.
        if cn_available and gold_block is not None:
            assert gold_smiles_normalizer is not None
            gold_smiles = row.get(smiles_col) if smiles_col else None
            gold_cn = gold_smiles_normalizer(gold_smiles)
            # Neutralize the gold connectivity; fall back to the strict gold block when the
            # source ships no SMILES to neutralize (can't neutralize a hash). Because gold_block
            # is not None here, gold_cn_block is always defined.
            gold_cn_block = gold_cn if gold_cn is not None else gold_block
            pred_cn_block = oracle.neutral_block(chosen_id) if (has_pred and chosen_id is not None) else None  # type: ignore[attr-defined]
            cn_scored += 1
            cn_correct_row = bool(pred_cn_block is not None and pred_cn_block == gold_cn_block)
            if cn_correct_row:
                cn_correct += 1

        per_row.append(
            {
                "name": row.get(config.name_column),
                "chosen_kg_id": None if not has_pred else chosen_id,
                "gold_block": gold_block,
                "predicted_block": predicted_block,
                "scored": is_scored,
                "correct": is_correct,
                "needed_fallback": needed_fallback,
                "charge_normalized_correct": cn_correct_row,
            }
        )

    accuracy = (correct / scored) if scored else None
    if cn_available:
        cn_core: dict[str, Any] | None = {
            "metric": "top1_accuracy_charge_normalized",
            "top1_accuracy": (cn_correct / cn_scored) if cn_scored else None,
            "correct": cn_correct,
            "scored_denominator": cn_scored,
        }
    else:
        cn_core = None
    return {
        "vocab": vocab,
        "input_type": config.input_type,
        "comparable_core": {
            "metric": "top1_accuracy",
            "top1_accuracy": accuracy,
            "correct": correct,
            "scored_denominator": scored,
        },
        "comparable_core_charge_normalized": cn_core,
        "coverage": {
            "n_predicted": n_predicted,
            "total": total,
            "fraction": (n_predicted / total) if total else 0.0,
        },
        "fallback_bucket": {"count": len(fallback_rows), "rows": fallback_rows},
        "per_row": per_row,
    }
