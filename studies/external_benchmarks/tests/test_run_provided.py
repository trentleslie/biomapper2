"""Provided-ID CLI wiring + orchestrator fail-closed path (offline; live collaborators faked)."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

import studies.external_benchmarks.run as run_mod
from studies.external_benchmarks.config import PROVIDED_ID_BACKBONE, PROVIDED_ID_REGISTRY


def test_cli_parses_provided_id_subcommand():
    parser = run_mod.build_parser()
    args = parser.parse_args(["provided-id", "--dataset", "ncbi-gene2ensembl-provided-id", "--source", "x.gz"])
    assert args.command == "provided-id"
    assert args.dataset == "ncbi-gene2ensembl-provided-id"
    assert args.source == "x.gz"


def test_cli_rejects_unknown_provided_dataset():
    parser = run_mod.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["provided-id", "--dataset", "not-a-dataset", "--source", "x"])


def test_cli_legacy_hajjar_flag_still_parses():
    parser = run_mod.build_parser()
    args = parser.parse_args(["--supplement", "hajjar.csv"])
    assert args.command is None
    assert args.supplement == "hajjar.csv"


def test_registry_and_backbone_map_are_aligned():
    # every provided-ID dataset has a backbone-source entry (None allowed for the Hajjar anchor)
    assert set(PROVIDED_ID_REGISTRY) == set(PROVIDED_ID_BACKBONE)
    assert PROVIDED_ID_BACKBONE["hajjar-100-provided-id"] is None
    assert PROVIDED_ID_BACKBONE["ncbi-gene2ensembl-provided-id"] is not None


def _install_fakes(monkeypatch, tmp_path, *, result, run_ok=True):
    import studies.external_benchmarks.adapters.provided_id as adapter_mod
    import studies.external_benchmarks.report.campaign as campaign_mod
    import studies.external_benchmarks.runner as runner_mod
    import studies.external_benchmarks.scorers.provided_id_scorer as scorer_mod

    monkeypatch.setattr("biomapper2.mapper.Mapper", lambda *a, **k: SimpleNamespace(linker=object()))

    tsv = tmp_path / "mapped.tsv"
    pd.DataFrame({"entrez": ["672"], "chosen_kg_id": ["NCBIGene:672"]}).to_csv(tsv, sep="\t", index=False)

    bundle = SimpleNamespace(
        input_df=pd.DataFrame({"entrez": ["672"], "gold_ensembl": ["ENSEMBL:ENSG1"], "query_placeholder": [""]}),
        card={"source_sha256": "deadbeef", "dataset": "ncbi-gene2ensembl-provided-id"},
    )
    monkeypatch.setattr(adapter_mod, "load_provided", lambda *a, **k: bundle)
    monkeypatch.setattr(adapter_mod, "persist_subsample", lambda *a, **k: tmp_path / "sub.csv")

    run = SimpleNamespace(ok=run_ok, output_tsv=str(tsv) if run_ok else None, stats={}, manifest={}, error="boom")
    monkeypatch.setattr(runner_mod, "run_provided_id", lambda *a, **k: run)
    monkeypatch.setattr(scorer_mod, "score_provided_id", lambda *a, **k: result)
    monkeypatch.setattr(campaign_mod, "assemble_campaign_report", lambda **k: None)


def test_orchestrate_provided_offline_happy_path(monkeypatch, tmp_path):
    result = {
        "arm": "gene",
        "comparable_core": {"metric": "top1_accuracy", "top1_accuracy": 0.9, "correct": 9, "scored_denominator": 10},
        "coverage": {"n_predicted": 10, "total": 10, "fraction": 1.0},
        "curie_stats": {"precision": 0.9, "recall": 0.9, "f1": 0.9, "predicted_and_gold": 10},
    }
    _install_fakes(monkeypatch, tmp_path, result=result)
    config = PROVIDED_ID_REGISTRY["ncbi-gene2ensembl-provided-id"]
    out = run_mod.orchestrate_provided(
        config=config,
        source="ftp://example/gene2ensembl.gz",
        backbone_config=PROVIDED_ID_BACKBONE["ncbi-gene2ensembl-provided-id"],
        out_dir=tmp_path / "out",
        run_gate_first=False,
    )
    assert out["dataset"] == config.key
    assert (tmp_path / "out" / f"{config.key}_provided_results.json").exists()
    assert (tmp_path / "out" / "dataset_card.json").exists()


def test_orchestrate_provided_refuses_failed_run(monkeypatch, tmp_path):
    _install_fakes(monkeypatch, tmp_path, result={}, run_ok=False)
    config = PROVIDED_ID_REGISTRY["ncbi-gene2ensembl-provided-id"]
    with pytest.raises(RuntimeError, match="produced no result|boom"):
        run_mod.orchestrate_provided(
            config=config,
            source="ftp://example/gene2ensembl.gz",
            backbone_config=PROVIDED_ID_BACKBONE["ncbi-gene2ensembl-provided-id"],
            out_dir=tmp_path / "out",
            run_gate_first=False,
        )
