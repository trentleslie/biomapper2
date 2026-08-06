"""Unit 2 — runner over mapper (offline; fake mapper injected)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from studies.external_benchmarks.config import HAJJAR
from studies.external_benchmarks.runner import (
    EmptyDatasetError,
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


# --------------------------------------------------------------------------------------------------
# Empty input: a source that yields no rows must fail loudly HERE, not survive into the mapper.
#
# Regression test for the 2026-08-05 SwissLipids failure. Its pinned source_url returned HTTP 200
# with a zero-byte body, so the adapter produced 0 rows, the empty frame reached the mapper, and the
# run died ~20 minutes later inside pandas with "columns overlap but no suffix specified" — an error
# naming schema columns, which points at the wrong problem entirely.
# --------------------------------------------------------------------------------------------------
def _empty_input_df():
    """Header-only frame — exactly what an adapter emits when its source returns an empty body."""
    return pd.DataFrame({HAJJAR.name_column: [], HAJJAR.gold_chebi_column: []})


def test_run_all_rejects_an_empty_dataset_before_calling_the_mapper(tmp_path):
    mapper = FakeMapper()
    with pytest.raises(EmptyDatasetError) as exc:
        run_all(
            mapper,
            _empty_input_df(),
            HAJJAR,
            tmp_path,
            dataset_sha="s",
            repo_root=Path.cwd(),
            vocabs=("CHEBI",),
        )
    msg = str(exc.value)
    assert HAJJAR.key in msg  # says WHICH dataset
    assert "0 rows" in msg  # says WHAT is wrong
    assert mapper.calls == [], "the mapper must never be handed an empty frame"


def test_empty_dataset_error_names_the_source_url_when_there_is_one(tmp_path):
    """The usual culprit is a dead source URL, so the message must point at it.

    Asserted on a config with a real source_url — HAJJAR's is "", and `"" in msg` is vacuously
    true, which would make this assertion prove nothing.
    """
    config = replace(HAJJAR, source_url="https://example.invalid/lipids.tsv")
    mapper = FakeMapper()
    with pytest.raises(EmptyDatasetError) as exc:
        run_all(
            mapper,
            _empty_input_df(),
            config,
            tmp_path,
            dataset_sha="s",
            repo_root=Path.cwd(),
            vocabs=("CHEBI",),
        )
    assert "https://example.invalid/lipids.tsv" in str(exc.value)


def test_run_all_still_accepts_a_single_row(tmp_path):
    """The guard must reject empty, not merely small — a 1-row dataset is legitimate."""
    mapper = FakeMapper()
    results = run_all(mapper, _input_df(), HAJJAR, tmp_path, dataset_sha="s", repo_root=Path.cwd(), vocabs=("CHEBI",))
    assert results["CHEBI"].ok


def test_run_vocab_also_rejects_an_empty_dataset(tmp_path):
    """orchestrate_metabench calls run_vocab directly, bypassing run_all's guard."""
    mapper = FakeMapper()
    with pytest.raises(EmptyDatasetError):
        run_vocab(mapper, _empty_input_df(), HAJJAR, "CHEBI", tmp_path, dataset_sha="s", repo_root=Path.cwd())
    assert mapper.calls == []


def test_empty_dataset_error_is_not_swallowed_as_a_per_vocab_error(tmp_path):
    """run_all files ordinary per-vocab exceptions as errors and continues; this must not be one.

    Guards the failure mode where moving the check into run_vocab silently downgrades a
    whole-run stop into a single vocab's recorded error while the other vocabs carry on.
    """
    mapper = FakeMapper()
    with pytest.raises(EmptyDatasetError):
        run_all(
            mapper,
            _empty_input_df(),
            HAJJAR,
            tmp_path,
            dataset_sha="s",
            repo_root=Path.cwd(),
            vocabs=("CHEBI", "HMDB"),
        )
