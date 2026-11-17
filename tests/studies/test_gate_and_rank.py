"""Tests for gate probes, regression set normalizers, runner seeds, and mechanical ranker.

Verifies golden manifest structure, normalization mechanics, seed resolution,
pinned-commit diff calculation, strict completeness validation, and sensitivity stability.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from studies.kestrel_fault_benchmark.gate_probes import ProbeResult
from studies.kestrel_fault_benchmark.rank import (
    MODES,
    PENALTY_SCORE,
    compute_ranking,
    derive_candidate_metrics,
    run_sensitivity_check,
)
from studies.kestrel_fault_benchmark.regression_set import (
    DEFAULT_MANIFEST_PATH,
    normalize_dataset_stats,
    normalize_mapping_response,
)
from studies.kestrel_fault_benchmark.runner import resolve_seeds

DEFAULT_CFG = {"window_s": 20.0, "slow_delay_s": 30.0, "recover_after_s": 120.0}


def _init_git_fixture_repo(repo_dir: Path) -> tuple[str, str, str]:
    """Create a small git repo with base_sha, cand_a_sha (+2 lines), cand_b_sha (+5 lines), then move HEAD."""
    env = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "PATH": "/usr/bin:/bin",
    }
    subprocess.run(["git", "init", "-q"], cwd=repo_dir, env=env, check=True)
    src_file = repo_dir / "src" / "biomapper2" / "mod.py"
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_dir, env=env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo_dir, env=env, check=True)
    base_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_dir).decode().strip()

    src_file.write_text("x = 1\ny = 2\nz = 3\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "cand_a", "-q"], cwd=repo_dir, env=env, check=True)
    cand_a_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_dir).decode().strip()

    src_file.write_text("x = 1\na = 1\nb = 2\nc = 3\nd = 4\ne = 5\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "cand_b", "-q"], cwd=repo_dir, env=env, check=True)
    cand_b_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_dir).decode().strip()

    # Advance HEAD with unrelated 50 lines so tests confirm HEAD movement is ignored
    src_file.write_text("\n".join(f"line_{i} = {i}" for i in range(50)) + "\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "later_head", "-q"], cwd=repo_dir, env=env, check=True)
    return base_sha, cand_a_sha, cand_b_sha


def _make_run(
    candidate: str,
    git_sha: str,
    mode: str,
    seed: int = 101,
    health_p99_ms: float = 12.0,
    non_kestrel_rps: float = 80.0,
    time_to_recover_s: float | None = 4.0,
    recovered: bool | None = True,
    health_ok_count: int = 20,
    health_total_count: int = 20,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "candidate": candidate,
        "git_sha": git_sha,
        "mode": mode,
        "seed": seed,
        "config": dict(config or DEFAULT_CFG),
        "health_p99_ms": health_p99_ms,
        "health_ok_count": health_ok_count,
        "health_total_count": health_total_count,
        "non_kestrel_rps": non_kestrel_rps,
        "recovered": recovered if mode == "recovering" else None,
        "time_to_recover_s": time_to_recover_s if mode == "recovering" else None,
    }


def test_golden_manifest_structure_and_hashes() -> None:
    """golden_healthy_manifest.json exists, contains 35 checks, and pins suite_sha256."""
    assert DEFAULT_MANIFEST_PATH.exists()
    with open(DEFAULT_MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("check_count") == 35
    assert len(data.get("checks", {})) == 35
    assert len(data.get("suite_sha256", "")) == 64


def test_regression_set_normalization() -> None:
    """Dynamic timing, UUID, and filesystem paths are properly zeroed/normalized."""
    raw_api_resp = {
        "result": {"name": "test"},
        "metadata": {"request_id": "1234-abcd-5678", "processing_time_ms": 42.5},
    }
    norm_api = normalize_mapping_response(raw_api_resp)
    assert norm_api["metadata"]["request_id"] == "00000000-0000-0000-0000-000000000000"
    assert norm_api["metadata"]["processing_time_ms"] == 0.0

    raw_stats = {
        "mapped_dataset": "/tmp/custom_path/dataset_MAPPED.tsv",
        "run_provenance": {"run_timestamp": "2026-11-16T12:00:00Z"},
    }
    norm_stats = normalize_dataset_stats(raw_stats)
    assert norm_stats["mapped_dataset"] == "MAPPED_DATASET_NORMALIZED"
    assert norm_stats["run_provenance"]["run_timestamp"] == "1970-01-01T00:00:00+00:00"


def test_probe_result_and_runner_seed_resolution() -> None:
    """ProbeResult transitions cleanly and resolve_seeds honors --repeats and --seeds."""
    probe = ProbeResult("3a", "reports error on fault")
    assert probe.verdict == "fail"
    probe.mark_pass("all 4 paths reported error", evidence={"paths_checked": 4})
    assert probe.to_dict()["verdict"] == "pass"

    assert resolve_seeds(None, None) == [101]
    assert resolve_seeds(3, None) == [101, 202, 303]
    assert resolve_seeds(None, "11,22") == [11, 22]
    assert resolve_seeds(2, "11,22,33") == [11, 22]
    with pytest.raises(ValueError, match="requires at least 3 seeds"):
        resolve_seeds(3, "101")


def test_rank_mechanical_metric_derivation_and_pinned_git_sha() -> None:
    """derive_candidate_metrics uses pinned git_sha rather than moving worktree HEAD."""
    with tempfile.TemporaryDirectory() as repo_str:
        repo = Path(repo_str)
        base_sha, cand_a_sha, _ = _init_git_fixture_repo(repo)
        runs = [
            _make_run(
                "cand_a",
                cand_a_sha,
                m,
                health_p99_ms=40.1 if m == "recovering" else 10.2,
                non_kestrel_rps=85.0 if m == "hang" else 100.0,
                time_to_recover_s=5.2,
            )
            for m in MODES
        ]
        m = derive_candidate_metrics(runs, repo, base_sha)
        assert m["candidate"] == "cand_a"
        assert m["worst_health_p99_ms"] == 40.1
        assert m["hang_non_kestrel_rps"] == 85.0
        assert m["max_time_to_recover_s"] == 5.2
        assert m["src_diff_lines"] == 2


def test_rank_validation_rejects_incomplete_or_broken_runs() -> None:
    """Missing modes, missing recovery times, mixed commits, or invalid worktrees fail loudly."""
    with tempfile.TemporaryDirectory() as repo_str:
        repo = Path(repo_str)
        base_sha, cand_a_sha, cand_b_sha = _init_git_fixture_repo(repo)
        full_runs = [_make_run("cand_a", cand_a_sha, m) for m in MODES]

        # Missing mode fails
        with pytest.raises(ValueError, match="missing required mode"):
            derive_candidate_metrics(full_runs[:-1], repo, base_sha)

        # Missing worktree fails instead of returning src_diff_lines=0
        with pytest.raises(ValueError, match="Valid candidate worktree"):
            derive_candidate_metrics(full_runs, repo / "nonexistent", base_sha)

        # Mixed git_sha fails
        mixed = list(full_runs)
        mixed[0] = _make_run("cand_a", cand_b_sha, MODES[0])
        with pytest.raises(ValueError, match="mixed git_sha"):
            derive_candidate_metrics(mixed, repo, base_sha)

        # Null time_to_recover_s without recovered=False fails
        bad_rec = [_make_run("cand_a", cand_a_sha, m, time_to_recover_s=None, recovered=True) for m in MODES]
        with pytest.raises(ValueError, match="missing valid time_to_recover_s"):
            derive_candidate_metrics(bad_rec, repo, base_sha)

        # Explicit unrecovered or failed health probe receives PENALTY_SCORE, never 0
        penalized = [
            _make_run("cand_a", cand_a_sha, m, time_to_recover_s=None, recovered=False, health_ok_count=19)
            for m in MODES
        ]
        pm = derive_candidate_metrics(penalized, repo, base_sha)
        assert pm["max_time_to_recover_s"] == PENALTY_SCORE
        assert pm["worst_health_p99_ms"] == PENALTY_SCORE


def test_rank_sensitivity_analysis_stable() -> None:
    """Sensitivity analysis confirms stability when rank 1 leads across all subsets."""
    with tempfile.TemporaryDirectory() as tmp_dir, tempfile.TemporaryDirectory() as repo_str:
        repo = Path(repo_str)
        base_sha, cand_a_sha, cand_b_sha = _init_git_fixture_repo(repo)
        bench_root = Path(tmp_dir)
        for mode in MODES:
            for seed in [101, 202]:
                da = bench_root / f"run_a_{mode}_{seed}"
                da.mkdir()
                (da / "summary.json").write_text(
                    json.dumps(
                        _make_run(
                            "cand_a",
                            cand_a_sha,
                            mode,
                            seed=seed,
                            health_p99_ms=12.0,
                            non_kestrel_rps=80.0,
                            time_to_recover_s=4.0,
                        )
                    )
                )
                db = bench_root / f"run_b_{mode}_{seed}"
                db.mkdir()
                (db / "summary.json").write_text(
                    json.dumps(
                        _make_run(
                            "cand_b",
                            cand_b_sha,
                            mode,
                            seed=seed,
                            health_p99_ms=95.0,
                            non_kestrel_rps=20.0,
                            time_to_recover_s=25.0,
                        )
                    )
                )

        wts = {"cand_a": repo, "cand_b": repo}
        ranking = compute_ranking(bench_root, base_sha, wts)
        assert ranking[0]["candidate"] == "cand_a"
        stable, per_dropped = run_sensitivity_check(bench_root, base_sha, wts, "cand_a")
        assert stable is True
        assert all(leader == "cand_a" for leader in per_dropped.values())


def test_rank_sensitivity_analysis_unstable() -> None:
    """Sensitivity analysis flags instability if dropping a mode flips the leader."""
    with tempfile.TemporaryDirectory() as tmp_dir, tempfile.TemporaryDirectory() as repo_str:
        repo = Path(repo_str)
        base_sha, cand_a_sha, cand_b_sha = _init_git_fixture_repo(repo)
        bench_root = Path(tmp_dir)
        for mode in MODES:
            da = bench_root / f"run_a_{mode}"
            da.mkdir()
            db = bench_root / f"run_b_{mode}"
            db.mkdir()
            p99_a = 500.0 if mode == "recovering" else 15.0
            p99_b = 30.0 if mode == "recovering" else 20.0
            (da / "summary.json").write_text(
                json.dumps(_make_run("cand_a", cand_a_sha, mode, health_p99_ms=p99_a, non_kestrel_rps=50.0))
            )
            (db / "summary.json").write_text(
                json.dumps(_make_run("cand_b", cand_b_sha, mode, health_p99_ms=p99_b, non_kestrel_rps=50.0))
            )

        wts = {"cand_a": repo, "cand_b": repo}
        ranking = compute_ranking(bench_root, base_sha, wts)
        assert ranking[0]["candidate"] == "cand_b"
        stable, per_dropped = run_sensitivity_check(bench_root, base_sha, wts, "cand_b")
        assert stable is False
        assert per_dropped["recovering"] == "cand_a"


def test_rank_cli_rejects_same_out_and_verify() -> None:
    """CLI rejects identical --out and --verify paths without overwriting evidence."""
    with tempfile.TemporaryDirectory() as tmp_dir, tempfile.TemporaryDirectory() as repo_str:
        repo = Path(repo_str)
        base_sha, cand_a_sha, _ = _init_git_fixture_repo(repo)
        bench_root = Path(tmp_dir) / "runs"
        for mode in MODES:
            d = bench_root / f"a_{mode}"
            d.mkdir(parents=True)
            (d / "summary.json").write_text(json.dumps(_make_run("cand_a", cand_a_sha, mode)))

        artifact = Path(tmp_dir) / "ranking.json"
        artifact.write_text('{"tampered": true}', encoding="utf-8")

        rank_script = Path(__file__).resolve().parents[2] / "studies" / "kestrel_fault_benchmark" / "rank.py"
        proc = subprocess.run(
            [
                sys.executable,
                str(rank_script),
                str(bench_root),
                "--shared-base-sha",
                base_sha,
                "--worktrees",
                f"cand_a={repo}",
                "--out",
                str(artifact),
                "--verify",
                str(artifact),
            ],
            capture_output=True,
            text=True,
        )
        assert proc.returncode != 0
        assert json.loads(artifact.read_text(encoding="utf-8")) == {"tampered": True}
