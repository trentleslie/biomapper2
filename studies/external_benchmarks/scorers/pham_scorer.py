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

Reporting (approved design): the FULL reconstructed population is scored (every name with >= 1
structural referent — NOT restricted to ambiguous names), and the AMBIGUOUS SUBSET (names with
>= ``config.ambiguous_min_referents`` distinct referent structures) is broken out separately as the
highlighted hard-case result. So two membership numbers are reported over two nested denominators,
plus precision and an ambiguity diagnostic:
  - ``comparable_core`` = FULL-population referent-membership rate = (# scored names whose chosen block
    is in the referent set) / (# scored names). A name with no prediction is a miss.
  - ``ambiguous_subset`` = the SAME membership rate restricted to genuinely ambiguous names
    (>= ``ambiguous_min_referents`` referents) — the paper's hard case, reported as the headline.
  - ``structural_precision`` = (# member) / (# names with a prediction AND a non-empty referent set)
    — of the names BioMapper answered, how often was the answer a legitimate referent (the
    hallucination guard). Part-1 fix (Greptile P2): a coverage-only row (empty referent set) is
    excluded from the scored denominator, so it must NOT dilute precision either — a prediction counts
    toward the precision denominator ONLY when the row has a non-empty ``gold_blocks``.
  - ``ambiguity`` diagnostic = the paper's silent-collapse concern made measurable, computed over the
    ambiguous subset: mean gold referent count vs how many distinct referent structures BioMapper
    surfaced. A Top-1 mapper surfaces one, so a high ``collapse_rate`` is EXPECTED and is reported as
    context (never gated) — it quantifies the ambiguity the mapper does not expose, exactly the danger
    Pham et al. warn about.

LIPID vs NON-LIPID stratification (approved 2026-07-16): the reconstructed ambiguous population is a
lipid-isomer-nomenclature majority, which overlaps the LMSD lipid arm and misses the abbreviation /
cross-class ambiguity Pham 2019 is about (``tmp`` -> thymidine-MP / thiamine-MP; ``suc`` -> succinate /
sucrose). Each name carries a ``stratum`` label (see the adapter's lipid classifier); the same full-set
metrics above are additionally computed per stratum in ``result["by_stratum"]``. The reported HEADLINE
is ``by_stratum["non_lipid"]["ambiguous_subset"]`` (Pham's distinct contribution); the lipid stratum is
reported separately (it overlaps LMSD). The top-level keys remain the FULL-population numbers. A row with
no stratum label (legacy frame) is bucketed under ``UNSTRATIFIED`` so scoring never fails on it.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..config import PhamDisambiguationDatasetConfig
from .structure_oracle_scorer import CHOSEN_COL, StructureOracle, _has_prediction, first_block

# Bucket for rows carrying no stratum label (e.g. a legacy mapped frame without the ``stratum`` column).
UNSTRATIFIED = "unstratified"


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


def _aggregate(records: list[dict[str, Any]], ambiguous_min: int, vocab: str | None, input_type: str) -> dict[str, Any]:
    """Aggregate pre-resolved per-row records into the membership / precision / ambiguity report.

    Records carry the already-oracle-resolved ``predicted_block`` (so aggregating repeatedly per stratum
    re-runs no oracle calls) plus the row's ``gold_blocks`` and ``has_pred``. Returns the same structure
    the top-level scorer emits, over whatever subset of records is passed in.
    """
    scored = member = n_predicted = n_predicted_scored = 0
    amb_scored = amb_member = amb_gold_referent_total = amb_predicted_referents_total = amb_collapsed = 0
    per_row: list[dict[str, Any]] = []

    for rec in records:
        gold_blocks: set[str] = rec["gold_blocks"]
        has_pred: bool = rec["has_pred"]
        predicted_block: str | None = rec["predicted_block"]
        if has_pred:
            n_predicted += 1
        predicted_blocks = {predicted_block} if predicted_block is not None else set()

        is_scored = bool(gold_blocks)
        is_ambiguous = bool(is_scored and len(gold_blocks) >= ambiguous_min)
        is_member = bool(is_scored and predicted_block is not None and predicted_block in gold_blocks)
        if is_scored:
            scored += 1
            if has_pred:
                n_predicted_scored += 1
            if is_member:
                member += 1
            if is_ambiguous:
                amb_scored += 1
                amb_gold_referent_total += len(gold_blocks)
                amb_predicted_referents_total += len(predicted_blocks)
                if is_member:
                    amb_member += 1
                if len(predicted_blocks) < len(gold_blocks):
                    amb_collapsed += 1

        per_row.append(
            {
                "name": rec["name"],
                "stratum": rec["stratum"],
                "chosen_kg_id": rec["chosen_kg_id"],
                "predicted_block": predicted_block,
                "gold_referent_blocks": sorted(gold_blocks),
                "n_gold_referents": len(gold_blocks),
                "n_predicted_referents": len(predicted_blocks),
                "scored": is_scored,
                "is_ambiguous": is_ambiguous,
                "member": is_member,
            }
        )

    total = len(records)
    membership_rate = (member / scored) if scored else None
    amb_membership_rate = (amb_member / amb_scored) if amb_scored else None
    structural_precision = (member / n_predicted_scored) if n_predicted_scored else None
    return {
        "vocab": vocab,
        "input_type": input_type,
        "comparable_core": {
            "metric": "referent_membership_rate",
            "referent_membership_rate": membership_rate,
            "member": member,
            "scored_denominator": scored,
        },
        "ambiguous_subset": {
            "metric": "referent_membership_rate",
            "referent_membership_rate": amb_membership_rate,
            "member": amb_member,
            "scored_denominator": amb_scored,
            "ambiguous_min_referents": ambiguous_min,
        },
        "structural_precision": {
            "metric": "structural_precision",
            "precision": structural_precision,
            "member": member,
            "predicted_denominator": n_predicted_scored,
        },
        "ambiguity": {
            "mean_gold_referents": (amb_gold_referent_total / amb_scored) if amb_scored else None,
            "mean_predicted_referents": (amb_predicted_referents_total / amb_scored) if amb_scored else None,
            "collapse_rate": (amb_collapsed / amb_scored) if amb_scored else None,
            "collapsed": amb_collapsed,
            "ambiguous_scored": amb_scored,
        },
        "coverage": {
            "n_predicted": n_predicted,
            "total": total,
            "fraction": (n_predicted / total) if total else 0.0,
        },
        "per_row": per_row,
    }


def score_pham_disambiguation(
    mapped_df: pd.DataFrame,
    config: PhamDisambiguationDatasetConfig,
    oracle: StructureOracle,
    vocab: str | None = None,
) -> dict[str, Any]:
    """Full-population + ambiguous-subset referent-membership + structural precision + ambiguity diag.

    Fail-loud on an empty frame (nothing to score). The gold referent set is read from
    ``config.gold_referent_inchikey_column`` (independent source); only ``chosen_kg_id`` is resolved
    through the oracle. A row whose gold referent set is empty is excluded from BOTH the scored
    denominator AND the precision denominator (coverage-only) rather than scored against nothing.

    The full population is every scored name; the ambiguous subset is the scored names with
    >= ``config.ambiguous_min_referents`` distinct referent structures (default 2).
    """
    total = len(mapped_df)
    if total == 0:
        raise UnscorableRunError(
            f"{config.key}: zero names — nothing to score. Refusing to report a hollow "
            f"referent-membership rate for a run that measured nothing."
        )

    ambiguous_min = int(getattr(config, "ambiguous_min_referents", 2))
    stratum_col = getattr(config, "stratum_column", "stratum")

    # First pass: resolve each prediction through the oracle ONCE and cache per-row records, so the
    # full-population and per-stratum aggregations re-run no oracle calls.
    records: list[dict[str, Any]] = []
    for _, row in mapped_df.iterrows():
        gold_blocks = _referent_blocks(row.get(config.gold_referent_inchikey_column))
        chosen = row.get(CHOSEN_COL)
        has_pred = _has_prediction(chosen)
        predicted_block = oracle.resolved_block(str(chosen).strip()) if has_pred else None
        stratum_val = row.get(stratum_col)
        stratum = str(stratum_val).strip() if stratum_val not in (None, "") and not pd.isna(stratum_val) else UNSTRATIFIED
        records.append(
            {
                "name": row.get(config.name_column),
                "stratum": stratum,
                "chosen_kg_id": str(chosen).strip() if has_pred else None,
                "gold_blocks": gold_blocks,
                "has_pred": has_pred,
                "predicted_block": predicted_block,
            }
        )

    # FULL population (every scored name) — the top-level keys, backward-compatible.
    result = _aggregate(records, ambiguous_min, vocab, config.input_type)

    # LIPID vs NON-LIPID strata broken out separately; the NON-lipid ambiguous subset is the headline
    # (Pham's distinct contribution — the abbreviation / cross-class ambiguity), the lipid stratum
    # overlaps the LMSD arm and is reported for context.
    by_stratum: dict[str, Any] = {}
    for stratum in sorted({rec["stratum"] for rec in records}):
        subset = [rec for rec in records if rec["stratum"] == stratum]
        by_stratum[stratum] = _aggregate(subset, ambiguous_min, vocab, config.input_type)
    result["by_stratum"] = by_stratum
    # Convenience pointer to the headline (may be absent if the run had no non-lipid rows).
    result["headline"] = {
        "stratum": "non_lipid",
        "ambiguous_subset": by_stratum.get("non_lipid", {}).get("ambiguous_subset"),
        "structural_precision": by_stratum.get("non_lipid", {}).get("structural_precision"),
    }
    return result
