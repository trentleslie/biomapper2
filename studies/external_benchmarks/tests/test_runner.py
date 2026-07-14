"""Unit 2 — runner over mapper (offline; fake mapper injected)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from studies.external_benchmarks.config import HAJJAR
from studies.external_benchmarks.runner import (
    TrivialMappingError,
    assigned_stats_nonnull,
    run_all,
    run_vocab,
)


class FakeMapper:
    """Records calls and writes a stub MAPPED tsv; returns injectable stats.

    ``fail_vocabs`` forces a raised error for specific vocabs (Kestrel-error simulation).
    """

    class _BiolinkClient:
        biolink_version = "4.2.5"

    def __init__(self, assigned=3, fail_vocabs=(), gold_in_provided=False):
        self.assigned = assigned
        self.fail_vocabs = set(fail_vocabs)
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
        self.calls.append(
            dict(
                vocab=vocab,
                provided_id_columns=list(provided_id_columns),
                annotation_mode=annotation_mode,
                name_column=name_column,
            )
        )
        if vocab in self.fail_vocabs:
            raise RuntimeError(f"Kestrel error on {vocab}")
        out = Path(output_dir) / f"{output_prefix}_MAPPED.tsv"
        pd.DataFrame({name_column: ["x"], "chosen_kg_id": [f"{vocab}:1"]}).to_csv(out, sep="\t", index=False)
        stats = {
            "total_items": 1,
            "mapped_to_kg": 1,
            "mapped_to_kg_assigned": 0 if self.gold_in_provided else self.assigned,
            "mapped_to_kg_provided": self.assigned if self.gold_in_provided else 0,
        }
        return str(out), stats


def _input_df():
    return pd.DataFrame({HAJJAR.name_column: ["D-Glucose"], HAJJAR.gold_chebi_column: ["CHEBI:4167"]})


def test_assigned_stats_nonnull_helper():
    assert assigned_stats_nonnull({"mapped_to_kg_assigned": 3})
    assert not assigned_stats_nonnull({"mapped_to_kg_assigned": 0})
    assert not assigned_stats_nonnull({})


def test_happy_path_produces_outputs_and_pinned_manifest(tmp_path):
    mapper = FakeMapper(assigned=3)
    run = run_vocab(mapper, _input_df(), HAJJAR, "CHEBI", tmp_path, dataset_sha="abc123", repo_root=Path.cwd())
    assert run.ok
    assert run.output_tsv is not None and run.stats is not None and run.manifest is not None
    assert Path(run.output_tsv).exists()
    # non-null assigned stats (anti-trivial-100%)
    assert run.stats["mapped_to_kg_assigned"] == 3
    # provided_id_columns must be empty (name-only run mode)
    assert mapper.calls[0]["provided_id_columns"] == []
    assert mapper.calls[0]["annotation_mode"] == "all"
    # manifest fully pinned
    man = run.manifest
    assert man["vocab"] == "CHEBI"
    assert man["dataset_source_sha256"] == "abc123"
    assert man["kestrel_api_url"]
    assert man["biolink_version"] == "4.2.5"
    assert man["provided_id_columns"] == []
    # manifest persisted to disk
    written = json.loads((tmp_path / "hajjar-100_CHEBI_manifest.json").read_text())
    assert written["dataset_source_sha256"] == "abc123"


def test_trivial_100_trap_raises(tmp_path):
    # gold leaked as provided -> assigned == 0 -> refuse the run
    mapper = FakeMapper(gold_in_provided=True)
    with pytest.raises(TrivialMappingError):
        run_vocab(mapper, _input_df(), HAJJAR, "CHEBI", tmp_path, dataset_sha="abc", repo_root=Path.cwd())


def test_out_override_honored(tmp_path):
    override = tmp_path / "custom_out"
    mapper = FakeMapper()
    run = run_vocab(mapper, _input_df(), HAJJAR, "HMDB", override, dataset_sha="s", repo_root=Path.cwd())
    assert run.output_tsv is not None
    assert Path(run.output_tsv).parent == override
    assert (override / "hajjar-100_HMDB_manifest.json").exists()


def test_per_vocab_error_isolated(tmp_path):
    mapper = FakeMapper(fail_vocabs=("KEGG",))
    results = run_all(
        mapper,
        _input_df(),
        HAJJAR,
        tmp_path,
        dataset_sha="s",
        repo_root=Path.cwd(),
        vocabs=("CHEBI", "KEGG", "HMDB"),
    )
    assert results["CHEBI"].ok
    assert results["HMDB"].ok
    assert not results["KEGG"].ok
    assert results["KEGG"].error is not None
    assert "Kestrel error" in results["KEGG"].error
