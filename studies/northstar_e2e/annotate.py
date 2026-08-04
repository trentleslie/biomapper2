"""Thin wrapper over mapper.map_dataset_to_kg for the annotation stage.

Name-only regime: provided_id_columns=[], annotation_mode="all" — the gold columns
ride along but BioMapper never sees them. Returns the mapped_df (with chosen_kg_id
and the ride-along measurement columns) read back from the mapper's output TSV.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .config import NorthStarConfig


def annotate(input_df: pd.DataFrame, config: NorthStarConfig, mapper: Any, out_dir: Path) -> pd.DataFrame:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_tsv, _stats = mapper.map_dataset_to_kg(
        dataset=input_df,
        entity_type=config.entity_type,
        name_column=config.name_column,
        provided_id_columns=[],
        vocab=config.target_vocab,
        annotation_mode="all",
        output_dir=out_dir,
        output_prefix=f"{config.key}",
    )
    return pd.read_csv(output_tsv, sep="\t", dtype=str).fillna("")
