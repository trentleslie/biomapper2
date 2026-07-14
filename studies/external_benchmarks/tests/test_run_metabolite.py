"""RefMet + SRM1950 CLI wiring and orchestrator fail-closed paths (offline; live collaborators faked)."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

import studies.external_benchmarks.run as run_mod
from studies.external_benchmarks.config import REFMET, SRM1950


def test_cli_parses_refmet_subcommand():
    parser = run_mod.build_parser()
    args = parser.parse_args(["refmet", "--source", "refmet.csv"])
    assert args.command == "refmet"
    assert args.source == "refmet.csv"


def test_cli_parses_srm1950_subcommand():
    parser = run_mod.build_parser()
    args = parser.parse_args(["srm1950", "--source", "metabolites.csv", "--no-gate"])
    assert args.command == "srm1950"
    assert args.no_gate is True


def test_registry_contains_both_new_datasets():
    from studies.external_benchmarks.config import REGISTRY

    assert REGISTRY["refmet"] is REFMET
    assert REGISTRY["srm1950"] is SRM1950
    # both are name->structure metabolite datasets with the InChIKey oracle
    for cfg in (REFMET, SRM1950):
        assert cfg.arm == "metabolite"
        assert cfg.input_type == "name"
        assert cfg.gold_inchikey_column == "gold_inchikey"


def _scored_result(top1: float | None, scored: int) -> dict:
    return {
        "vocab": "CHEBI",
        "input_type": "name",
        "comparable_core": {
            "metric": "top1_accuracy",
            "top1_accuracy": top1,
            "correct": 1,
            "scored_denominator": scored,
        },
        "comparable_core_charge_normalized": {
            "metric": "top1_accuracy_charge_normalized",
            "top1_accuracy": top1,
            "correct": 1,
            "scored_denominator": scored,
        },
        "coverage": {"n_predicted": scored, "total": scored, "fraction": 1.0},
        "fallback_bucket": {"count": 0, "rows": []},
        "per_row": [],
    }


def _install_common_fakes(monkeypatch, tmp_path, *, result, run_ok=True):
    """Fake Mapper + StructureResolver + oracle + scorer + reconcile + report for both orchestrators."""
    import studies.external_benchmarks.oracle as oracle_mod
    import studies.external_benchmarks.report.campaign as campaign_mod
    import studies.external_benchmarks.runner as runner_mod
    import studies.external_benchmarks.scorers.structure_oracle_scorer as scorer_mod
    import studies.external_benchmarks.verify as verify_mod

    monkeypatch.setattr("biomapper2.mapper.Mapper", lambda *a, **k: SimpleNamespace(linker=object()))
    monkeypatch.setattr("biomapper2.core.structure_resolver.StructureResolver", lambda *a, **k: object())
    monkeypatch.setattr(oracle_mod, "KGStructureOracle", lambda *a, **k: object())

    tsv = tmp_path / "mapped.tsv"
    pd.DataFrame({"refmet_name": ["Glucose"], "chosen_kg_id": ["CHEBI:4167"]}).to_csv(tsv, sep="\t", index=False)
    vr = SimpleNamespace(
        vocab="CHEBI", ok=run_ok, output_tsv=str(tsv) if run_ok else None, stats={}, manifest={}, error="boom"
    )
    monkeypatch.setattr(runner_mod, "run_all", lambda *a, **k: {"CHEBI": vr})
    monkeypatch.setattr(scorer_mod, "score_structure_oracle", lambda *a, **k: result)
    monkeypatch.setattr(verify_mod, "reconcile", lambda *a, **k: SimpleNamespace(passed=True, mismatches=[]))
    monkeypatch.setattr(campaign_mod, "assemble_campaign_report", lambda **k: None)


REFMET_LINES = [
    "refmet_id,refmet_name,super_class,main_class,sub_class,formula,exactmass,pubchem_cid,chebi_id,hmdb_id,lipidmaps_id,kegg_id,inchi_key",
    "RM1,Glucose,Carb,Mono,Hex,C6H12O6,180,5793,4167,HMDB0000122,,C00031,WQZGKKKJIJFFOK-GASJEMHNSA-N",
    "RM2,NoStructure,,,,,,,,,,,",
]


def test_orchestrate_refmet_offline_happy_path(monkeypatch, tmp_path):
    _install_common_fakes(monkeypatch, tmp_path, result=_scored_result(1.0, 1))
    out = run_mod.orchestrate_refmet(source=iter(REFMET_LINES), out_dir=tmp_path / "out", run_gate_first=False)
    assert out["vocab"] == "CHEBI"
    assert (tmp_path / "out" / "dataset_card.json").exists()
    assert (tmp_path / "out" / "CHEBI_results.json").exists()
    # the exact scored subsample is persisted beside the card (reproducibility artifact)
    assert (tmp_path / "out" / "refmet_subsample.csv").exists()


def test_orchestrate_refmet_refuses_unscorable_run(monkeypatch, tmp_path):
    _install_common_fakes(monkeypatch, tmp_path, result=_scored_result(None, 0))
    out_dir = tmp_path / "out"
    with pytest.raises(RuntimeError, match="no scorable rows|top1_accuracy is None"):
        run_mod.orchestrate_refmet(source=iter(REFMET_LINES), out_dir=out_dir, run_gate_first=False)
    assert not (out_dir / "CHEBI_results.json").exists()


def test_orchestrate_srm1950_offline_happy_path(monkeypatch, tmp_path):
    _install_common_fakes(monkeypatch, tmp_path, result=_scored_result(1.0, 1))
    raw = pd.DataFrame(
        {
            "HMDB_ID": ["HMDB0000122"],
            "NAME": ["Glucose"],
            "SMILES": ["OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O"],
            "INCHIKEY": [""],
        }
    )
    out = run_mod.orchestrate_srm1950(source=raw, out_dir=tmp_path / "out", run_gate_first=False)
    assert out["vocab"] == "CHEBI"
    assert (tmp_path / "out" / "dataset_card.json").exists()
    assert (tmp_path / "out" / "CHEBI_results.json").exists()


def test_orchestrate_srm1950_refuses_unscorable_run(monkeypatch, tmp_path):
    _install_common_fakes(monkeypatch, tmp_path, result=_scored_result(None, 0))
    raw = pd.DataFrame({"HMDB_ID": ["H1"], "NAME": ["Glucose"], "SMILES": ["CCO"], "INCHIKEY": [""]})
    out_dir = tmp_path / "out"
    with pytest.raises(RuntimeError, match="no scorable rows|top1_accuracy is None"):
        run_mod.orchestrate_srm1950(source=raw, out_dir=out_dir, run_gate_first=False)
    assert not (out_dir / "CHEBI_results.json").exists()
