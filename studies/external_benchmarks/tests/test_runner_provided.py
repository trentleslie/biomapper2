"""Provided-ID runner — provided-path mapping guard + anti-trivial-100% invariant (offline)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from studies.external_benchmarks.config import PROVIDED_NCBI_GENE2ENSEMBL
from studies.external_benchmarks.runner import NoProvidedMappingError, run_provided_id
from studies.external_benchmarks.scorers.provided_id_scorer import TargetInProvidedError


class FakeMapper:
    class _BiolinkClient:
        biolink_version = "4.2.5"

    def __init__(self, provided=3):
        self.provided = provided
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
        self.calls.append(
            dict(
                entity_type=entity_type,
                name_column=name_column,
                provided_id_columns=list(provided_id_columns),
                vocab=vocab,
                annotation_mode=annotation_mode,
            )
        )
        out = Path(output_dir) / f"{output_prefix}_MAPPED.tsv"
        pd.DataFrame(
            {"entrez": ["672"], "chosen_kg_id": ["NCBIGene:672"], "kg_equivalent_ids": ["{'ENSEMBL': ['ENSG1']}"]}
        ).to_csv(out, sep="\t", index=False)
        # provided-ID mode: the assign path is off (annotation_mode='none'), so assigned is 0 by design
        stats = {"mapped_to_kg_assigned": 0, "mapped_to_kg_provided": self.provided}
        return str(out), stats


def _input_df():
    return pd.DataFrame({"entrez": ["672"], "gold_ensembl": ["ENSEMBL:ENSG1"], "query_placeholder": [""]})


def test_runner_provides_source_holds_out_target(tmp_path):
    mapper = FakeMapper(provided=3)
    run = run_provided_id(
        mapper, _input_df(), PROVIDED_NCBI_GENE2ENSEMBL, tmp_path, dataset_sha="sha", repo_root=Path.cwd()
    )
    assert run.ok
    call = mapper.calls[0]
    # the SOURCE is the only provided column; annotation is off (pure provided-ID expansion)
    assert call["provided_id_columns"] == ["entrez"]
    assert call["annotation_mode"] == "none"
    assert call["vocab"] is None
    man = run.manifest
    assert man["mode"] == "provided_id"
    assert man["provided_id_columns"] == ["entrez"]
    assert man["held_out_target_columns"] == {"ENSEMBL": "gold_ensembl"}
    assert (tmp_path / "ncbi-gene2ensembl-provided-id_provided_manifest.json").exists()


def test_runner_refuses_zero_provided_mappings(tmp_path):
    # mapped_to_kg_provided == 0 means the source never linked -> refuse (broken run, not a zero).
    mapper = FakeMapper(provided=0)
    with pytest.raises(NoProvidedMappingError):
        run_provided_id(
            mapper, _input_df(), PROVIDED_NCBI_GENE2ENSEMBL, tmp_path, dataset_sha="s", repo_root=Path.cwd()
        )


def test_runner_scores_zero_mappings_when_source_gap_is_known(tmp_path):
    # A direction with a DOCUMENTED source gap (e.g. MetaBench kegg2hmdb: the KEGG source id is not a
    # queryable KG node) legitimately maps zero. That is a real 0/n result, not a broken run, so the
    # guard must NOT abort -- the run proceeds and is scorable as all-misses.
    import dataclasses

    config = dataclasses.replace(PROVIDED_NCBI_GENE2ENSEMBL, known_source_gap=True)
    mapper = FakeMapper(provided=0)
    run = run_provided_id(mapper, _input_df(), config, tmp_path, dataset_sha="s", repo_root=Path.cwd())
    assert run.ok  # did not raise; a documented-gap direction is scored, not refused


def test_runner_anti_trivial_guard_runs_before_mapper(tmp_path):
    # A config whose target is not held out must fail loud BEFORE the mapper is ever called.
    from types import SimpleNamespace

    bad = SimpleNamespace(
        key="bad",
        arm="gene",
        entity_type="gene",
        input_type="provided_id",
        annotation_mode="none",
        source_id_column="entrez",
        source_namespace="NCBIGene",
        name_column="query_placeholder",
        gold_target_columns=(("NCBIGene", "entrez"),),
    )
    mapper = FakeMapper()
    with pytest.raises(TargetInProvidedError):
        run_provided_id(mapper, _input_df(), bad, tmp_path, dataset_sha="s", repo_root=Path.cwd())
    assert mapper.calls == []  # guard fired first; the mapper was never invoked
