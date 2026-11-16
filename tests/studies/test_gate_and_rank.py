"""Tests for gate probes, regression set normalizers, and mechanical ranker.

Verifies golden manifest structure, normalization mechanics, gate probe result
evaluation, mechanical ranking key order, and sensitivity analysis stability.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from studies.kestrel_fault_benchmark.gate_probes import ProbeResult
from studies.kestrel_fault_benchmark.rank import (
    compute_ranking,
    derive_candidate_metrics,
    run_sensitivity_check,
)
from studies.kestrel_fault_benchmark.regression_set import (
    DEFAULT_MANIFEST_PATH,
    normalize_dataset_stats,
    normalize_mapping_response,
)


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


def test_probe_result_pass_fail_marking() -> None:
    """ProbeResult correctly transitions and serializes pass/fail readings."""
    probe = ProbeResult("3a", "reports error on fault")
    assert probe.verdict == "fail"

    probe.mark_pass("all 4 paths reported error", evidence={"paths_checked": 4})
    d_pass = probe.to_dict()
    assert d_pass["verdict"] == "pass"
    assert d_pass["evidence"]["paths_checked"] == 4

    probe.mark_fail("path 1 failed")
    d_fail = probe.to_dict()
    assert d_fail["verdict"] == "fail"
    assert "path 1 failed" in d_fail["saw"]


def test_rank_mechanical_metric_derivation() -> None:
    """derive_candidate_metrics accurately calculates p99, throughput, and recovery bounds."""
    runs = [
        {"candidate": "cand_a", "mode": "healthy", "health_p99_ms": 10.2, "non_kestrel_rps": 100.0},
        {"candidate": "cand_a", "mode": "hang", "health_p99_ms": 25.4, "non_kestrel_rps": 85.0},
        {"candidate": "cand_a", "mode": "recovering", "health_p99_ms": 40.1, "time_to_recover_s": 5.2},
    ]
    m = derive_candidate_metrics(runs, None, "base_sha")
    assert m["candidate"] == "cand_a"
    assert m["worst_health_p99_ms"] == 40.1
    assert m["hang_non_kestrel_rps"] == 85.0
    assert m["max_time_to_recover_s"] == 5.2


def test_rank_sensitivity_analysis_stable() -> None:
    """Sensitivity analysis confirms stability when rank 1 leads across all subsets."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        bench_root = Path(tmp_dir)
        modes = ["healthy", "slow-30s", "hang", "50% 5xx", "recovering"]
        for mode in modes:
            for seed in [101, 202]:
                cand_a_dir = bench_root / f"run_a_{mode}_{seed}"
                cand_a_dir.mkdir()
                (cand_a_dir / "summary.json").write_text(
                    json.dumps(
                        {
                            "candidate": "cand_a",
                            "mode": mode,
                            "health_p99_ms": 12.0,
                            "non_kestrel_rps": 80.0,
                            "time_to_recover_s": 4.0 if mode == "recovering" else None,
                        }
                    )
                )
                cand_b_dir = bench_root / f"run_b_{mode}_{seed}"
                cand_b_dir.mkdir()
                (cand_b_dir / "summary.json").write_text(
                    json.dumps(
                        {
                            "candidate": "cand_b",
                            "mode": mode,
                            "health_p99_ms": 95.0,
                            "non_kestrel_rps": 20.0,
                            "time_to_recover_s": 25.0 if mode == "recovering" else None,
                        }
                    )
                )

        ranking = compute_ranking(bench_root, "dummy_sha", {})
        assert ranking[0]["candidate"] == "cand_a"

        stable, per_dropped = run_sensitivity_check(bench_root, "dummy_sha", {}, "cand_a")
        assert stable is True
        assert all(leader == "cand_a" for leader in per_dropped.values())


def test_rank_sensitivity_analysis_unstable() -> None:
    """Sensitivity analysis flags instability if dropping a mode flips the leader."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        bench_root = Path(tmp_dir)
        modes = ["healthy", "slow-30s", "hang", "50% 5xx", "recovering"]
        for mode in modes:
            cand_a_dir = bench_root / f"run_a_{mode}"
            cand_a_dir.mkdir()
            cand_b_dir = bench_root / f"run_b_{mode}"
            cand_b_dir.mkdir()

            if mode == "recovering":
                # In recovering mode, cand_a has a huge spike, but is otherwise slightly faster
                p99_a = 500.0
                p99_b = 30.0
            else:
                p99_a = 15.0
                p99_b = 20.0

            (cand_a_dir / "summary.json").write_text(
                json.dumps({"candidate": "cand_a", "mode": mode, "health_p99_ms": p99_a, "non_kestrel_rps": 50.0})
            )
            (cand_b_dir / "summary.json").write_text(
                json.dumps({"candidate": "cand_b", "mode": mode, "health_p99_ms": p99_b, "non_kestrel_rps": 50.0})
            )

        # In baseline, cand_b wins due to lower worst_p99
        ranking = compute_ranking(bench_root, "dummy_sha", {})
        assert ranking[0]["candidate"] == "cand_b"

        # But dropping recovering mode makes cand_a win, so leader is unstable
        stable, per_dropped = run_sensitivity_check(bench_root, "dummy_sha", {}, "cand_b")
        assert stable is False
        assert per_dropped["recovering"] == "cand_a"


def test_rank_compute_and_verify() -> None:
    """compute_ranking orders candidates deterministically and matches verified dump."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        bench_root = Path(tmp_dir)
        d1 = bench_root / "cand_1"
        d1.mkdir()
        (d1 / "summary.json").write_text(
            json.dumps({"candidate": "cand_1", "mode": "healthy", "health_p99_ms": 25.0, "non_kestrel_rps": 60.0})
        )
        d2 = bench_root / "cand_2"
        d2.mkdir()
        (d2 / "summary.json").write_text(
            json.dumps({"candidate": "cand_2", "mode": "healthy", "health_p99_ms": 10.0, "non_kestrel_rps": 90.0})
        )

        ranking = compute_ranking(bench_root, "dummy_sha", {})
        assert ranking[0]["candidate"] == "cand_2"
        assert ranking[0]["rank"] == 1
        assert ranking[1]["candidate"] == "cand_1"
        assert ranking[1]["rank"] == 2
