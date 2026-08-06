"""The ``all`` suite runner: one command that drives every self-sourcing benchmark into a single
timestamped suite dir with an aggregate manifest (backend pin + per-dataset status), so the
preprint's numbers re-run in one invocation as the code/Kraken backend evolve.

The suite is designed for unattended (scheduled-CI) runs: a dataset qualifies when the runner can
reach its source on its own, whether that is a pinned ``source_url`` or a pinned corpus fetch. The
few whose sources are not fetchable artifacts are reported as skipped with the reason, never
silently dropped. ``run_suite`` takes an injectable ``runners`` map so the aggregation logic is
tested offline without touching the live KG backend.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
    result = run_mod.run_suite(
        out_dir=tmp_path, datasets=["alpha", "beta"], runners=runners, run_gate_first=False, probe_live=False
    )
    manifest_path = Path(result["out_dir"]) / "suite_manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    ran = [d for d in manifest["datasets"] if d["status"] != "skipped"]
    assert [d["dataset"] for d in ran] == ["alpha", "beta"]
    assert all(d["status"] == "ok" for d in ran)
    assert manifest["n_ok"] == 2 and manifest["n_failed"] == 0
    # each dataset ran in its own subdir under the one suite dir
    for d in ran:
        assert Path(d["out_dir"]).resolve().is_relative_to(Path(result["out_dir"]).resolve())


def _boom_runner(out_dir, run_gate_first):
    raise RuntimeError("kaboom")


def test_run_suite_records_failure_and_continues(tmp_path):
    runners = {"good": _fake_runner("good"), "bad": _boom_runner}
    result = run_mod.run_suite(
        out_dir=tmp_path, datasets=["bad", "good"], runners=runners, run_gate_first=False, probe_live=False
    )
    by = {d["dataset"]: d for d in result["manifest"]["datasets"]}
    assert by["bad"]["status"] == "failed" and "kaboom" in by["bad"]["error"]
    assert by["good"]["status"] == "ok"  # the suite continued past the failure
    assert result["manifest"]["n_ok"] == 1 and result["manifest"]["n_failed"] == 1


# --------------------------------------------------------------------------------------------------
# Skips: a dataset left out of the suite is RECORDED with a reason, so the manifest distinguishes a
# deliberate skip from a dataset that fell out of the registry by accident.
# --------------------------------------------------------------------------------------------------
def test_manifest_records_deliberate_skips_with_reasons(tmp_path):
    result = run_mod.run_suite(
        out_dir=tmp_path,
        datasets=["alpha"],
        runners={"alpha": _fake_runner("alpha")},
        run_gate_first=False,
        probe_live=False,
    )
    by = {d["dataset"]: d for d in result["manifest"]["datasets"]}
    for key, reason in run_mod.SUITE_SKIPPED.items():
        assert by[key]["status"] == "skipped"
        assert by[key]["reason"] == reason
    # skips are their own bucket — never silently folded into ok or failed
    assert result["manifest"]["n_skipped"] == len(run_mod.SUITE_SKIPPED)
    assert result["manifest"]["n_ok"] == 1
    assert result["manifest"]["n_failed"] == 0


def test_every_cli_dataset_is_either_run_or_explicitly_skipped():
    """No dataset may be invisible: each one either runs in the suite or carries a skip reason."""
    assert not (set(run_mod.SUITE_DATASETS) & set(run_mod.SUITE_SKIPPED))


def test_explicitly_requested_dataset_is_not_also_reported_skipped(tmp_path):
    key = next(iter(run_mod.SUITE_SKIPPED))
    result = run_mod.run_suite(
        out_dir=tmp_path, datasets=[key], runners={key: _fake_runner(key)}, run_gate_first=False, probe_live=False
    )
    entries = [d for d in result["manifest"]["datasets"] if d["dataset"] == key]
    assert len(entries) == 1 and entries[0]["status"] == "ok"


# --------------------------------------------------------------------------------------------------
# Exit status: a scheduled run that cannot go red is useless — a failed benchmark must fail the process.
# --------------------------------------------------------------------------------------------------
def _stub_suite(monkeypatch, tmp_path, *, n_ok, n_failed, datasets):
    def _fake_suite(**kwargs):
        return {
            "out_dir": str(tmp_path),
            "manifest": {"n_ok": n_ok, "n_failed": n_failed, "n_skipped": 0, "datasets": datasets},
            "results": [],
        }

    monkeypatch.setattr(run_mod, "run_suite", _fake_suite)
    monkeypatch.setattr("sys.argv", ["run.py", "all", "--no-gate"])


def test_main_all_exits_nonzero_when_a_dataset_failed(monkeypatch, tmp_path, capsys):
    _stub_suite(
        monkeypatch,
        tmp_path,
        n_ok=1,
        n_failed=1,
        datasets=[{"dataset": "bad", "status": "failed", "error": "RuntimeError: kaboom"}],
    )
    with pytest.raises(SystemExit) as exc:
        run_mod.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert str(tmp_path) in out  # the suite dir is still reported, so artifacts stay findable
    assert "kaboom" in out


def test_main_all_exits_zero_when_only_skips(monkeypatch, tmp_path):
    _stub_suite(
        monkeypatch,
        tmp_path,
        n_ok=1,
        n_failed=0,
        datasets=[{"dataset": "pham", "status": "skipped", "reason": "source requires hand reconstruction"}],
    )
    run_mod.main()  # a deliberate skip is not a failure


# --------------------------------------------------------------------------------------------------
# Pins: the manifest records the backend endpoint + provenance so a suite run is reproducible.
# --------------------------------------------------------------------------------------------------
def test_manifest_pins_backend_and_provenance(tmp_path, monkeypatch):
    monkeypatch.setenv("KESTREL_API_URL", "https://kestrel.krakenkg.com/api")
    monkeypatch.setenv("KG_SNAPSHOT", "2026-08-01")
    result = run_mod.run_suite(
        out_dir=tmp_path,
        datasets=["alpha"],
        runners={"alpha": _fake_runner("alpha")},
        run_gate_first=False,
        probe_live=False,
    )
    pins = result["manifest"]["pins"]
    assert pins["backend"] == "https://kestrel.krakenkg.com/api"  # the public-Kraken endpoint is recorded
    assert pins["kg_snapshot"] == "2026-08-01"
    assert "biolink_version" in pins
    assert "git_sha" in pins


def test_suite_pins_record_the_graph_build_on_an_unattended_run(monkeypatch, tmp_path):
    """The regression this closes: a cron run supplies no env, and must still pin a real build.

    _suite_pins defaults probe_live=True precisely so a scheduled suite cannot pin "unrecorded".
    """
    monkeypatch.delenv("KG_SNAPSHOT", raising=False)
    monkeypatch.delenv("CHEBI_RELEASE", raising=False)

    from studies.external_benchmarks import runner as runner_mod

    monkeypatch.setattr(
        runner_mod,
        "_fetch_metagraph",
        lambda refresh=False: {
            "graph": "kraken",
            "version": "2.0.1",
            "summary": {"total_nodes": 7, "total_edges": 9},
        },
    )
    monkeypatch.setattr(runner_mod, "KESTREL_API_URL", "http://kg.invalid/api")

    result = run_mod.run_suite(
        out_dir=tmp_path,
        datasets=["alpha"],
        runners={"alpha": _fake_runner("alpha")},
        run_gate_first=False,
    )
    pins = result["manifest"]["pins"]
    assert pins["kg_snapshot"] == "kraken 2.0.1 (7n/9e)"  # derived from the graph, not typed by hand
    assert pins["kg_metagraph"]["version"] == "2.0.1"


def test_suite_flags_a_kg_that_moved_mid_run(monkeypatch, tmp_path):
    """Pins are sampled BEFORE the datasets run; a redeploy mid-suite must not be attributed silently."""
    from studies.external_benchmarks import runner as runner_mod

    builds = [
        {"graph": "kraken", "version": "2.0.1", "summary": {"total_nodes": 7, "total_edges": 9}},
        {"graph": "kraken", "version": "2.0.2", "summary": {"total_nodes": 8, "total_edges": 9}},
    ]
    seen = {"n": 0}

    def _shifting(refresh=False):
        i = min(seen["n"], len(builds) - 1)
        seen["n"] += 1
        return builds[i]

    monkeypatch.delenv("KG_SNAPSHOT", raising=False)
    monkeypatch.setattr(runner_mod, "_fetch_metagraph", _shifting)

    result = run_mod.run_suite(
        out_dir=tmp_path,
        datasets=["alpha"],
        runners={"alpha": _fake_runner("alpha")},
        run_gate_first=False,
    )
    m = result["manifest"]
    assert m["pins"]["kg_metagraph"]["version"] == "2.0.1"  # pinned to the build that ran the datasets
    assert m["kg_stable_during_run"] is False
    assert m["kg_metagraph_at_end"]["version"] == "2.0.2"


def test_suite_reports_a_stable_kg_when_the_build_did_not_move(monkeypatch, tmp_path):
    from studies.external_benchmarks import runner as runner_mod

    build = {"graph": "kraken", "version": "2.0.1", "summary": {"total_nodes": 7, "total_edges": 9}}
    monkeypatch.delenv("KG_SNAPSHOT", raising=False)
    monkeypatch.setattr(runner_mod, "_fetch_metagraph", lambda refresh=False: build)

    result = run_mod.run_suite(
        out_dir=tmp_path,
        datasets=["alpha"],
        runners={"alpha": _fake_runner("alpha")},
        run_gate_first=False,
    )
    assert result["manifest"]["kg_stable_during_run"] is True
    assert "kg_metagraph_at_end" not in result["manifest"]  # only recorded when it actually moved


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


@pytest.mark.parametrize(
    "key, orchestrator, config_name",
    [
        ("refmet", "orchestrate_refmet", "REFMET"),
        ("srm1950", "orchestrate_srm1950", "SRM1950"),
        ("lmsd", "orchestrate_lmsd", "LMSD"),
        ("swisslipids", "orchestrate_swisslipids", "SWISSLIPIDS"),
    ],
)
def test_streamed_datasets_route_to_orchestrator_with_pinned_url(monkeypatch, tmp_path, key, orchestrator, config_name):
    """These four accept the URL string directly and stream it, so the suite needs no local file."""
    import studies.external_benchmarks.config as cfg_mod

    calls: dict = {}

    def _fake(**kwargs):
        calls.update(kwargs)
        return {"out_dir": str(tmp_path), "report": "r.md"}

    monkeypatch.setattr(run_mod, orchestrator, _fake)
    run_mod._suite_runners()[key](out_dir=tmp_path, run_gate_first=False)
    assert calls["source"] == getattr(cfg_mod, config_name).source_url
    assert calls["run_gate_first"] is False


def test_nlmgene_routes_through_the_pinned_ftp_corpus_fetch(monkeypatch, tmp_path):
    """nlmgene has no source_url to pass through: the corpus arrives via fetch_corpus()."""
    import studies.external_benchmarks.adapters.nlmgene as nlmgene_adapter

    calls: dict = {}
    # The closure re-imports fetch_corpus at call time, so patching the module attribute takes effect.
    monkeypatch.setattr(nlmgene_adapter, "fetch_corpus", lambda config: [("PMID1", "<xml/>")])

    def _fake(**kwargs):
        calls.update(kwargs)
        return {"out_dir": str(tmp_path), "report": "r.md"}

    monkeypatch.setattr(run_mod, "orchestrate_nlmgene", _fake)
    run_mod._suite_runners()["nlmgene"](out_dir=tmp_path, run_gate_first=False)
    assert list(calls["source"]) == [("PMID1", "<xml/>")]


def test_only_genuinely_unsourceable_datasets_remain_skipped():
    """pham/hajjar/provided-id have no fetchable pinned source; everything else should now run."""
    assert set(run_mod.SUITE_SKIPPED) == {"provided-id", "pham", "hajjar"}


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


# --------------------------------------------------------------------------------------------------
# Per-dataset error / cache counters ride in the suite manifest, reset between datasets.
# --------------------------------------------------------------------------------------------------
def _counting_runner(name, n_requests):
    """A runner that spends requests through the real counter, as an orchestrator would."""

    def _run(out_dir, run_gate_first):
        from biomapper2 import utils

        p = Path(out_dir)
        p.mkdir(parents=True, exist_ok=True)
        for _ in range(n_requests):
            utils._bump("hybrid-search", "requests")
        return {"out_dir": str(p), "report": ""}

    return _run


def test_suite_records_per_dataset_request_counters(tmp_path):
    runners = {"alpha": _counting_runner("alpha", 3), "beta": _counting_runner("beta", 5)}
    result = run_mod.run_suite(
        out_dir=tmp_path, datasets=["alpha", "beta"], runners=runners, run_gate_first=False, probe_live=False
    )
    by_key = {d["dataset"]: d for d in result["manifest"]["datasets"]}
    assert by_key["alpha"]["request_counters"]["hybrid-search"]["requests"] == 3
    assert by_key["beta"]["request_counters"]["hybrid-search"]["requests"] == 5


def test_counters_do_not_accumulate_across_datasets_in_one_process(tmp_path):
    """The whole suite runs in ONE process. Without a per-dataset reset every dataset after the
    first is cumulative, so the second dataset's count would be the sum of both."""
    runners = {"alpha": _counting_runner("alpha", 3), "beta": _counting_runner("beta", 5)}
    result = run_mod.run_suite(
        out_dir=tmp_path, datasets=["alpha", "beta"], runners=runners, run_gate_first=False, probe_live=False
    )
    by_key = {d["dataset"]: d for d in result["manifest"]["datasets"]}
    assert by_key["beta"]["request_counters"]["hybrid-search"]["requests"] != 8


def test_counters_are_recorded_for_a_failing_dataset_too(tmp_path):
    """A dataset that raises is exactly the one whose error counts a reader wants."""

    def _boom(out_dir, run_gate_first):
        from biomapper2 import utils

        utils._bump("hybrid-search", "terminal_5xx")
        raise RuntimeError("no target vocab produced a result")

    result = run_mod.run_suite(
        out_dir=tmp_path,
        datasets=["alpha"],
        runners={"alpha": _boom},
        run_gate_first=False,
        probe_live=False,
    )
    record = result["manifest"]["datasets"][0]
    assert record["status"] == "failed"
    assert record["request_counters"]["hybrid-search"]["terminal_5xx"] == 1


def test_per_arm_status_is_carried_through_when_an_orchestrator_reports_it(tmp_path):
    """One arm of a multi-arm dataset can complete cleanly while another fails, leaving usable
    results on disk under a dataset-level failed status. The record has to be able to say so."""

    def _partial(out_dir, run_gate_first):
        p = Path(out_dir)
        p.mkdir(parents=True, exist_ok=True)
        return {"out_dir": str(p), "report": "", "arm_status": {"positive": "ok", "negative": "failed"}}

    result = run_mod.run_suite(
        out_dir=tmp_path,
        datasets=["alpha"],
        runners={"alpha": _partial},
        run_gate_first=False,
        probe_live=False,
    )
    assert result["manifest"]["datasets"][0]["arm_status"] == {"positive": "ok", "negative": "failed"}
