"""Pham CLI wiring: the --ambiguous-only flag reaches orchestrate_pham (offline; orchestrator faked)."""

from __future__ import annotations

import studies.external_benchmarks.run as run_mod


def test_cli_parses_pham_ambiguous_only_flag():
    parser = run_mod.build_parser()
    args = parser.parse_args(["pham", "--source", "x.csv", "--no-gate", "--ambiguous-only"])
    assert args.command == "pham"
    assert args.ambiguous_only is True
    # defaults off (full-population behavior preserved)
    args2 = parser.parse_args(["pham", "--source", "x.csv"])
    assert args2.ambiguous_only is False


def test_main_dispatches_pham_ambiguous_only(monkeypatch, tmp_path, capsys):
    # The load-bearing wiring Greptile flagged: `python -m ...run pham --ambiguous-only` must reach
    # orchestrate_pham with ambiguous_only=True (previously the CLI could not enable the mode at all).
    local = tmp_path / "pham.csv"
    local.write_bytes(b"metabolite_name,metanetx_id\ntmp,MNXM1\n")
    calls: list[dict] = []
    monkeypatch.setattr(
        run_mod, "orchestrate_pham", lambda **k: (calls.append(k), {"out_dir": "d", "report": "r"})[1]
    )
    monkeypatch.setattr("sys.argv", ["run", "pham", "--source", str(local), "--no-gate", "--ambiguous-only"])
    run_mod.main()

    assert len(calls) == 1
    assert calls[0]["ambiguous_only"] is True
    assert calls[0]["run_gate_first"] is False  # --no-gate honored
    assert "Saved Pham run" in capsys.readouterr().out


def test_main_pham_defaults_to_full_population(monkeypatch, tmp_path):
    # Without --ambiguous-only the CLI keeps the full-population default (ambiguous_only=False).
    local = tmp_path / "pham.csv"
    local.write_bytes(b"metabolite_name,metanetx_id\ntmp,MNXM1\n")
    calls: list[dict] = []
    monkeypatch.setattr(
        run_mod, "orchestrate_pham", lambda **k: (calls.append(k), {"out_dir": "d", "report": "r"})[1]
    )
    monkeypatch.setattr("sys.argv", ["run", "pham", "--source", str(local), "--no-gate"])
    run_mod.main()

    assert calls[0]["ambiguous_only"] is False
