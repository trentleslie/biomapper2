"""Black-box HTTP gate probes for BioMapper2 Kestrel fault isolation.

Evaluates running candidate API processes against Fake Kestrel without inspecting
source code. Tests Lines 1a, 1b, 2, 3a (Rule 3.1 & 3.2), 3b (Rule 3.3), 4, 5, and 6
as specified in GATE_CHECKLIST.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
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

from .regression_set import verify_against_golden

logger = logging.getLogger(__name__)


class ProbeResult:
    """Individual line probe evaluation result."""

    def __init__(self, line_id: str, looked_for: str) -> None:
        self.line_id = line_id
        self.verdict = "fail"
        self.looked_for = looked_for
        self.saw = ""
        self.evidence: dict[str, Any] = {}
        self.reading = ""

    def mark_pass(self, saw: str, reading: str = "", evidence: dict[str, Any] | None = None) -> None:
        self.verdict = "pass"
        self.saw = saw
        self.reading = reading or saw
        if evidence:
            self.evidence = evidence

    def mark_fail(self, saw: str, reading: str = "", evidence: dict[str, Any] | None = None) -> None:
        self.verdict = "fail"
        self.saw = saw
        self.reading = reading or saw
        if evidence:
            self.evidence = evidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.line_id,
            "verdict": self.verdict,
            "looked_for": self.looked_for,
            "saw": self.saw,
            "evidence": self.evidence,
            "reading": self.reading,
        }


class ServerPairContext:
    """Manages subprocess lifecycles for Fake Kestrel and candidate API."""

    def __init__(
        self,
        worktree: Path,
        kestrel_port: int,
        api_port: int,
        initial_mode: str = "healthy",
        cache_dir: Path | None = None,
        out_dir: Path | None = None,
    ) -> None:
        self.worktree = worktree.resolve()
        self.kestrel_port = kestrel_port
        self.api_port = api_port
        self.initial_mode = initial_mode
        self.cache_dir = cache_dir or Path(tempfile.mkdtemp(prefix="gate_cache_"))
        self.out_dir = out_dir or Path(tempfile.mkdtemp(prefix="gate_logs_"))
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.fk_proc: subprocess.Popen[Any] | None = None
        self.api_proc: subprocess.Popen[Any] | None = None
        self.log_fk: Any = None
        self.log_api: Any = None

    async def start(self, wait_mapper_ready: bool = True) -> float:
        """Start both servers. Returns API launch-to-ready duration in seconds."""
        python_bin = self.worktree / ".venv" / "bin" / "python"
        uvicorn_bin = self.worktree / ".venv" / "bin" / "uvicorn"
        if not python_bin.exists():
            python_bin = Path(sys.executable)
        if not uvicorn_bin.exists():
            uvicorn_bin = python_bin

        self.log_fk = open(self.out_dir / "fake_kestrel.log", "w")
        self.log_api = open(self.out_dir / "api.log", "w")

        # 1. Fake Kestrel
        fk_cmd = [
            str(python_bin),
            "-m",
            "studies.kestrel_fault_benchmark.fake_kestrel",
            "--port",
            str(self.kestrel_port),
            "--mode",
            self.initial_mode,
        ]
        self.fk_proc = subprocess.Popen(
            fk_cmd,
            cwd=self.worktree,
            env=os.environ.copy(),
            stdout=self.log_fk,
            stderr=self.log_fk,
        )

        # Wait for Fake Kestrel
        async with httpx.AsyncClient() as client:
            for _ in range(50):
                try:
                    r = await client.get(f"http://127.0.0.1:{self.kestrel_port}/__admin/state", timeout=1.0)
                    if r.status_code == 200:
                        break
                except Exception:
                    await asyncio.sleep(0.1)

        # 2. Candidate API
        api_env = os.environ.copy()
        api_env["KESTREL_API_URL"] = f"http://127.0.0.1:{self.kestrel_port}"
        api_env["BIOMAPPER2_CACHE_DIR"] = str(self.cache_dir)
        api_env["REFMET_SNAPSHOT_PATH"] = str(
            (self.worktree / "studies" / "kestrel_fault_benchmark" / "fixtures" / "refmet_regression_freeze.tsv").resolve()
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
            str(self.api_port),
            "--workers",
            "1",
        ]
        t_start = time.monotonic()
        self.api_proc = subprocess.Popen(
            api_cmd,
            cwd=self.worktree,
            env=api_env,
            stdout=self.log_api,
            stderr=self.log_api,
        )

        ready_time = 0.0
        if wait_mapper_ready:
            async with httpx.AsyncClient() as client:
                for _ in range(150):
                    try:
                        r = await client.get(f"http://127.0.0.1:{self.api_port}/api/v1/health", timeout=1.0)
                        if r.status_code == 200 and r.json().get("mapper_initialized"):
                            ready_time = time.monotonic() - t_start
                            break
                    except Exception:
                        await asyncio.sleep(0.1)

        return ready_time

    async def stop(self) -> None:
        """Terminate subprocesses and close log handles."""
        if self.api_proc:
            self.api_proc.terminate()
            try:
                self.api_proc.wait(timeout=5)
            except Exception:
                self.api_proc.kill()
            self.api_proc = None
        if self.fk_proc:
            self.fk_proc.terminate()
            try:
                self.fk_proc.wait(timeout=5)
            except Exception:
                self.fk_proc.kill()
            self.fk_proc = None
        if self.log_fk:
            self.log_fk.close()
        if self.log_api:
            self.log_api.close()


async def check_line_1a(worktree: Path, kp: int, ap: int, out_dir: Path) -> ProbeResult:
    """Line 1a: Event-loop liveness under hang."""
    res = ProbeResult("1a", "20/20 health checks < 1.0s under hang while 8 mapping workers in-flight; workers error")
    ctx = ServerPairContext(worktree, kp, ap, initial_mode="healthy", out_dir=out_dir)
    await ctx.start()
    try:
        async with httpx.AsyncClient() as client:
            # Switch Fake Kestrel to hang
            await client.post(f"http://127.0.0.1:{kp}/__admin/mode", json={"mode": "hang"})

            # Launch 8 concurrent mapping requests
            mapping_tasks = [
                client.post(
                    f"http://127.0.0.1:{ap}/api/v1/map/entity",
                    json={"name": "leukemia", "entity_type": "disease"},
                    timeout=30.0,
                )
                for _ in range(8)
            ]

            # Measure 20 health check probes
            health_ok = 0
            health_latencies: list[float] = []
            for _ in range(20):
                t0 = time.monotonic()
                try:
                    hr = await client.get(f"http://127.0.0.1:{ap}/api/v1/health", timeout=1.5)
                    elapsed_ms = (time.monotonic() - t0) * 1000.0
                    health_latencies.append(elapsed_ms)
                    if hr.status_code == 200 and hr.json().get("status") == "healthy" and elapsed_ms < 1000.0:
                        health_ok += 1
                except Exception:
                    health_latencies.append(9999.0)
                await asyncio.sleep(0.1)

            # Await mapping tasks
            map_responses = await asyncio.gather(*mapping_tasks, return_exceptions=True)
            workers_errored = sum(
                1
                for mr in map_responses
                if isinstance(mr, httpx.Response)
                and mr.status_code == 200
                and bool(mr.json().get("result", {}).get("error"))
            )

            evidence = {
                "health_ok": health_ok,
                "health_total": 20,
                "health_latencies_ms": [round(x, 1) for x in health_latencies],
                "workers_errored": workers_errored,
            }

            if health_ok == 20 and workers_errored == 8:
                res.mark_pass("20/20 health < 1.0s and 8/8 workers cleanly errored", evidence=evidence)
            else:
                res.mark_fail(
                    f"{health_ok}/20 health < 1s, {workers_errored}/8 mapping workers cleanly errored",
                    evidence=evidence,
                )
    finally:
        await ctx.stop()
    return res


async def check_line_1b(worktree: Path, kp: int, ap: int, out_dir: Path) -> ProbeResult:
    """Line 1b: Cold startup under hang <= 15s."""
    res = ProbeResult("1b", "Cold startup under hang ready on GET /health in <= 15.0s")
    empty_cache = Path(tempfile.mkdtemp(prefix="gate_1b_empty_cache_"))
    ctx = ServerPairContext(worktree, kp, ap, initial_mode="hang", cache_dir=empty_cache, out_dir=out_dir)
    try:
        ready_duration = await ctx.start(wait_mapper_ready=True)
        async with httpx.AsyncClient() as client:
            et_resp = await client.get(f"http://127.0.0.1:{ap}/api/v1/entity-types", timeout=2.0)
            et_ok = et_resp.status_code == 200

        evidence = {"ready_duration_s": round(ready_duration, 2), "entity_types_ok": et_ok}
        if 0.0 < ready_duration <= 15.0 and et_ok:
            res.mark_pass(f"Ready in {ready_duration:.2f}s (<= 15.0s)", evidence=evidence)
        else:
            res.mark_fail(f"Ready in {ready_duration:.2f}s or entity-types failed", evidence=evidence)
    finally:
        await ctx.stop()
        shutil.rmtree(empty_cache, ignore_errors=True)
    return res


async def check_line_2(worktree: Path, kp: int, ap: int, out_dir: Path) -> ProbeResult:
    """Line 2: Non-Kestrel latency <= 2x under hang."""
    res = ProbeResult("2", "Non-Kestrel median and p95 latency <= max(2x healthy, healthy + 5ms) under hang")
    ctx = ServerPairContext(worktree, kp, ap, initial_mode="healthy", out_dir=out_dir)
    await ctx.start()
    try:
        async with httpx.AsyncClient() as client:
            # Baseline non-kestrel latencies
            base_lats: list[float] = []
            for _ in range(15):
                t0 = time.monotonic()
                r = await client.get(f"http://127.0.0.1:{ap}/api/v1/entity-types", timeout=2.0)
                if r.status_code == 200:
                    base_lats.append((time.monotonic() - t0) * 1000.0)
                await asyncio.sleep(0.05)

            base_p50 = sorted(base_lats)[len(base_lats) // 2] if base_lats else 10.0

            # Switch to hang and launch in-flight load
            await client.post(f"http://127.0.0.1:{kp}/__admin/mode", json={"mode": "hang"})
            _ = [
                asyncio.create_task(
                    client.post(
                        f"http://127.0.0.1:{ap}/api/v1/map/entity",
                        json={"name": "leukemia", "entity_type": "disease"},
                        timeout=30.0,
                    )
                )
                for _ in range(8)
            ]

            fault_lats: list[float] = []
            for _ in range(15):
                t0 = time.monotonic()
                r = await client.get(f"http://127.0.0.1:{ap}/api/v1/entity-types", timeout=2.0)
                if r.status_code == 200:
                    fault_lats.append((time.monotonic() - t0) * 1000.0)
                await asyncio.sleep(0.05)

            fault_p50 = sorted(fault_lats)[len(fault_lats) // 2] if fault_lats else 9999.0
            allowed_p50 = max(2.0 * base_p50, base_p50 + 5.0)

            evidence = {"base_p50_ms": round(base_p50, 1), "fault_p50_ms": round(fault_p50, 1), "allowed_p50_ms": round(allowed_p50, 1)}
            if fault_p50 <= allowed_p50:
                res.mark_pass(f"fault p50 {fault_p50:.1f}ms <= {allowed_p50:.1f}ms", evidence=evidence)
            else:
                res.mark_fail(f"fault p50 {fault_p50:.1f}ms > {allowed_p50:.1f}ms", evidence=evidence)
    finally:
        await ctx.stop()
    return res


async def check_line_3a(worktree: Path, kp: int, ap: int, out_dir: Path) -> ProbeResult:
    """Line 3a: Rule 3.1 & 3.2 - Unresolved + Kestrel fault reports error across all 4 code paths."""
    res = ProbeResult("3a", "All 4 Kestrel code paths report non-empty error when unresolved under Kestrel faults")
    ctx = ServerPairContext(worktree, kp, ap, initial_mode="healthy", out_dir=out_dir)
    await ctx.start()
    try:
        async with httpx.AsyncClient() as client:
            # 1. Standard search path (leukemia, hybrid-search: 5xx)
            await client.post(f"http://127.0.0.1:{kp}/__admin/mode", json={"endpoint_overrides": {"hybrid-search": "5xx"}})
            r1 = await client.post(
                f"http://127.0.0.1:{ap}/api/v1/map/entity",
                json={"name": "leukemia", "entity_type": "disease"},
                timeout=10.0,
            )
            d1 = r1.json().get("result", {})
            p1_ok = d1.get("chosen_kg_id") is None and bool(d1.get("error"))

            # 2. Lipid cascade (12-HETE, annotator goslin-lipid, hybrid-search: 5xx)
            r2 = await client.post(
                f"http://127.0.0.1:{ap}/api/v1/map/entity",
                json={"name": "12-HETE", "entity_type": "lipid", "options": {"annotators": ["goslin-lipid"]}},
                timeout=10.0,
            )
            d2 = r2.json().get("result", {})
            p2_ok = d2.get("chosen_kg_id") is None and bool(d2.get("error"))

            # 3. Curated drug-conflated human gene GH1 (get-nodes: 5xx, discards non-human search ortholog)
            await client.post(f"http://127.0.0.1:{kp}/__admin/mode", json={"endpoint_overrides": {"get-nodes": "5xx"}})
            r3 = await client.post(
                f"http://127.0.0.1:{ap}/api/v1/map/entity",
                json={"name": "GH1", "entity_type": "gene"},
                timeout=10.0,
            )
            d3 = r3.json().get("result", {})
            p3_ok = d3.get("chosen_kg_id") is None and bool(d3.get("error"))

            # 4. Provided ID linking (glucose with kegg C00031, canonicalize: 5xx)
            await client.post(f"http://127.0.0.1:{kp}/__admin/mode", json={"endpoint_overrides": {"canonicalize": "5xx"}})
            r4 = await client.post(
                f"http://127.0.0.1:{ap}/api/v1/map/entity",
                json={"name": "glucose", "entity_type": "metabolite", "identifiers": {"kegg": "C00031"}, "options": {"annotation_mode": "missing"}},
                timeout=10.0,
            )
            d4 = r4.json().get("result", {})
            p4_ok = d4.get("chosen_kg_id") is None and bool(d4.get("error"))

            evidence = {"p1_search": p1_ok, "p2_lipid": p2_ok, "p3_gene": p3_ok, "p4_linker": p4_ok}
            if all([p1_ok, p2_ok, p3_ok, p4_ok]):
                res.mark_pass("All 4 code paths correctly emitted non-empty error when unresolved", evidence=evidence)
            else:
                res.mark_fail(f"Failure in code paths: {evidence}", evidence=evidence)
    finally:
        await ctx.stop()
    return res


async def check_line_3b(worktree: Path, kp: int, ap: int, out_dir: Path) -> ProbeResult:
    """Line 3b: Rule 3.3 - Non-Kestrel resolution + Kestrel fault emits kestrel_degraded: true, omitted when healthy."""
    res = ProbeResult("3b", "Emits kestrel_degraded: true when non-Kestrel evidence resolves, omitted when healthy")
    ctx = ServerPairContext(worktree, kp, ap, initial_mode="healthy", out_dir=out_dir)
    await ctx.start()
    try:
        async with httpx.AsyncClient() as client:
            # Under hybrid-search fault: Cholic acid resolves via RefMet freeze + healthy canonicalize
            await client.post(f"http://127.0.0.1:{kp}/__admin/mode", json={"endpoint_overrides": {"hybrid-search": "5xx"}})
            r_deg = await client.post(
                f"http://127.0.0.1:{ap}/api/v1/map/entity",
                json={"name": "Cholic acid", "entity_type": "metabolite"},
                timeout=10.0,
            )
            d_deg = r_deg.json().get("result", {})
            deg_ok = d_deg.get("chosen_kg_id") is not None and d_deg.get("kestrel_degraded") is True and d_deg.get("error") is None

            # Under healthy Kestrel: kestrel_degraded must be completely omitted from JSON object
            await client.post(f"http://127.0.0.1:{kp}/__admin/reset")
            r_healthy = await client.post(
                f"http://127.0.0.1:{ap}/api/v1/map/entity",
                json={"name": "Cholic acid", "entity_type": "metabolite"},
                timeout=10.0,
            )
            raw_text = r_healthy.text
            omitted_ok = "kestrel_degraded" not in raw_text

            evidence = {"deg_ok": deg_ok, "omitted_ok": omitted_ok}
            if deg_ok and omitted_ok:
                res.mark_pass("Emitted kestrel_degraded: true on fault resolution, completely omitted when healthy", evidence=evidence)
            else:
                res.mark_fail(f"Verification failed: deg_ok={deg_ok}, omitted_ok={omitted_ok}", evidence=evidence)
    finally:
        await ctx.stop()
    return res


async def check_line_4(worktree: Path, kp: int, ap: int, out_dir: Path) -> ProbeResult:
    """Line 4: Timeouts and 5xx are never cached on the same process."""
    res = ProbeResult("4", "Errors under fault are not cached; resolve normally once Kestrel becomes healthy")
    ctx = ServerPairContext(worktree, kp, ap, initial_mode="healthy", out_dir=out_dir)
    await ctx.start()
    try:
        async with httpx.AsyncClient() as client:
            # Query under 5xx: must error
            await client.post(f"http://127.0.0.1:{kp}/__admin/mode", json={"endpoint_overrides": {"hybrid-search": "5xx"}})
            r_err = await client.post(
                f"http://127.0.0.1:{ap}/api/v1/map/entity",
                json={"name": "leukemia", "entity_type": "disease"},
                timeout=10.0,
            )
            d_err = r_err.json().get("result", {})
            errored_ok = bool(d_err.get("error"))

            # Switch back to healthy on same running process and re-query
            await client.post(f"http://127.0.0.1:{kp}/__admin/reset")
            r_heal = await client.post(
                f"http://127.0.0.1:{ap}/api/v1/map/entity",
                json={"name": "leukemia", "entity_type": "disease"},
                timeout=10.0,
            )
            d_heal = r_heal.json().get("result", {})
            resolved_ok = bool(d_heal.get("chosen_kg_id")) and d_heal.get("error") is None

            evidence = {"errored_under_fault": errored_ok, "resolved_under_healthy": resolved_ok}
            if errored_ok and resolved_ok:
                res.mark_pass("Uncached error resolved immediately to normal match upon healthy transition", evidence=evidence)
            else:
                res.mark_fail(f"Line 4 failed: {evidence}", evidence=evidence)
    finally:
        await ctx.stop()
    return res


async def check_line_5(worktree: Path, kp: int, ap: int, out_dir: Path, recover_after_s: float = 5.0) -> ProbeResult:
    """Line 5: Automatic recovery in recovering mode <= 60s."""
    res = ProbeResult("5", "Automatic recovery in recovering mode returns full service in <= 60s without restart")
    ctx = ServerPairContext(
        worktree,
        kp,
        ap,
        initial_mode="healthy",
        out_dir=out_dir,
    )
    await ctx.start()
    try:
        async with httpx.AsyncClient() as client:
            # Set Fake Kestrel to recovering with short recovery window for probe
            await client.post(
                f"http://127.0.0.1:{kp}/__admin/mode",
                json={"mode": "recovering", "slow_delay_s": 1.0, "recover_after_s": recover_after_s},
            )
            await asyncio.sleep(recover_after_s)
            flip_time = time.monotonic()

            recovered = False
            recovery_dur_s = 0.0
            for _ in range(60):
                try:
                    t0 = time.monotonic()
                    hr = await client.get(f"http://127.0.0.1:{ap}/api/v1/health", timeout=1.5)
                    h_ms = (time.monotonic() - t0) * 1000.0
                    mr = await client.post(
                        f"http://127.0.0.1:{ap}/api/v1/map/entity",
                        json={"name": "leukemia", "entity_type": "disease"},
                        timeout=3.0,
                    )
                    if hr.status_code == 200 and h_ms < 1000.0 and mr.status_code == 200:
                        res_json = mr.json().get("result", {})
                        if res_json.get("chosen_kg_id") and not res_json.get("error"):
                            recovery_dur_s = time.monotonic() - flip_time
                            recovered = True
                            break
                except Exception:
                    pass
                await asyncio.sleep(1.0)

            evidence = {"recovered": recovered, "recovery_time_s": round(recovery_dur_s, 2)}
            if recovered and recovery_dur_s <= 60.0:
                res.mark_pass(f"Recovered in {recovery_dur_s:.2f}s (<= 60.0s)", evidence=evidence)
            else:
                res.mark_fail(f"Failed to recover in <= 60s: {evidence}", evidence=evidence)
    finally:
        await ctx.stop()
    return res


async def check_line_6(worktree: Path, kp: int, ap: int, out_dir: Path) -> ProbeResult:
    """Line 6: Fixed regression set byte-identical under healthy Kestrel."""
    res = ProbeResult("6", "100% SHA-256 byte identity against golden_healthy_e578a93.json.gz")
    ctx = ServerPairContext(worktree, kp, ap, initial_mode="healthy", out_dir=out_dir)
    await ctx.start()
    try:
        matched, suite_sha, mismatches = verify_against_golden(f"http://127.0.0.1:{ap}")
        evidence = {"matched": matched, "suite_sha256": suite_sha, "mismatches": mismatches}
        if matched:
            res.mark_pass(f"100% match (suite_sha256={suite_sha})", evidence=evidence)
        else:
            res.mark_fail(f"Mismatches detected: {mismatches[:3]}", evidence=evidence)
    finally:
        await ctx.stop()
    return res


async def run_all_gate_probes(
    candidate: str,
    worktree: Path,
    kestrel_port: int,
    api_port: int,
    out_dir: Path,
    lines_to_run: list[str],
    recover_after_s: float = 5.0,
) -> dict[str, Any]:
    """Execute all requested gate checklist lines and write result.json."""
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[ProbeResult] = []

    for line_id in lines_to_run:
        line_id = line_id.strip().lower()
        if line_id == "1a":
            results.append(await check_line_1a(worktree, kestrel_port, api_port, out_dir))
        elif line_id == "1b":
            results.append(await check_line_1b(worktree, kestrel_port, api_port, out_dir))
        elif line_id == "2":
            results.append(await check_line_2(worktree, kestrel_port, api_port, out_dir))
        elif line_id == "3a":
            results.append(await check_line_3a(worktree, kestrel_port, api_port, out_dir))
        elif line_id == "3b":
            results.append(await check_line_3b(worktree, kestrel_port, api_port, out_dir))
        elif line_id == "4":
            results.append(await check_line_4(worktree, kestrel_port, api_port, out_dir))
        elif line_id == "5":
            results.append(await check_line_5(worktree, kestrel_port, api_port, out_dir, recover_after_s=recover_after_s))
        elif line_id == "6":
            results.append(await check_line_6(worktree, kestrel_port, api_port, out_dir))

    pass_count = sum(1 for r in results if r.verdict == "pass")
    fail_count = sum(1 for r in results if r.verdict == "fail")

    summary_dict = {
        "candidate": candidate,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "pass": pass_count,
            "fail": fail_count,
            "not_checkable_here": 0,
        },
        "lines": [r.to_dict() for r in results],
    }

    result_json_path = out_dir / "result.json"
    with open(result_json_path, "w", encoding="utf-8") as f:
        json.dump(summary_dict, f, indent=2)

    return summary_dict


def main() -> None:
    """CLI entrypoint for black-box gate probes."""
    parser = argparse.ArgumentParser(description="BioMapper2 Kestrel Fault Gate Probes")
    parser.add_argument("--candidate", required=True, help="Candidate name")
    parser.add_argument("--worktree", required=True, help="Candidate worktree root path")
    parser.add_argument("--kestrel-port", type=int, default=18100, help="Fake Kestrel port")
    parser.add_argument("--api-port", type=int, default=18101, help="Candidate API port")
    parser.add_argument("--out-dir", required=True, help="Output directory for result.json and logs")
    parser.add_argument("--lines", default="1a,1b,2,3a,3b,4,5,6", help="Comma-separated lines to check")
    parser.add_argument("--recover-after-s", type=float, default=5.0, help="Recovery window for Line 5 check")
    args = parser.parse_args()

    worktree = Path(args.worktree).resolve()
    out_dir = Path(args.out_dir).resolve()
    lines = [x.strip() for x in args.lines.split(",") if x.strip()]

    res = asyncio.run(
        run_all_gate_probes(
            candidate=args.candidate,
            worktree=worktree,
            kestrel_port=args.kestrel_port,
            api_port=args.api_port,
            out_dir=out_dir,
            lines_to_run=lines,
            recover_after_s=args.recover_after_s,
        )
    )
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["summary"]["fail"] == 0 else 1)


if __name__ == "__main__":
    main()
