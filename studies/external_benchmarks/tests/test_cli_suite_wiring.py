"""CLI wiring for the last three benchmarks (necs / metaboliteannotator / hgnc) + KG-snapshot /
ChEBI-release run provenance. The orchestrators already exist and are covered by their adapter
tests; this file pins the *wiring* — that each subcommand parses and that ``main()`` dispatches to
the right orchestrator with the right source construction — plus the manifest provenance fields.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import studies.external_benchmarks.run as run_mod
import studies.external_benchmarks.runner as runner_mod
from studies.external_benchmarks.config import HGNC, NAME_HIT_REGISTRY, NECS


# --------------------------------------------------------------------------------------------------
# Parse: each new subcommand is registered with the expected defaults.
# --------------------------------------------------------------------------------------------------
def test_cli_parses_necs_subcommand():
    parser = run_mod.build_parser()
    args = parser.parse_args(["necs", "--no-gate"])
    assert args.command == "necs"
    assert args.source is None  # main() falls back to the pinned Metabolon MOESM5 URL
    assert args.no_gate is True


def test_cli_parses_metaboliteannotator_subcommand():
    parser = run_mod.build_parser()
    args = parser.parse_args(["metaboliteannotator"])
    assert args.command == "metaboliteannotator"
    # No --source: the live run fetches the 6 MetaboLights sets from config.accessions.
    assert not hasattr(args, "source") or args.source is None


def test_cli_parses_hgnc_subcommand():
    parser = run_mod.build_parser()
    args = parser.parse_args(["hgnc"])
    assert args.command == "hgnc"
    assert args.source is None  # main() falls back to the pinned HGNC complete-set URL


# --------------------------------------------------------------------------------------------------
# Dispatch: main() routes to the right orchestrator with the right source.
# --------------------------------------------------------------------------------------------------
def _record(monkeypatch, fn_name):
    calls: dict[str, object] = {}

    def _fake(**kwargs):
        calls.update(kwargs)
        return {"out_dir": "out", "report": "report.md"}

    monkeypatch.setattr(run_mod, fn_name, _fake)
    return calls


def test_dispatch_necs_defaults_source_to_config_url(monkeypatch):
    calls = _record(monkeypatch, "orchestrate_necs")
    monkeypatch.setattr("sys.argv", ["run.py", "necs", "--no-gate"])
    run_mod.main()
    assert calls["source"] == NECS.source_url  # default = pinned supplement URL
    assert calls["run_gate_first"] is False


def test_dispatch_metaboliteannotator_builds_sources_from_registry(monkeypatch):
    calls = _record(monkeypatch, "orchestrate_metaboliteannotator")
    monkeypatch.setattr("sys.argv", ["run.py", "metaboliteannotator", "--no-gate"])
    run_mod.main()
    # sources maps every ion-mode key -> its 6 MetaboLights accessions (auto-fetch source).
    expected = {key: cfg.accessions for key, cfg in NAME_HIT_REGISTRY.items()}
    assert calls["sources"] == expected
    # sanity: the six MTBLS sets are actually present.
    for accs in calls["sources"].values():
        assert len(accs) == 6 and all(a.startswith("MTBLS") for a in accs)


def test_dispatch_hgnc_routes_to_backbone_with_config(monkeypatch):
    calls = _record(monkeypatch, "orchestrate_backbone")
    monkeypatch.setattr("sys.argv", ["run.py", "hgnc", "--no-gate"])
    run_mod.main()
    assert calls["config"] is HGNC
    assert calls["source"] == HGNC.source_url  # default = pinned complete-set URL (streamed)


def test_dispatch_hgnc_local_source_becomes_line_iter(monkeypatch, tmp_path):
    calls = _record(monkeypatch, "orchestrate_backbone")
    local = tmp_path / "hgnc.txt"
    local.write_text("symbol\tensembl_gene_id\nTP53\tENSG00000141510\n")
    monkeypatch.setattr("sys.argv", ["run.py", "hgnc", "--source", str(local), "--no-gate"])
    run_mod.main()
    # A local path is handed to the backbone loader as a line iterator, not a raw string/bytes.
    assert not isinstance(calls["source"], (str, bytes))
    assert hasattr(calls["source"], "__iter__")


# --------------------------------------------------------------------------------------------------
# Provenance: KG snapshot / ChEBI release land in the manifest (both name- and provided-ID paths).
# --------------------------------------------------------------------------------------------------
def test_kg_provenance_defaults_to_unrecorded(monkeypatch):
    monkeypatch.delenv("KG_SNAPSHOT", raising=False)
    monkeypatch.delenv("CHEBI_RELEASE", raising=False)
    prov = runner_mod.kg_provenance()
    assert prov == {"kg_snapshot": "unrecorded", "chebi_release": "unrecorded"}
    assert "kg_health_probe" not in prov  # no network by default (keeps unit tests offline)


def test_kg_provenance_reads_env(monkeypatch):
    monkeypatch.setenv("KG_SNAPSHOT", "2026-06-01")
    monkeypatch.setenv("CHEBI_RELEASE", "ChEBI-238")
    prov = runner_mod.kg_provenance()
    assert prov["kg_snapshot"] == "2026-06-01"
    assert prov["chebi_release"] == "ChEBI-238"


def test_build_manifest_includes_kg_provenance(monkeypatch, tmp_path):
    monkeypatch.setenv("KG_SNAPSHOT", "snap-X")
    monkeypatch.setenv("CHEBI_RELEASE", "ChEBI-999")
    m = runner_mod.build_manifest(
        vocab="CHEBI",
        config=NECS,
        dataset_sha="abc",
        biolink_version="4.2.5",
        output_tsv="out.tsv",
        repo_root=tmp_path,
    )
    assert m["kg_snapshot"] == "snap-X"
    assert m["chebi_release"] == "ChEBI-999"


def test_build_manifest_explicit_kg_prov_wins(tmp_path):
    m = runner_mod.build_manifest(
        vocab="CHEBI",
        config=NECS,
        dataset_sha="abc",
        biolink_version="4.2.5",
        output_tsv="out.tsv",
        repo_root=tmp_path,
        kg_prov={"kg_snapshot": "explicit", "chebi_release": "explicit-chebi"},
    )
    assert m["kg_snapshot"] == "explicit"
    assert m["chebi_release"] == "explicit-chebi"
