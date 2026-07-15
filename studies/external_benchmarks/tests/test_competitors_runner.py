"""Competitor runner: scorable-df shape, protocol deltas, identical-scorer reuse."""

from __future__ import annotations

import pandas as pd
import pytest

from studies.external_benchmarks.competitors.base import CompetitorClient
from studies.external_benchmarks.competitors.runner import (
    UnknownBackboneSourceError,
    build_competitor_mapped_df,
    run_competitor,
    score_competitor_run,
    source_namespace_for,
)
from studies.external_benchmarks.config import HGNC


class FakeClient(CompetitorClient):
    """A transport-free client: canned per-query predictions + declared target support."""

    def __init__(self, name, predictions, supported):
        super().__init__(transport=None)  # type: ignore[arg-type]  # map_ids overridden; no HTTP
        self.name = name
        self._preds = predictions
        self._supported = set(supported)

    def source_code(self, source_ns):
        return source_ns

    def target_code(self, target_ns):
        return target_ns if target_ns in self._supported else None

    def map_batch(self, ids, source_ns, target_ns):  # pragma: no cover - not used (map_ids overridden)
        raise NotImplementedError

    def map_ids(self, queries, source_ns, target_namespaces):
        return {q: set(self._preds.get(q, set())) for q in queries}


def _hgnc_input_df():
    return pd.DataFrame(
        {
            "symbol": ["BRCA1", "TP53", "NOGOLD"],
            "gold_ensembl": ["ENSEMBL:ENSG00000012048", "ENSEMBL:ENSG00000141510", ""],
            "gold_entrez": ["NCBIGene:672", "NCBIGene:7157", ""],
            "gold_uniprot": ["UniProtKB:P38398", "UniProtKB:P04637", ""],
        }
    )


def test_source_namespace_for_known_and_unknown():
    assert source_namespace_for(HGNC) == "SYMBOL"

    class Bogus:
        key = "not-a-backbone"

    with pytest.raises(UnknownBackboneSourceError):
        source_namespace_for(Bogus())  # type: ignore[arg-type]


def test_build_mapped_df_has_scorer_columns_and_preserves_gold():
    df = _hgnc_input_df()
    preds = {"BRCA1": {"ENSEMBL:ENSG00000012048"}}
    out = build_competitor_mapped_df(df, HGNC, preds)
    assert list(out["chosen_kg_id"]) == ["", "", ""]
    assert out.loc[0, "kg_equivalent_ids"] == {"ENSEMBL": ["ENSG00000012048"]}
    # gold columns preserved verbatim (identical row/gold set as BioMapper)
    assert list(out["gold_ensembl"]) == list(df["gold_ensembl"])


def test_run_competitor_records_unsupported_targets_as_protocol_delta():
    client = FakeClient("ensembl_only", {"BRCA1": {"ENSEMBL:ENSG00000012048"}}, supported={"ENSEMBL"})
    run = run_competitor(client, _hgnc_input_df(), HGNC)
    assert run.supported_targets == ["ENSEMBL"]
    assert set(run.unsupported_targets) == {"NCBIGene", "UniProtKB"}
    assert run.notes and "cannot express" in run.notes[0]


def test_score_competitor_run_uses_identical_curie_scorer():
    # BRCA1 correct (Ensembl match), TP53 wrong, NOGOLD excluded -> 1/2 accuracy on 2 scored rows.
    client = FakeClient(
        "fake",
        {"BRCA1": {"ENSEMBL:ENSG00000012048"}, "TP53": {"ENSEMBL:ENSG00000WRONG"}},
        supported={"ENSEMBL", "NCBIGene", "UniProtKB"},
    )
    run = run_competitor(client, _hgnc_input_df(), HGNC)
    result = score_competitor_run(run, HGNC)
    core = result["comparable_core"]
    assert core["scored_denominator"] == 2  # NOGOLD excluded
    assert core["correct"] == 1
    assert core["top1_accuracy"] == pytest.approx(0.5)
    assert result["tool"] == "fake"
    assert result["unsupported_targets"] == []


def test_missing_prediction_counts_as_miss_not_error():
    client = FakeClient("empty", {}, supported={"ENSEMBL", "NCBIGene", "UniProtKB"})
    run = run_competitor(client, _hgnc_input_df(), HGNC)
    result = score_competitor_run(run, HGNC)
    # No predictions at all -> 0 correct over 2 scored rows (an honest zero, not a crash).
    assert result["comparable_core"]["correct"] == 0
    assert result["comparable_core"]["scored_denominator"] == 2
    assert result["coverage"]["n_predicted"] == 0
