"""CURIE-equality scorer (gene/protein arm) — known input -> expected. Correctness is the crux."""

from __future__ import annotations

import pandas as pd
import pytest

from studies.external_benchmarks.config import HGNC
from studies.external_benchmarks.scorers.curie_scorer import (
    normalize_curie,
    predicted_curies,
    score_curie,
)


def test_normalize_curie_uppercases_prefix_only():
    assert normalize_curie("Ensembl:ENSG00000139618") == "ENSEMBL:ENSG00000139618"
    assert normalize_curie(" UniProtKB:P51587 ") == "UNIPROTKB:P51587"
    assert normalize_curie("") is None
    assert normalize_curie(None) is None
    assert normalize_curie(float("nan")) is None


def test_predicted_curies_from_chosen_and_equivalents():
    row = pd.Series(
        {
            "chosen_kg_id": "NCBIGene:675",
            "kg_equivalent_ids": {"ENSEMBL": ["ENSG00000139618"], "UniProtKB": ["P51587"]},
        }
    )
    preds = predicted_curies(row)
    assert "NCBIGENE:675" in preds
    assert "ENSEMBL:ENSG00000139618" in preds
    assert "UNIPROTKB:P51587" in preds


def test_predicted_curies_parses_stringified_dict():
    # A MAPPED.tsv round-trips kg_equivalent_ids as a repr string; the scorer must parse it.
    row = pd.Series({"chosen_kg_id": "NCBIGene:672", "kg_equivalent_ids": "{'ENSEMBL': ['ENSG00000012048']}"})
    assert "ENSEMBL:ENSG00000012048" in predicted_curies(row)


@pytest.fixture
def mapped_df():
    """4 rows: exact cross-ref hit; equivalent-id hit; wrong cross-ref; no gold (excluded)."""
    return pd.DataFrame(
        {
            HGNC.name_column: ["BRCA1", "BRCA2", "TP53", "NOGOLD"],
            "chosen_kg_id": ["NCBIGene:672", "NCBIGene:675", "NCBIGene:0000", "NCBIGene:9999"],
            "kg_equivalent_ids": [
                {"ENSEMBL": ["ENSG00000012048"], "UniProtKB": ["P38398"]},  # correct via Ensembl
                {"ENSEMBL": ["ENSG00000139618"]},  # correct via Ensembl equiv
                {"ENSEMBL": ["ENSG00000WRONG"]},  # wrong connectivity -> incorrect
                {"ENSEMBL": ["ENSG00000123"]},  # prediction present but no gold -> excluded from acc
            ],
            "gold_ensembl": ["ENSEMBL:ENSG00000012048", "ENSEMBL:ENSG00000139618", "ENSEMBL:ENSG00000141510", ""],
            "gold_entrez": ["NCBIGene:672", "NCBIGene:675", "NCBIGene:7157", ""],
            "gold_uniprot": ["UniProtKB:P38398", "UniProtKB:P51587", "UniProtKB:P04637", ""],
        }
    )


def test_top1_accuracy_and_denominator(mapped_df):
    result = score_curie(mapped_df, HGNC, vocab="ENSEMBL")
    core = result["comparable_core"]
    # scored = 3 rows with gold (NOGOLD excluded); correct = BRCA1 (entrez+ensembl), BRCA2 (ensembl)
    assert core["scored_denominator"] == 3
    assert core["correct"] == 2
    assert core["top1_accuracy"] == pytest.approx(2 / 3)


def test_wrong_crossref_is_incorrect(mapped_df):
    result = score_curie(mapped_df, HGNC)
    tp53 = next(r for r in result["per_row"] if r["query"] == "TP53")
    assert tp53["scored"] is True
    assert tp53["correct"] is False


def test_no_gold_excluded_from_accuracy_counted_in_coverage(mapped_df):
    result = score_curie(mapped_df, HGNC)
    nogold = next(r for r in result["per_row"] if r["query"] == "NOGOLD")
    assert nogold["scored"] is False
    # coverage still counts its prediction
    assert result["coverage"]["n_predicted"] == 4
    assert result["coverage"]["total"] == 4


def test_precision_recall_f1(mapped_df):
    result = score_curie(mapped_df, HGNC)
    stats = result["curie_stats"]
    # both (prediction AND gold) = 3; correct = 2 -> precision 2/3, recall 2/3
    assert stats["predicted_and_gold"] == 3
    assert stats["precision"] == pytest.approx(2 / 3)
    assert stats["recall"] == pytest.approx(2 / 3)
    assert stats["f1"] == pytest.approx(2 / 3)


def test_source_id_cannot_trivially_self_match():
    # The source-namespace query id (an HGNC id) is never in the gold cross-refs, so a prediction
    # echoing it back cannot inflate accuracy — only genuine cross-ref recovery counts.
    df = pd.DataFrame(
        {
            HGNC.name_column: ["BRCA1"],
            "chosen_kg_id": ["HGNC:1100"],  # echoes the source namespace only
            "kg_equivalent_ids": [{"HGNC": ["HGNC:1100"]}],
            "gold_ensembl": ["ENSEMBL:ENSG00000012048"],
            "gold_entrez": ["NCBIGene:672"],
            "gold_uniprot": ["UniProtKB:P38398"],
        }
    )
    result = score_curie(df, HGNC)
    assert result["comparable_core"]["correct"] == 0
    assert result["comparable_core"]["top1_accuracy"] == pytest.approx(0.0)
