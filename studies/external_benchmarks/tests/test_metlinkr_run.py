"""metLinkR CLI wiring: subparser registration + main() dispatch (offline; orchestrator faked)."""

from __future__ import annotations

import studies.external_benchmarks.run as run_mod


def test_cli_parses_metlinkr_subcommand():
    parser = run_mod.build_parser()
    args = parser.parse_args(["metlinkr", "--source", "ManualMappings.csv", "--no-gate"])
    assert args.command == "metlinkr"
    assert args.source == "ManualMappings.csv"
    assert args.no_gate is True


def test_cli_metlinkr_source_defaults_to_none():
    parser = run_mod.build_parser()
    args = parser.parse_args(["metlinkr"])
    assert args.command == "metlinkr"
    assert args.source is None  # main() falls back to the live "fetch" sentinel


def test_main_dispatches_metlinkr_to_orchestrator(monkeypatch, capsys):
    # The load-bearing wiring: `python -m ...run metlinkr` must reach orchestrate_metlinkr. With no
    # --source the source falls back to the "fetch" sentinel; --no-gate flows through to the runner.
    calls: list[dict] = []

    def _fake_orchestrate_metlinkr(**kwargs):
        calls.append(kwargs)
        return {"out_dir": "runs/metlinkr_X", "report": "runs/metlinkr_X/metlinkr_report.md"}

    monkeypatch.setattr(run_mod, "orchestrate_metlinkr", _fake_orchestrate_metlinkr)
    monkeypatch.setattr("sys.argv", ["run", "metlinkr", "--no-gate"])
    run_mod.main()

    assert len(calls) == 1
    assert calls[0]["source"] == "fetch"  # no --source -> live fetch sentinel
    assert calls[0]["run_gate_first"] is False  # --no-gate honored
    assert calls[0]["out_dir"] is None
    assert "Saved metLinkR run" in capsys.readouterr().out


def test_main_metlinkr_reads_local_source_to_bytes(monkeypatch, tmp_path):
    # A local ManualMappings.csv path is read to bytes (load_metlinkr parses bytes directly);
    # a non-fetch string would otherwise trigger a live network fetch.
    local = tmp_path / "ManualMappings.csv"
    local.write_bytes(b"IPT_METABOLITE_NAME,Manual_Metabolite_Group_Label\nglucose,1\n")
    calls: list[dict] = []

    monkeypatch.setattr(
        run_mod, "orchestrate_metlinkr", lambda **k: (calls.append(k), {"out_dir": "d", "report": "r"})[1]
    )
    monkeypatch.setattr("sys.argv", ["run", "metlinkr", "--source", str(local), "--no-gate"])
    run_mod.main()

    assert isinstance(calls[0]["source"], bytes)
    assert b"glucose" in calls[0]["source"]
