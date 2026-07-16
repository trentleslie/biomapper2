"""Name-source regime breakout for the structure-oracle scorer (LMSD lipid two-regime split).

The LMSD sample is ~90% lipid SHORTHAND (``ABBREVIATION``, the hard name->structure class) vs the
easier common/systematic names. The scorer must break the strict + charge-normalized Top-1 out per
regime (shorthand vs common/systematic) — additively, alongside the blended overall — when the
caller supplies the adapter's ``query_source`` column, and leave every other arm untouched when it
does not.
"""

from __future__ import annotations

import pandas as pd
import pytest

from studies.external_benchmarks.adapters.lmsd import QUERY_SOURCE_COL
from studies.external_benchmarks.config import LMSD
from studies.external_benchmarks.scorers.structure_oracle_scorer import (
    COMMON_SYSTEMATIC_REGIME,
    SHORTHAND_REGIME,
    name_source_regime,
    score_structure_oracle,
)

# Gold InChIKey first-blocks used across the fixture.
A = "AAAAAAAAAAAAAA"
B = "BBBBBBBBBBBBBB"
C = "CCCCCCCCCCCCCC"
D = "DDDDDDDDDDDDDD"


class _FakeOracle:
    def __init__(self, kg: dict[str, str | None]):
        self._kg = kg

    def kg_block(self, node_id):
        return self._kg.get(node_id)

    def resolved_block(self, node_id):
        return self._kg.get(node_id)


def test_name_source_regime_classifies_shorthand_vs_rest():
    assert name_source_regime("abbreviation") == SHORTHAND_REGIME
    assert name_source_regime("ABBREVIATION") == SHORTHAND_REGIME
    assert name_source_regime("common_name") == COMMON_SYSTEMATIC_REGIME
    assert name_source_regime("systematic_name") == COMMON_SYSTEMATIC_REGIME
    # unexpected/blank tags fold into common/systematic, never dropped
    assert name_source_regime("") == COMMON_SYSTEMATIC_REGIME
    assert name_source_regime("weird") == COMMON_SYSTEMATIC_REGIME


@pytest.fixture
def mapped_df():
    """4 rows: 2 shorthand (1 hit, 1 miss) + 2 common/systematic (both hit)."""
    return pd.DataFrame(
        {
            LMSD.name_column: ["TG 57:6", "PC 16:0/18:1", "Palmitic acid", "1,2-diacyl-sn-glycerol"],
            QUERY_SOURCE_COL: ["abbreviation", "abbreviation", "common_name", "systematic_name"],
            LMSD.gold_inchikey_column: [
                f"{A}-XXXXXXXXXX-N",  # shorthand hit
                f"{B}-XXXXXXXXXX-N",  # shorthand miss
                f"{C}-XXXXXXXXXX-N",  # common hit
                f"{D}-XXXXXXXXXX-N",  # systematic hit
            ],
            LMSD.gold_smiles_column: ["", "", "", ""],  # no SMILES -> CN falls back to strict block
            "chosen_kg_id": ["CHEBI:1", "CHEBI:2", "CHEBI:3", "CHEBI:4"],
        }
    )


@pytest.fixture
def oracle():
    # shorthand: CHEBI:1 matches A (hit), CHEBI:2 -> WRONG (miss). common/systematic both match.
    return _FakeOracle({"CHEBI:1": A, "CHEBI:2": "WRONGWRONGWRON", "CHEBI:3": C, "CHEBI:4": D})


def test_regime_breakout_splits_blended_number(mapped_df, oracle):
    result = score_structure_oracle(mapped_df, LMSD, oracle, vocab="CHEBI", name_source_column=QUERY_SOURCE_COL)
    # blended overall: 3/4 correct
    assert result["comparable_core"]["scored_denominator"] == 4
    assert result["comparable_core"]["correct"] == 3
    assert result["comparable_core"]["top1_accuracy"] == pytest.approx(0.75)

    by = result["by_name_source_regime"]
    assert by is not None
    assert set(by) == {SHORTHAND_REGIME, COMMON_SYSTEMATIC_REGIME}

    # shorthand: 1/2 correct (the hard class), common/systematic: 2/2
    short = by[SHORTHAND_REGIME]["comparable_core"]
    assert short["scored_denominator"] == 2
    assert short["correct"] == 1
    assert short["top1_accuracy"] == pytest.approx(0.5)

    common = by[COMMON_SYSTEMATIC_REGIME]["comparable_core"]
    assert common["scored_denominator"] == 2
    assert common["correct"] == 2
    assert common["top1_accuracy"] == pytest.approx(1.0)

    # per-regime denominators sum to the blended denominator (a row is in exactly one regime)
    assert short["scored_denominator"] + common["scored_denominator"] == 4
    # each regime records n_rows + coverage
    assert by[SHORTHAND_REGIME]["n_rows"] == 2
    assert by[SHORTHAND_REGIME]["coverage"]["n_predicted"] == 2


def test_charge_normalized_per_regime_present(mapped_df, oracle):
    # With a normalizer + neutral_block-capable oracle the per-regime charge-normalized cores are
    # emitted. In THIS synthetic fixture the neutral blocks equal the strict blocks (no SMILES to
    # neutralize), so CN coincides with strict here — but that is a fixture property, NOT a general
    # lipid claim (the live smoke showed charge-norm > strict for real lipids with charged headgroups).
    class _CNOracle(_FakeOracle):
        def neutral_block(self, node_id):
            return self._kg.get(node_id)

    cn_oracle = _CNOracle({"CHEBI:1": A, "CHEBI:2": "WRONGWRONGWRON", "CHEBI:3": C, "CHEBI:4": D})
    result = score_structure_oracle(
        mapped_df,
        LMSD,
        cn_oracle,
        vocab="CHEBI",
        gold_smiles_normalizer=lambda smi: None,  # no SMILES -> CN gold falls back to strict block
        name_source_column=QUERY_SOURCE_COL,
    )
    by = result["by_name_source_regime"]
    short_cn = by[SHORTHAND_REGIME]["comparable_core_charge_normalized"]
    assert short_cn is not None
    assert short_cn["correct"] == by[SHORTHAND_REGIME]["comparable_core"]["correct"] == 1
    assert short_cn["scored_denominator"] == 2


def test_no_name_source_column_leaves_breakout_none(mapped_df, oracle):
    # Absent the column, the split is None and the blended number is unchanged (other arms unaffected).
    result = score_structure_oracle(mapped_df, LMSD, oracle, vocab="CHEBI")
    assert result["by_name_source_regime"] is None
    assert result["comparable_core"]["top1_accuracy"] == pytest.approx(0.75)
