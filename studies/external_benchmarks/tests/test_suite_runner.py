"""The ``all`` suite runner: one command that drives every self-sourcing benchmark into a single
timestamped suite dir with an aggregate manifest (backend pin + per-dataset status), so the
preprint's numbers re-run in one invocation as the code/Kraken backend evolve.

The suite is designed for unattended (nightly-CI) runs: only datasets with a pinned default source
run by default; datasets that require a hand-passed ``--source`` are reported as skipped, never
silently dropped. ``run_suite`` takes an injectable ``runners`` map so the aggregation logic is
tested offline without touching the live KG backend.
"""

from __future__ import annotations

import json
from pathlib import Path

import studies.external_benchmarks.run as run_mod


# --------------------------------------------------------------------------------------------------
# Parse: the ``all`` subcommand is registered.
# --------------------------------------------------------------------------------------------------
def test_cli_parses_all_subcommand():
    parser = run_mod.build_parser()
    args = parser.parse_args(["all", "--no-gate"])
    assert args.command == "all"
    assert args.no_gate is True


# --------------------------------------------------------------------------------------------------
# Aggregate: run_suite drives every injected runner into one suite dir + a single manifest.
# --------------------------------------------------------------------------------------------------
def _fake_runner(name):
    def _run(out_dir, run_gate_first):
        p = Path(out_dir)
        p.mkdir(parents=True, exist_ok=True)
        (p / "report.md").write_text(f"# {name}\n")
        return {"out_dir": str(p), "report": str(p / "report.md")}

    return _run


def test_run_suite_aggregates_results_into_one_manifest(tmp_path):
    runners = {"alpha": _fake_runner("alpha"), "beta": _fake_runner("beta")}
    result = run_mod.run_suite(out_dir=tmp_path, datasets=["alpha", "beta"], runners=runners, run_gate_first=False)
    manifest_path = Path(result["out_dir"]) / "suite_manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert [d["dataset"] for d in manifest["datasets"]] == ["alpha", "beta"]
    assert all(d["status"] == "ok" for d in manifest["datasets"])
    assert manifest["n_ok"] == 2 and manifest["n_failed"] == 0
    # each dataset ran in its own subdir under the one suite dir
    for d in manifest["datasets"]:
        assert Path(d["out_dir"]).resolve().is_relative_to(Path(result["out_dir"]).resolve())


def _boom_runner(out_dir, run_gate_first):
    raise RuntimeError("kaboom")


def test_run_suite_records_failure_and_continues(tmp_path):
    runners = {"good": _fake_runner("good"), "bad": _boom_runner}
    result = run_mod.run_suite(out_dir=tmp_path, datasets=["bad", "good"], runners=runners, run_gate_first=False)
    by = {d["dataset"]: d for d in result["manifest"]["datasets"]}
    assert by["bad"]["status"] == "failed" and "kaboom" in by["bad"]["error"]
    assert by["good"]["status"] == "ok"  # the suite continued past the failure
    assert result["manifest"]["n_ok"] == 1 and result["manifest"]["n_failed"] == 1


# --------------------------------------------------------------------------------------------------
# Pins: the manifest records the backend endpoint + provenance so a suite run is reproducible.
# --------------------------------------------------------------------------------------------------
def test_manifest_pins_backend_and_provenance(tmp_path, monkeypatch):
    monkeypatch.setenv("KESTREL_API_URL", "https://app.krakenkg.com/api")
    monkeypatch.setenv("KG_SNAPSHOT", "2026-08-01")
    result = run_mod.run_suite(
        out_dir=tmp_path,
        datasets=["alpha"],
        runners={"alpha": _fake_runner("alpha")},
        run_gate_first=False,
    )
    pins = result["manifest"]["pins"]
    assert pins["backend"] == "https://app.krakenkg.com/api"  # the public-Kraken endpoint is recorded
    assert pins["kg_snapshot"] == "2026-08-01"
    assert "biolink_version" in pins
    assert "git_sha" in pins


# --------------------------------------------------------------------------------------------------
# Default wiring: the built-in registry covers the self-sourcing datasets and routes each correctly.
# --------------------------------------------------------------------------------------------------
def test_suite_runners_cover_the_self_sourcing_datasets():
    assert set(run_mod._suite_runners()) == set(run_mod.SUITE_DATASETS)


def test_suite_runner_routes_necs_to_orchestrator_with_pinned_source(monkeypatch, tmp_path):
    from studies.external_benchmarks.config import NECS

    calls: dict = {}

    def _fake(**kwargs):
        calls.update(kwargs)
        return {"out_dir": str(tmp_path), "report": "r.md"}

    monkeypatch.setattr(run_mod, "orchestrate_necs", _fake)
    run_mod._suite_runners()["necs"](out_dir=tmp_path, run_gate_first=False)
    assert calls["source"] == NECS.source_url  # default = pinned Metabolon supplement URL
    assert calls["run_gate_first"] is False


def test_main_all_dispatches_to_run_suite_respecting_no_gate(monkeypatch, tmp_path, capsys):
    captured: dict = {}

    def _fake_suite(**kwargs):
        captured.update(kwargs)
        return {
            "out_dir": str(tmp_path),
            "manifest": {"n_ok": 2, "n_failed": 0, "datasets": []},
            "results": [],
        }

    monkeypatch.setattr(run_mod, "run_suite", _fake_suite)
    monkeypatch.setattr("sys.argv", ["run.py", "all", "--no-gate"])
    run_mod.main()
    assert captured["run_gate_first"] is False
    assert "suite" in capsys.readouterr().out.lower()
