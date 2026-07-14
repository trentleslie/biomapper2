"""Charge/protonation-normalized structure-oracle variant (Hajjar learning #2)."""

from __future__ import annotations

import pandas as pd
import pytest

from studies.external_benchmarks.config import HAJJAR
from studies.external_benchmarks.scorers.structure_oracle_scorer import (
    neutralize_first_block,
    score_structure_oracle,
)


def test_neutralize_first_block_collapses_charge_state():
    # A carboxylate and its acid neutralize to one connectivity skeleton.
    acetate = neutralize_first_block("CC(=O)[O-]")
    acid = neutralize_first_block("CC(=O)O")
    assert acetate is not None
    assert acetate == acid
    assert neutralize_first_block("") is None
    assert neutralize_first_block(None) is None
    assert neutralize_first_block("not a smiles $$$") is None


class _FakeCNOracle:
    """Fake oracle exposing strict (kg/resolved) AND neutral blocks per node id."""

    def __init__(self, strict: dict[str, str | None], neutral: dict[str, str | None]):
        self._strict = strict
        self._neutral = neutral

    def kg_block(self, node_id):
        return self._strict.get(node_id)

    def resolved_block(self, node_id):
        return self._strict.get(node_id)

    def neutral_block(self, node_id):
        return self._neutral.get(node_id)


@pytest.fixture
def mapped_df():
    # One row where strict blocks DIFFER (gold AAA... vs pred BBB...) but the neutralized blocks
    # MATCH (both NNN...). The strict oracle must miss it; the charge-normalized oracle must catch it.
    return pd.DataFrame(
        {
            HAJJAR.name_column: ["citrate-ish"],
            HAJJAR.gold_inchikey_column: ["AAAAAAAAAAAAAA-GASJEMHNSA-N"],  # strict gold block AAA...
            HAJJAR.gold_smiles_column: ["OC(=O)CC(O)(CC(=O)[O-])C(=O)[O-]"],  # charged gold SMILES
            "chosen_kg_id": ["CHEBI:30769"],
        }
    )


def test_strict_misses_but_charge_normalized_catches(mapped_df):
    oracle = _FakeCNOracle(
        strict={"CHEBI:30769": "BBBBBBBBBBBBBB"},  # strict pred != strict gold AAA...
        neutral={"CHEBI:30769": "NNNNNNNNNNNNNN"},  # neutral pred == neutral gold (below)
    )
    # Inject a gold normalizer that returns the matching neutral block for the gold SMILES.
    result = score_structure_oracle(
        mapped_df, HAJJAR, oracle, vocab="CHEBI", gold_smiles_normalizer=lambda smi: "NNNNNNNNNNNNNN"
    )
    strict = result["comparable_core"]
    cn = result["comparable_core_charge_normalized"]
    # strict: scored 1, correct 0
    assert strict["scored_denominator"] == 1
    assert strict["correct"] == 0
    assert strict["top1_accuracy"] == pytest.approx(0.0)
    # charge-normalized: scored 1, correct 1
    assert cn is not None
    assert cn["scored_denominator"] == 1
    assert cn["correct"] == 1
    assert cn["top1_accuracy"] == pytest.approx(1.0)
    # per-row flag surfaced
    assert result["per_row"][0]["charge_normalized_correct"] is True


def test_charge_normalized_core_is_none_without_capability(mapped_df):
    # No normalizer passed -> strict-only, CN core is None. Existing behavior is preserved.
    oracle = _FakeCNOracle(strict={"CHEBI:30769": "BBBBBBBBBBBBBB"}, neutral={})
    result = score_structure_oracle(mapped_df, HAJJAR, oracle, vocab="CHEBI")
    assert result["comparable_core_charge_normalized"] is None
    assert result["comparable_core"]["top1_accuracy"] == pytest.approx(0.0)


def test_charge_normalized_falls_back_to_strict_gold_without_smiles():
    # A row with a gold InChIKey but no gold SMILES: gold can't be neutralized (can't un-hash),
    # so the CN comparison uses the strict gold block, and a matching neutral prediction counts.
    df = pd.DataFrame(
        {
            HAJJAR.name_column: ["x"],
            HAJJAR.gold_inchikey_column: ["WQZGKKKJIJFFOK-GASJEMHNSA-N"],
            HAJJAR.gold_smiles_column: [""],  # no SMILES
            "chosen_kg_id": ["CHEBI:1"],
        }
    )
    oracle = _FakeCNOracle(strict={"CHEBI:1": "ZZZZZZZZZZZZZZ"}, neutral={"CHEBI:1": "WQZGKKKJIJFFOK"})
    result = score_structure_oracle(df, HAJJAR, oracle, vocab="CHEBI", gold_smiles_normalizer=lambda smi: None)
    cn = result["comparable_core_charge_normalized"]
    assert cn is not None
    assert cn["correct"] == 1  # neutral pred matched the strict gold block fallback
