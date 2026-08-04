"""Ablation arms for the slice (spec §4 decomposition).

  arm0_clean   : canonical names -> mapper -> ground -> interpret  (ceiling)
  arm1_product : messy -> mapper -> ground -> interpret            (the real metric)
  arm3_oracle  : messy -> hidden mapping G -> gold ChEBI -> ground -> interpret
                 (separates resolution error from information loss)

Arm 2 (raw-messy no-BioMapper baseline) is added once 0/1/3 work — deferred here
per the spec's slice ordering. The shuffled-annotation control is Task 10.
Every dependency (mapper, kestrel, llm_fn) is injected so arms run offline in tests.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .annotate import annotate
from .config import NorthStarConfig
from .grounding import ground_pathways
from .interpret import interpret
from .scorers.pathway_overlap import score_pathways


@dataclass(frozen=True)
class ArmResult:
    arm: str
    interpretation: Any
    grounded: Any
    score: dict


def _oracle_mapped_df(messy_result, config: NorthStarConfig) -> pd.DataFrame:
    """Build a mapped_df whose chosen_kg_id is the held-out gold ChEBI (G applied)."""
    df = messy_result.messy_df.copy()
    df["chosen_kg_id"] = df[config.gold_chebi_column]
    return df


def _interpret_and_score(mapped_df, config, kestrel, membership, llm_fn) -> tuple[Any, Any, dict]:
    grounded = ground_pathways(mapped_df, "chosen_kg_id", kestrel, membership)
    interp = interpret(
        grounded,
        mapped_df,
        config.question,
        llm_fn,
        name_col=config.name_column,
        dir_col=config.direction_column,
    )
    score = score_pathways(interp)
    return interp, grounded, score


def run_arm(
    arm: str,
    *,
    clean_df: pd.DataFrame,
    messy_result,
    config: NorthStarConfig,
    mapper: Any,
    kestrel,
    membership: dict,
    llm_fn: Callable[[str], dict],
) -> ArmResult:
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        if arm == "arm0_clean":
            mapped_df = annotate(clean_df, config, mapper, out_dir)
        elif arm == "arm1_product":
            mapped_df = annotate(messy_result.messy_df, config, mapper, out_dir)
        elif arm == "arm3_oracle":
            mapped_df = _oracle_mapped_df(messy_result, config)
        else:
            raise ValueError(f"unknown arm {arm!r}")
    interp, grounded, score = _interpret_and_score(mapped_df, config, kestrel, membership, llm_fn)
    return ArmResult(arm=arm, interpretation=interp, grounded=grounded, score=score)
