"""Benchmark runner for Kestrel fault isolation competition.

Executes concurrent load (Kestrel mapping, health probes, non-Kestrel queries)
against a candidate API process paired with Fake Kestrel across the 5 fault modes.
Records thread counts, latency percentiles, throughput, and recovery times.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

ALL_MODES = ["healthy", "slow-30s", "hang", "50% 5xx", "recovering"]
DEFAULT_SEEDS = [101, 202, 303]


def percentile(data: list[float], p: float) -> float:
    """Calculate percentile p (0.0 - 1.0) with linear interpolation."""
    if not data:
        return 0.0
    s = sorted(data)
    idx = (len(s) - 1) * p
    low = math.floor(idx)
    high = math.ceil(idx)
    if low == high:
        return s[int(idx)]
    d = idx - low
    return s[low] * (1.0 - d) + s[high] * d


def get_process_threads(pid: int) -> int:
    """Read thread count from /proc/<pid>/status under Linux."""
    try:
        status_path = Path(f"/proc/{pid}/status")
        if status_path.exists():
            for line in status_path.read_text().splitlines():
                if line.startswith("Threads:"):
                    return int(line.split()[1])
    except Exception:
        pass
    return 0


def get_git_info(worktree_path: Path) -> tuple[str, bool]:
    """Retrieve git HEAD SHA and dirty status for candidate worktree."""
    try:
        sha = (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=worktree_path,
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
        status = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=worktree_path,
            stderr=subprocess.DEVNULL,
        ).decode()
        return sha, len(status.strip()) > 0
    except Exception:
        return "unknown", False


async def run_benchmark_run(
    candidate: str,
    worktree: Path,
    mode: str,
    seed: int,
    kestrel_port: int = 18100,
    api_port: int = 18101,
    out_root: Path | None = None,
    window_s: float = 20.0,
    slow_delay_s: float = 30.0,
    recover_after_s: float = 120.0,
) -> dict[str, Any]:
    """Execute a single benchmark run under specified mode and seed."""
    if out_root is None:
        out_root = worktree / "results" / "benchmark"
    out_root.mkdir(parents=True, exist_ok=True)

    mode_slug = mode.replace(" ", "_").replace("%", "pct")
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bench_dir = out_root / f"{timestamp_str}_{candidate}_{mode_slug}_s{seed}"
    bench_dir.mkdir(parents=True, exist_ok=True)

    git_sha, git_dirty = get_git_info(worktree)
    cache_dir = Path(tempfile.mkdtemp(prefix=f"cache_{candidate}_{mode_slug}_s{seed}_"))

    log_fk_path = bench_dir / "fake_kestrel.log"
    log_api_path = bench_dir / "api.log"
    log_fk = open(log_fk_path, "w")
    log_api = open(log_api_path, "w")

    python_bin = worktree / ".venv" / "bin" / "python"
    uvicorn_bin = worktree / ".venv" / "bin" / "uvicorn"
    if not python_bin.exists():
        python_bin = Path(sys.executable)
    if not uvicorn_bin.exists():
        uvicorn_bin = python_bin

    # 1. Launch Fake Kestrel
    fk_env = os.environ.copy()
    fk_cmd = [
        str(python_bin),
        "-m",
        "studies.kestrel_fault_benchmark.fake_kestrel",
        "--port",
        str(kestrel_port),
        "--mode",
        mode,
        "--seed",
        str(seed),
        "--slow-delay-s",
        str(slow_delay_s),
        "--recover-after-s",
        str(recover_after_s),
    ]
    fk_proc = subprocess.Popen(fk_cmd, cwd=worktree, env=fk_env, stdout=log_fk, stderr=log_fk)

    # 2. Launch Candidate API
    api_env = os.environ.copy()
    api_env["KESTREL_API_URL"] = f"http://127.0.0.1:{kestrel_port}"
    api_env["BIOMAPPER2_CACHE_DIR"] = str(cache_dir)
    api_env["REFMET_SNAPSHOT_PATH"] = str(
        (worktree / "studies" / "kestrel_fault_benchmark" / "fixtures" / "refmet_regression_freeze.tsv").resolve()
    )
    api_env["REFMET_FREEZE_MODE"] = "frozen"
    api_env["REFMET_LIVE_API_FALLBACK"] = "0"
    api_env["BIOMAPPER2_TIER_B_ENABLED"] = "0"

    api_cmd = [
        str(uvicorn_bin),
        "biomapper2.api.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(api_port),
        "--workers",
        "1",
    ]
    api_proc = subprocess.Popen(api_cmd, cwd=worktree, env=api_env, stdout=log_api, stderr=log_api)

    health_latencies: list[float] = []
    health_ok_count = 0
    health_total_count = 0
    non_kestrel_latencies: list[float] = []
    non_kestrel_completed = 0
    kestrel_completed = 0
    kestrel_errored = 0
    time_to_recover_s: float | None = None

    try:
        # Wait for Fake Kestrel
        async with httpx.AsyncClient() as client:
            for _ in range(50):
                try:
                    r = await client.get(f"http://127.0.0.1:{kestrel_port}/health", timeout=1.0)
                    if r.status_code == 200:
                        break
                except Exception:
                    await asyncio.sleep(0.1)

            for _ in range(150):
                try:
                    r = await client.get(f"http://127.0.0.1:{api_port}/api/v1/health", timeout=1.0)
                    if r.status_code == 200 and r.json().get("mapper_initialized"):
                        break
                except Exception:
                    await asyncio.sleep(0.1)

        threads_before = get_process_threads(api_proc.pid)

        # Workload loops
        async def health_probe_worker(stop_event: asyncio.Event) -> None:
            nonlocal health_ok_count, health_total_count
            async with httpx.AsyncClient() as client:
                while not stop_event.is_set():
                    t0 = time.monotonic()
                    try:
                        r = await client.get(f"http://127.0.0.1:{api_port}/api/v1/health", timeout=5.0)
                        dur_ms = (time.monotonic() - t0) * 1000.0
                        health_latencies.append(dur_ms)
                        health_total_count += 1
                        if r.status_code == 200:
                            health_ok_count += 1
                    except Exception:
                        dur_ms = (time.monotonic() - t0) * 1000.0
                        health_latencies.append(dur_ms)
                        health_total_count += 1
                    await asyncio.sleep(0.25)

        async def non_kestrel_worker(stop_event: asyncio.Event, worker_id: int) -> None:
            nonlocal non_kestrel_completed
            endpoints = ["entity-types", "annotators", "vocabularies"]
            ep = endpoints[worker_id % len(endpoints)]
            async with httpx.AsyncClient() as client:
                while not stop_event.is_set():
                    t0 = time.monotonic()
                    try:
                        r = await client.get(f"http://127.0.0.1:{api_port}/api/v1/{ep}", timeout=5.0)
                        dur_ms = (time.monotonic() - t0) * 1000.0
                        if r.status_code == 200:
                            non_kestrel_latencies.append(dur_ms)
                            non_kestrel_completed += 1
                    except Exception:
                        pass
                    await asyncio.sleep(0.05)

        async def kestrel_mapping_worker(stop_event: asyncio.Event, worker_id: int) -> None:
            nonlocal kestrel_completed, kestrel_errored
            names = ["leukemia", "heart attack", "isoleucine", "glucose", "TNFRSF1A"]
            name = names[worker_id % len(names)]
            payload = {"name": name, "entity_type": "disease" if "attack" in name or "leuk" in name else "metabolite"}
            async with httpx.AsyncClient() as client:
                while not stop_event.is_set():
                    try:
                        r = await client.post(
                            f"http://127.0.0.1:{api_port}/api/v1/map/entity",
                            json=payload,
                            timeout=60.0,
                        )
                        if r.status_code == 200:
                            data = r.json()
                            if data.get("result", {}).get("error"):
                                kestrel_errored += 1
                            else:
                                kestrel_completed += 1
                        else:
                            kestrel_errored += 1
                    except Exception:
                        kestrel_errored += 1
                    await asyncio.sleep(0.1)

        stop_load = asyncio.Event()

        # Run window
        run_duration = recover_after_s + 60.0 if mode == "recovering" else window_s
        workers = [
            asyncio.create_task(health_probe_worker(stop_load)),
            *(asyncio.create_task(non_kestrel_worker(stop_load, i)) for i in range(4)),
            *(asyncio.create_task(kestrel_mapping_worker(stop_load, i)) for i in range(8)),
        ]

        if mode == "recovering":
            # In recovering mode: wait until recover_after_s, then measure time_to_recover_s
            await asyncio.sleep(recover_after_s)
            flip_time = time.monotonic()
            # Probe until recovery is observed (health check < 1.0s and successful mapping)
            recovered = False
            async with httpx.AsyncClient() as probe_client:
                while time.monotonic() - flip_time < 75.0:
                    try:
                        t0 = time.monotonic()
                        hr = await probe_client.get(f"http://127.0.0.1:{api_port}/api/v1/health", timeout=2.0)
                        h_ms = (time.monotonic() - t0) * 1000.0
                        mr = await probe_client.post(
                            f"http://127.0.0.1:{api_port}/api/v1/map/entity",
                            json={"name": "leukemia", "entity_type": "disease"},
                            timeout=5.0,
                        )
                        if hr.status_code == 200 and h_ms < 1000.0 and mr.status_code == 200:
                            res_json = mr.json().get("result", {})
                            if res_json.get("chosen_kg_id") and not res_json.get("error"):
                                time_to_recover_s = round(time.monotonic() - flip_time, 2)
                                recovered = True
                                break
                    except Exception:
                        pass
                    await asyncio.sleep(0.5)
            if not recovered:
                time_to_recover_s = 75.0
            await asyncio.sleep(5.0)
        else:
            await asyncio.sleep(run_duration)

        stop_load.set()
        await asyncio.gather(*workers, return_exceptions=True)

        threads_after = get_process_threads(api_proc.pid)
        threads_delta = threads_after - threads_before

    finally:
        api_proc.terminate()
        fk_proc.terminate()
        try:
            api_proc.wait(timeout=5)
        except Exception:
            api_proc.kill()
        try:
            fk_proc.wait(timeout=5)
        except Exception:
            fk_proc.kill()
        log_fk.close()
        log_api.close()
        shutil.rmtree(cache_dir, ignore_errors=True)

    duration_actual = window_s if mode != "recovering" else (recover_after_s + 60.0)
    non_kestrel_rps = round(non_kestrel_completed / max(1.0, duration_actual), 1)

    summary: dict[str, Any] = {
        "candidate": candidate,
        "mode": mode,
        "seed": seed,
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        "threads_before": threads_before,
        "threads_after": threads_after,
        "threads_delta": threads_delta,
        "health_p50_ms": round(percentile(health_latencies, 0.50), 1),
        "health_p95_ms": round(percentile(health_latencies, 0.95), 1),
        "health_p99_ms": round(percentile(health_latencies, 0.99), 1),
        "health_max_ms": round(max(health_latencies) if health_latencies else 0.0, 1),
        "health_ok_count": health_ok_count,
        "health_total_count": health_total_count,
        "non_kestrel_p50_ms": round(percentile(non_kestrel_latencies, 0.50), 1),
        "non_kestrel_p95_ms": round(percentile(non_kestrel_latencies, 0.95), 1),
        "non_kestrel_rps": non_kestrel_rps,
        "kestrel_requests_completed": kestrel_completed,
        "kestrel_requests_errored": kestrel_errored,
        "time_to_recover_s": time_to_recover_s,
    }

    summary_path = bench_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"BENCHMARK_DIR={bench_dir}")
    return summary


def main() -> None:
    """CLI entrypoint for benchmark runner."""
    parser = argparse.ArgumentParser(description="BioMapper2 Kestrel Fault Benchmark Runner")
    parser.add_argument("--candidate", required=True, help="Candidate name (e.g. shared-base, team-a)")
    parser.add_argument("--mode", default="healthy", help="Fault mode (healthy|slow-30s|hang|50% 5xx|recovering|all)")
    parser.add_argument("--repeats", type=int, default=1, help="Number of repeats per mode")
    parser.add_argument("--seeds", default="101", help="Comma-separated random seeds (e.g. 101,202,303)")
    parser.add_argument("--kestrel-port", type=int, default=18100, help="Fake Kestrel port")
    parser.add_argument("--api-port", type=int, default=18101, help="Candidate API port")
    parser.add_argument("--out-root", default=None, help="Root directory for benchmark outputs")
    parser.add_argument("--worktree", default=".", help="Candidate worktree root path")
    parser.add_argument("--window-s", type=float, default=20.0, help="Duration of benchmark load window")
    parser.add_argument("--slow-delay-s", type=float, default=30.0, help="Delay for slow-30s in seconds")
    parser.add_argument("--recover-after-s", type=float, default=120.0, help="Recovery delay in seconds")
    args = parser.parse_args()

    worktree = Path(args.worktree).resolve()
    out_root = Path(args.out_root).resolve() if args.out_root else worktree / "results" / "benchmark"
    seeds = [int(s.strip()) for s in args.seeds.split(",") if s.strip()]

    modes_to_run = ALL_MODES if args.mode == "all" else [args.mode]

    for mode in modes_to_run:
        for seed in seeds[: args.repeats]:
            res = asyncio.run(
                run_benchmark_run(
                    candidate=args.candidate,
                    worktree=worktree,
                    mode=mode,
                    seed=seed,
                    kestrel_port=args.kestrel_port,
                    api_port=args.api_port,
                    out_root=out_root,
                    window_s=args.window_s,
                    slow_delay_s=args.slow_delay_s,
                    recover_after_s=args.recover_after_s,
                )
            )
            print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
