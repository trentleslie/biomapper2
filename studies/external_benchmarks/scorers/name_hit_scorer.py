"""Name-hit-rate scorer (MetaboliteAnnotator regime) — the same-set NAME-input head-to-head.

The comparable core is a per-input NAME-HIT-RATE: the fraction of input names for which BioMapper
produced a target-vocab identifier. This is MetaboliteAnnotator's own metric, computed identically so
BioMapper's number lands directly beside the published 93.2% (pos) / 93.5% (neg) and the
MetaboAnalyst 6.0 / metaboliteIDmapping baselines. It is a coverage-shaped number (labeled
``input_type=name``) and is NEVER merged with the correctness qualifiers below.

Discipline (Hajjar/NECS learnings):
  - ONE number per dataset — one ``name_hit_rate`` per mode config (per-accession is traceability).
  - ANTI-TRIVIAL: the hit is adjudicated on BioMapper's OUTPUT (``chosen_kg_id``), never on the
    held-out gold column. A name with a gold id but no produced id is a MISS. (The runner's
    ``assigned>0`` guard separately enforces the name path so the gold can't leak in as a provided id.)
  - FAIL-LOUD on unscorable: zero input names raises rather than reporting a hollow ``None``.
  - ID-CONCORDANCE qualifier: of the names we hit that also carry a gold ``database_identifier``, how
    many hit the RIGHT id — reusing ``curie_scorer.split_gold_curies`` for the ``|``-multi gold cell.
  - CHARGE-NORMALIZED STRUCTURE qualifier (optional, live): when an oracle exposing ``neutral_block``
    is supplied, a protonation-neutralized structure concordance over the hit-and-gold-SMILES subset —
    the dominant-miss variant, reusing ``structure_oracle_scorer.neutralize_first_block``.
"""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd

from ..config import NameHitDatasetConfig
from .curie_scorer import predicted_curies, split_gold_curies
from .structure_oracle_scorer import CHOSEN_COL, _has_prediction, neutralize_first_block

# Passthrough accession column produced by the adapter (kept optional so a bare df still scores).
SOURCE_ACCESSION_COL = "source_accession"


class UnscorableRunError(RuntimeError):
    """Raised when there is nothing to score (zero input names) — never report a hollow rate."""


class NeutralBlockOracle(Protocol):
    """Minimal live-oracle surface for the charge-normalized structure qualifier."""

    def neutral_block(self, node_id: str) -> str | None: ...


def score_name_hit(
    mapped_df: pd.DataFrame,
    config: NameHitDatasetConfig,
    vocab: str | None = None,
    *,
    oracle: NeutralBlockOracle | None = None,
) -> dict[str, Any]:
    """Name-hit-rate + ID-concordance + optional charge-normalized structure concordance."""
    total = len(mapped_df)
    if total == 0:
        raise UnscorableRunError(
            f"{config.key}: zero input names — nothing to score. Refusing to report a hollow "
            f"name-hit-rate for a run that measured nothing."
        )

    cn_available = oracle is not None and hasattr(oracle, "neutral_block")

    matched = 0
    id_scored = 0  # names that both hit and carry a gold id (concordance denominator)
    id_concordant = 0
    cn_scored = 0
    cn_concordant = 0
    per_accession: dict[str, dict[str, int]] = {}
    per_row: list[dict[str, Any]] = []

    for _, row in mapped_df.iterrows():
        chosen = row.get(CHOSEN_COL)
        has_hit = _has_prediction(chosen)  # the hit is from the PREDICTION, not the gold
        if has_hit:
            matched += 1

        gold_ids = split_gold_curies(row.get(config.gold_id_column))
        row_concordant: bool | None = None
        if has_hit and gold_ids:
            id_scored += 1
            row_concordant = bool(predicted_curies(row) & gold_ids)
            if row_concordant:
                id_concordant += 1

        cn_row: bool | None = None
        if cn_available and has_hit and config.gold_smiles_column:
            gold_smiles = row.get(config.gold_smiles_column)
            gold_cn = neutralize_first_block(gold_smiles)
            if gold_cn is not None:
                pred_cn = oracle.neutral_block(str(chosen).strip())  # type: ignore[union-attr]
                cn_scored += 1
                cn_row = bool(pred_cn is not None and pred_cn == gold_cn)
                if cn_row:
                    cn_concordant += 1

        acc = str(row.get(SOURCE_ACCESSION_COL, "") or "")
        if acc:
            bucket = per_accession.setdefault(acc, {"matched": 0, "total": 0})
            bucket["total"] += 1
            if has_hit:
                bucket["matched"] += 1

        per_row.append(
            {
                "name": row.get(config.name_column),
                "chosen_kg_id": str(chosen).strip() if has_hit else None,
                "hit": has_hit,
                "id_concordant": row_concordant,
            }
        )

    structure_cn: dict[str, Any] | None = None
    if cn_available:
        structure_cn = {
            "metric": "structure_concordance_charge_normalized",
            "scored": cn_scored,
            "concordant": cn_concordant,
            "concordance_rate": (cn_concordant / cn_scored) if cn_scored else None,
        }

    return {
        "vocab": vocab,
        "mode": config.mode,
        "input_type": config.input_type,
        "comparable_core": {
            "metric": "name_hit_rate",
            "name_hit_rate": matched / total,
            "matched": matched,
            "total": total,
        },
        "id_concordance": {
            "metric": "id_concordance_rate",
            "scored": id_scored,
            "concordant": id_concordant,
            "concordance_rate": (id_concordant / id_scored) if id_scored else None,
        },
        "structure_concordance_charge_normalized": structure_cn,
        "per_accession": per_accession,
        "per_row": per_row,
    }
