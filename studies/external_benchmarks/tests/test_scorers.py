"""Unit 3 — scorers (offline; fake oracle injected). Scoring correctness is the crux."""

from __future__ import annotations

import pandas as pd
import pytest

from studies.external_benchmarks.adapters.hajjar import HAS_STRUCTURE_COL
from studies.external_benchmarks.config import HAJJAR
from studies.external_benchmarks.scorers.paper_metric import score_paper_metric
from studies.external_benchmarks.scorers.structure_oracle_scorer import (
    first_block,
    score_structure_oracle,
)

# Gold InChIKey first-blocks used across the fixture.
GLU = "WQZGKKKJIJFFOK"
ALA = "QNAYBMKLOCPYGJ"
CAF = "RYYVLZVUVIJVGH"
ETH = "LFQSCWFLJHTTHZ"


@pytest.fixture
def mapped_df():
    """5 rows exercising every scoring case (see per-row comments)."""
    return pd.DataFrame(
        {
            HAJJAR.name_column: ["D-Glucose", "L-Alanine", "Caffeine", "Mystery lipid", "Ethanol"],
            HAJJAR.gold_chebi_column: ["CHEBI:4167", "CHEBI:16977", "CHEBI:27732", "CHEBI:99999", "CHEBI:16236"],
            HAJJAR.gold_inchikey_column: [
                f"{GLU}-GASJEMHNSA-N",  # 1 correct (same id, same block)
                f"{ALA}-REOHCLBHSA-N",  # 2 correct (diff id, same block)
                f"{CAF}-UHFFFAOYSA-N",  # 3 incorrect (diff connectivity)
                "",  # 4 no gold structure -> excluded from denom, counted in coverage
                f"{ETH}-UHFFFAOYSA-N",  # 5 correct via fallback -> flagged
            ],
            HAS_STRUCTURE_COL: [True, True, True, False, True],
            "chosen_kg_id": ["CHEBI:4167", "CHEBI:DIFF", "CHEBI:WRONG", "CHEBI:12345", "CHEBI:16236"],
        }
    )


@pytest.fixture
def oracle(fake_oracle_factory):
    # kg_block: KG-record structure (None means KG has no structure -> forces fallback)
    kg = {
        "CHEBI:4167": GLU,
        "CHEBI:DIFF": ALA,  # different id, gold-matching connectivity
        "CHEBI:WRONG": "AAAAAAAAAAAAAA",  # different connectivity
        "CHEBI:12345": "BBBBBBBBBBBBBB",  # prediction for the no-gold-structure row
        "CHEBI:16236": None,  # KG lacks structure -> fallback path
    }
    fallback = {"CHEBI:16236": ETH}  # name fallback recovers ethanol's block
    return fake_oracle_factory(kg, fallback)


def test_first_block():
    assert first_block("WQZGKKKJIJFFOK-GASJEMHNSA-N") == "WQZGKKKJIJFFOK"
    assert first_block("") is None
    assert first_block(None) is None
    assert first_block(float("nan")) is None


def test_top1_accuracy_and_coverage(mapped_df, oracle):
    result = score_structure_oracle(mapped_df, HAJJAR, oracle, vocab="CHEBI")
    core = result["comparable_core"]
    # scored denominator = 4 (rows with gold structure); correct = 3 (glucose, alanine, ethanol)
    assert core["scored_denominator"] == 4
    assert core["correct"] == 3
    assert core["top1_accuracy"] == pytest.approx(0.75)
    # coverage counts all predictions incl. the no-gold-structure row
    assert result["coverage"]["n_predicted"] == 5
    assert result["coverage"]["total"] == 5
    assert result["coverage"]["fraction"] == pytest.approx(1.0)


def test_different_id_same_block_is_correct(mapped_df, oracle):
    result = score_structure_oracle(mapped_df, HAJJAR, oracle, vocab="CHEBI")
    alanine = next(r for r in result["per_row"] if r["name"] == "L-Alanine")
    assert alanine["chosen_kg_id"] == "CHEBI:DIFF"  # != gold CHEBI:16977
    assert alanine["correct"] is True


def test_different_connectivity_is_incorrect(mapped_df, oracle):
    result = score_structure_oracle(mapped_df, HAJJAR, oracle, vocab="CHEBI")
    caffeine = next(r for r in result["per_row"] if r["name"] == "Caffeine")
    assert caffeine["scored"] is True
    assert caffeine["correct"] is False


def test_no_gold_inchikey_excluded_from_denominator(mapped_df, oracle):
    result = score_structure_oracle(mapped_df, HAJJAR, oracle, vocab="CHEBI")
    mystery = next(r for r in result["per_row"] if r["name"] == "Mystery lipid")
    assert mystery["scored"] is False  # excluded from accuracy
    # but its prediction still counts toward coverage
    assert result["coverage"]["n_predicted"] == 5


def test_fallback_rows_flagged_into_bucket(mapped_df, oracle):
    result = score_structure_oracle(mapped_df, HAJJAR, oracle, vocab="CHEBI")
    bucket = result["fallback_bucket"]
    assert bucket["count"] == 1
    assert "CHEBI:16236" in bucket["rows"]  # ethanol, recovered via name fallback
    ethanol = next(r for r in result["per_row"] if r["name"] == "Ethanol")
    assert ethanol["needed_fallback"] is True
    assert ethanol["correct"] is True


def test_paper_metric_match_rate(mapped_df):
    result = score_paper_metric(mapped_df, HAJJAR, vocab="CHEBI")
    assert result["metric"] == "match_rate"
    assert result["input_type"] == "name"
    assert result["matched"] == 5
    assert result["total"] == 5
    assert result["match_rate"] == pytest.approx(1.0)


def test_paper_metric_counts_only_predicted():
    df = pd.DataFrame({HAJJAR.name_column: ["a", "b", "c"], "chosen_kg_id": ["CHEBI:1", None, "nan"]})
    result = score_paper_metric(df, HAJJAR)
    assert result["matched"] == 1
    assert result["total"] == 3
