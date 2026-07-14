"""Runner drives the gene/protein (CurieDatasetConfig) arm too — anti-trivial-100% carried over."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from studies.external_benchmarks.config import HGNC
from studies.external_benchmarks.runner import TrivialMappingError, run_vocab


class FakeMapper:
    class _BiolinkClient:
        biolink_version = "4.2.5"

    def __init__(self, assigned=3, gold_in_provided=False):
        self.assigned = assigned
        self.gold_in_provided = gold_in_provided
        self.calls = []
        self.biolink_client = self._BiolinkClient()

    def map_dataset_to_kg(
        self,
        *,
        dataset,
        entity_type,
        name_column,
        provided_id_columns,
        vocab,
        annotation_mode,
        output_dir,
        output_prefix,
    ):
        self.calls.append(dict(entity_type=entity_type, provided_id_columns=list(provided_id_columns), vocab=vocab))
        out = Path(output_dir) / f"{output_prefix}_MAPPED.tsv"
        pd.DataFrame({name_column: ["BRCA1"], "chosen_kg_id": [f"NCBIGene:{vocab}"]}).to_csv(out, sep="\t", index=False)
        stats = {
            "mapped_to_kg_assigned": 0 if self.gold_in_provided else self.assigned,
            "mapped_to_kg_provided": self.assigned if self.gold_in_provided else 0,
        }
        return str(out), stats


def _input_df():
    return pd.DataFrame({HGNC.name_column: ["BRCA1"], "gold_ensembl": ["ENSEMBL:ENSG00000012048"]})


def test_runner_runs_curie_config_name_only(tmp_path):
    mapper = FakeMapper(assigned=3)
    run = run_vocab(mapper, _input_df(), HGNC, "ENSEMBL", tmp_path, dataset_sha="sha", repo_root=Path.cwd())
    assert run.ok
    # entity_type flows from the gene/protein config; run mode is name-only (gold held out)
    assert mapper.calls[0]["entity_type"] == "gene"
    assert mapper.calls[0]["provided_id_columns"] == []
    man = run.manifest
    assert man["dataset"] == HGNC.key
    assert man["entity_type"] == "gene"
    assert (tmp_path / f"{HGNC.key}_ENSEMBL_manifest.json").exists()


def test_curie_arm_trivial_100_trap_raises(tmp_path):
    # Gold-as-provided -> assigned == 0 -> refuse (same guard as the metabolite arm).
    mapper = FakeMapper(gold_in_provided=True)
    with pytest.raises(TrivialMappingError):
        run_vocab(mapper, _input_df(), HGNC, "ENSEMBL", tmp_path, dataset_sha="s", repo_root=Path.cwd())
