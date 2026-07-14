"""Provided-ID scorer — CURIE reachability + the fail-loud anti-trivial-100% guard (offline)."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from studies.external_benchmarks.config import PROVIDED_NCBI_GENE2ENSEMBL
from studies.external_benchmarks.scorers.provided_id_scorer import (
    TargetInProvidedError,
    assert_target_held_out,
    score_provided_id,
)


def _mapped_df():
    """Three rows: a hit (gold in equivalence set), a miss (predicted but wrong), a no-prediction."""
    return pd.DataFrame(
        {
            # source id handed to BioMapper (bare Entrez); carried through to the output
            "entrez": ["672", "1", "9999"],
            # BioMapper's resolved node + its equivalence expansion (the provided-ID prediction)
            "chosen_kg_id": ["NCBIGene:672", "NCBIGene:1", None],
            "kg_equivalent_ids": [
                "{'ENSEMBL': ['ENSG00000012048']}",  # reaches the gold Ensembl -> correct
                "{'ENSEMBL': ['ENSG99999999999']}",  # wrong Ensembl -> predicted-but-incorrect
                "{}",  # no expansion -> no prediction
            ],
            # held-out gold TARGET (scorer-only; never provided to BioMapper)
            "gold_ensembl": [
                "ENSEMBL:ENSG00000012048",
                "ENSEMBL:ENSG00000000003",
                "ENSEMBL:ENSG00000141510",
            ],
        }
    )


def test_scorer_correct_iff_gold_target_in_equivalence_set():
    result = score_provided_id(_mapped_df(), PROVIDED_NCBI_GENE2ENSEMBL)
    core = result["comparable_core"]
    # only row 1's held-out Ensembl is present in BioMapper's returned equivalence set
    assert core["correct"] == 1
    assert core["scored_denominator"] == 3  # all three rows carry a gold Ensembl
    assert core["top1_accuracy"] == pytest.approx(1 / 3)
    cov = result["coverage"]
    assert cov["n_predicted"] == 2  # rows 1 and 2 produced a prediction; row 3 did not
    stats = result["curie_stats"]
    assert stats["predicted_and_gold"] == 2
    assert stats["precision"] == pytest.approx(1 / 2)  # correct / (predicted AND gold)
    assert stats["recall"] == pytest.approx(1 / 3)  # correct / scored
    assert result["mode"] == "provided_id"
    assert result["source_namespace"] == "NCBIGene"


def test_scorer_row_records_source_not_name():
    result = score_provided_id(_mapped_df(), PROVIDED_NCBI_GENE2ENSEMBL)
    assert result["per_row"][0]["source"] == "672"
    assert result["per_row"][0]["correct"] is True
    assert result["per_row"][1]["correct"] is False


def test_assert_target_held_out_rejects_target_in_provided():
    # A stand-in whose gold TARGET column IS the provided source column -> fail loud, not 100%.
    bad = SimpleNamespace(
        key="bad-target-in-provided",
        source_id_column="entrez",
        source_namespace="NCBIGene",
        gold_target_columns=(("NCBIGene", "entrez"),),  # target == provided source column
    )
    with pytest.raises(TargetInProvidedError, match="held out|provided_id_columns"):
        assert_target_held_out(bad)


def test_assert_target_held_out_rejects_same_namespace_round_trip():
    # Source namespace == a target namespace (ChEBI -> ChEBI round-trip) self-matches -> fail loud.
    bad = SimpleNamespace(
        key="bad-round-trip",
        source_id_column="chebi",
        source_namespace="CHEBI",
        gold_target_columns=(("CHEBI", "gold_chebi"),),
    )
    with pytest.raises(TargetInProvidedError, match="round-trip|namespace"):
        assert_target_held_out(bad)


def test_scorer_calls_guard_before_scoring():
    bad = SimpleNamespace(
        key="bad",
        arm="gene",
        input_type="provided_id",
        source_id_column="entrez",
        source_namespace="NCBIGene",
        gold_target_columns=(("NCBIGene", "entrez"),),
    )
    with pytest.raises(TargetInProvidedError):
        score_provided_id(_mapped_df(), bad)
