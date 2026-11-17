"""Black-box HTTP gate probes for BioMapper2 Kestrel fault isolation.

Evaluates running candidate API processes against Fake Kestrel without inspecting
source code. Tests Lines 1a, 1b, 2, 3a (Rule 3.1 & 3.2), 3b (Rule 3.3), 4, 5, and 6
as specified in GATE_CHECKLIST.md.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import io
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

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from studies.kestrel_fault_benchmark.regression_set import verify_against_golden

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


def _seed_biolink_static_files(worktree: Path, cache_dir: Path) -> None:
    """Atomically copy pinned Biolink schema and prefix-map fixtures into cache_dir for offline runs."""
    fixtures_dir = worktree / "studies" / "kestrel_fault_benchmark" / "fixtures"
    cache_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "biolink-model_4.2.5.yaml",
        "biolink-model-prefix-map_4.2.5.json",
    ):
        src = fixtures_dir / name
        dst = cache_dir / name
        if src.exists() and not dst.exists():
            fd, tmp = tempfile.mkstemp(dir=str(cache_dir), suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(src.read_bytes())
                os.replace(tmp, str(dst))
            except BaseException:
                with contextlib.suppress(OSError):
                    os.remove(tmp)
                raise


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
        self._owns_cache_dir = cache_dir is None
        self.cache_dir = cache_dir or Path(tempfile.mkdtemp(prefix="gate_cache_"))
        self.out_dir = out_dir or Path(tempfile.mkdtemp(prefix="gate_logs_"))
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.fk_proc: subprocess.Popen[Any] | None = None
        self.api_proc: subprocess.Popen[Any] | None = None
        self.log_fk: Any = None
        self.log_api: Any = None

    async def start(self, wait_mapper_ready: bool = True, require_ready: bool = True) -> float:
        """Start both servers. Returns API launch-to-ready duration in seconds."""
        try:
            python_bin = self.worktree / ".venv" / "bin" / "python"
            if not python_bin.exists():
                python_bin = Path(sys.executable)

            _seed_biolink_static_files(self.worktree, self.cache_dir)
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
            fk_env = os.environ.copy()
            fk_env["PYTHONPATH"] = str(self.worktree)
            self.fk_proc = subprocess.Popen(
                fk_cmd,
                cwd=self.worktree,
                env=fk_env,
                stdout=self.log_fk,
                stderr=self.log_fk,
            )

            # Wait for Fake Kestrel
            fk_ready = False
            async with httpx.AsyncClient() as client:
                for _ in range(50):
                    if self.fk_proc.poll() is not None:
                        raise RuntimeError(f"Fake Kestrel exited prematurely with code {self.fk_proc.returncode}")
                    try:
                        r = await client.get(f"http://127.0.0.1:{self.kestrel_port}/__admin/state", timeout=1.0)
                        if r.status_code == 200:
                            fk_ready = True
                            break
                    except Exception:
                        await asyncio.sleep(0.1)
            if not fk_ready:
                raise RuntimeError("Fake Kestrel failed to become ready")

            # 2. Candidate API
            api_env = os.environ.copy()
            existing_pp = api_env.get("PYTHONPATH", "")
            api_pp = f"{self.worktree / 'src'}{os.pathsep}{self.worktree}"
            api_env["PYTHONPATH"] = f"{api_pp}{os.pathsep}{existing_pp}" if existing_pp else api_pp
            api_env["KESTREL_API_URL"] = f"http://127.0.0.1:{self.kestrel_port}"
            api_env["BIOMAPPER2_PREDICATE_MAP_URL"] = (
                f"http://127.0.0.1:{self.kestrel_port}/__fixtures/predicate_mapping.yaml"
            )
            api_env["BIOMAPPER2_CACHE_DIR"] = str(self.cache_dir)
            api_env["REFMET_SNAPSHOT_PATH"] = str(
                (
                    self.worktree / "studies" / "kestrel_fault_benchmark" / "fixtures" / "refmet_regression_freeze.tsv"
                ).resolve()
            )
            api_env["REFMET_FREEZE_MODE"] = "frozen"
            api_env["REFMET_LIVE_API_FALLBACK"] = "0"
            api_env["BIOMAPPER2_TIER_B_ENABLED"] = "0"

            api_cmd = [
                str(python_bin),
                "-m",
                "uvicorn",
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
                        if self.api_proc.poll() is not None:
                            if require_ready:
                                raise RuntimeError(
                                    f"Candidate API exited prematurely with code {self.api_proc.returncode}"
                                )
                            break
                        try:
                            r = await client.get(f"http://127.0.0.1:{self.api_port}/api/v1/health", timeout=1.0)
                            if r.status_code == 200 and r.json().get("mapper_initialized"):
                                ready_time = time.monotonic() - t_start
                                break
                        except Exception:
                            await asyncio.sleep(0.1)
                if require_ready and ready_time <= 0.0:
                    raise RuntimeError("Candidate API failed to initialize mapper within startup timeout")

            return ready_time
        except BaseException:
            await self.stop()
            raise

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
        if self._owns_cache_dir:
            shutil.rmtree(self.cache_dir, ignore_errors=True)


def _mapping_response_errored(resp: Any) -> bool:
    if not isinstance(resp, httpx.Response) or resp.status_code != 200:
        return False
    body = resp.json()
    if "result" in body:
        res = body.get("result") or {}
        return bool(res.get("error")) and res.get("chosen_kg_id") is None
    if "results" in body:
        results = body.get("results") or []
        failed = body.get("summary", {}).get("failed", 0)
        return (
            failed == len(results) > 0
            and all(bool(r.get("error")) and r.get("chosen_kg_id") is None for r in results)
        )
    return False


async def check_line_1a(worktree: Path, kp: int, ap: int, out_dir: Path) -> ProbeResult:
    """Line 1a: Event-loop liveness under hang."""
    res = ProbeResult("1a", "20/20 health checks < 1.0s under hang while 8 mapping workers in-flight; workers error")
    ctx = ServerPairContext(worktree, kp, ap, initial_mode="healthy", out_dir=out_dir / "line_1a")
    await ctx.start()
    try:
        async with httpx.AsyncClient() as client:
            # Switch Fake Kestrel to hang
            await client.post(f"http://127.0.0.1:{kp}/__admin/mode", json={"mode": "hang"})

            # Schedule 8 concurrent mapping requests BEFORE health probes (6 /entity + 2 /batch)
            mapping_tasks: list[asyncio.Task[httpx.Response]] = []
            for idx in range(6):
                name = "leukemia" if idx % 2 == 0 else "heart attack"
                mapping_tasks.append(
                    asyncio.create_task(
                        client.post(
                            f"http://127.0.0.1:{ap}/api/v1/map/entity",
                            json={"name": name, "entity_type": "disease"},
                            timeout=30.0,
                        )
                    )
                )
            for _ in range(2):
                mapping_tasks.append(
                    asyncio.create_task(
                        client.post(
                            f"http://127.0.0.1:{ap}/api/v1/map/batch",
                            json={"entities": [{"name": "isoleucine", "entity_type": "metabolite"}]},
                            timeout=30.0,
                        )
                    )
                )

            # Confirm requests have actively reached Fake Kestrel hang before probing health
            active_hangs_before = 0
            for _ in range(100):
                st = (await client.get(f"http://127.0.0.1:{kp}/__admin/state", timeout=1.0)).json()
                active_hangs_before = int(st.get("active_hangs", 0))
                if active_hangs_before >= 1:
                    break
                await asyncio.sleep(0.02)
            in_flight_before = sum(1 for t in mapping_tasks if not t.done())

            # Measure 20 health check probes while mapping tasks remain in flight (~0.4s window)
            health_ok = 0
            health_latencies: list[float] = []
            for _ in range(20):
                t0 = time.monotonic()
                try:
                    hr = await client.get(f"http://127.0.0.1:{ap}/api/v1/health", timeout=1.5)
                    elapsed_ms = (time.monotonic() - t0) * 1000.0
                    health_latencies.append(elapsed_ms)
                    if (
                        hr.status_code == 200
                        and hr.json().get("status") == "healthy"
                        and hr.json().get("mapper_initialized") is True
                        and elapsed_ms < 1000.0
                    ):
                        health_ok += 1
                except Exception:
                    health_latencies.append(9999.0)
                await asyncio.sleep(0.02)

            in_flight_after = sum(1 for t in mapping_tasks if not t.done())
            st_after = (await client.get(f"http://127.0.0.1:{kp}/__admin/state", timeout=1.0)).json()
            active_hangs_after = int(st_after.get("active_hangs", 0))

            # Await mapping tasks to verify clean termination with error
            map_responses = await asyncio.gather(*mapping_tasks, return_exceptions=True)
            workers_errored = sum(1 for mr in map_responses if _mapping_response_errored(mr))

            evidence = {
                "health_ok": health_ok,
                "health_total": 20,
                "health_latencies_ms": [round(x, 1) for x in health_latencies],
                "in_flight_before": in_flight_before,
                "in_flight_after": in_flight_after,
                "active_hangs_before": active_hangs_before,
                "active_hangs_after": active_hangs_after,
                "workers_errored": workers_errored,
            }

            if (
                health_ok == 20
                and in_flight_before >= 1
                and in_flight_after >= 1
                and active_hangs_before >= 1
                and active_hangs_after >= 1
                and workers_errored == 8
            ):
                res.mark_pass(
                    "20/20 health < 1.0s while mapping requests actively hung in-flight; 8/8 errored cleanly",
                    evidence=evidence,
                )
            else:
                res.mark_fail(
                    f"{health_ok}/20 health < 1s, in_flight={in_flight_before}->{in_flight_after}, "
                    f"{workers_errored}/8 mapping workers cleanly errored",
                    evidence=evidence,
                )
    finally:
        await ctx.stop()
    return res


async def check_line_1b(worktree: Path, kp: int, ap: int, out_dir: Path) -> ProbeResult:
    """Line 1b: Cold startup under hang <= 15s."""
    res = ProbeResult("1b", "Cold startup under hang ready on GET /health in <= 15.0s")
    empty_cache = Path(tempfile.mkdtemp(prefix="gate_1b_empty_cache_"))
    ctx = ServerPairContext(
        worktree, kp, ap, initial_mode="hang", cache_dir=empty_cache, out_dir=out_dir / "line_1b"
    )
    try:
        ready_duration = await ctx.start(wait_mapper_ready=True, require_ready=False)
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


def _pct(vals: list[float], p: float) -> float:
    if not vals:
        return 9999.0
    s = sorted(vals)
    idx = (len(s) - 1) * p
    lo, hi = math.floor(idx), math.ceil(idx)
    return s[int(idx)] if lo == hi else s[lo] * (1.0 - (idx - lo)) + s[hi] * (idx - lo)


async def _measure_non_kestrel_mix(
    client: httpx.AsyncClient, ap: int, rounds: int = 5
) -> tuple[list[float], int]:
    lats: list[float] = []
    failures = 0
    for _ in range(rounds):
        for ep in ("entity-types", "annotators", "vocabularies"):
            t0 = time.monotonic()
            try:
                r = await client.get(f"http://127.0.0.1:{ap}/api/v1/{ep}", timeout=3.0)
                if r.status_code == 200:
                    lats.append((time.monotonic() - t0) * 1000.0)
                else:
                    failures += 1
            except Exception:
                failures += 1
        t0 = time.monotonic()
        try:
            rm = await client.post(
                f"http://127.0.0.1:{ap}/api/v1/map/entity",
                json={"name": "glucose", "entity_type": "metabolite", "options": {"annotation_mode": "none"}},
                timeout=3.0,
            )
            if rm.status_code == 200 and not rm.json().get("result", {}).get("error"):
                lats.append((time.monotonic() - t0) * 1000.0)
            else:
                failures += 1
        except Exception:
            failures += 1
        await asyncio.sleep(0.03)
    return lats, failures


async def check_line_2(
    worktree: Path, kp: int, ap: int, out_dir: Path, slow_delay_s: float = 30.0
) -> ProbeResult:
    """Line 2: Non-Kestrel latency <= 2x under hang and slow-30s."""
    res = ProbeResult("2", "Non-Kestrel p50 and p95 latency <= max(2x healthy, healthy + 5ms) under hang & slow-30s")
    ctx = ServerPairContext(worktree, kp, ap, initial_mode="healthy", out_dir=out_dir / "line_2")
    await ctx.start()
    try:
        async with httpx.AsyncClient() as client:
            expected_samples = 4 * 5
            # Warmup once, then measure baseline
            _, warmup_failures = await _measure_non_kestrel_mix(client, ap, rounds=1)
            base_lats, base_failures = await _measure_non_kestrel_mix(client, ap, rounds=5)
            base_p50 = _pct(base_lats, 0.50)
            base_p95 = _pct(base_lats, 0.95)
            allow_p50 = max(2.0 * base_p50, base_p50 + 5.0)
            allow_p95 = max(2.0 * base_p95, base_p95 + 5.0)

            mode_stats: dict[str, dict[str, Any]] = {}
            for fault_mode in ("hang", "slow-30s"):
                await client.post(
                    f"http://127.0.0.1:{kp}/__admin/mode",
                    json={"mode": fault_mode, "slow_delay_s": slow_delay_s},
                )
                bg_tasks = [
                    asyncio.create_task(
                        client.post(
                            f"http://127.0.0.1:{ap}/api/v1/map/entity",
                            json={"name": "leukemia", "entity_type": "disease"},
                            timeout=35.0,
                        )
                    )
                    for _ in range(8)
                ]
                await asyncio.sleep(0.15)
                fault_lats, fault_failures = await _measure_non_kestrel_mix(client, ap, rounds=5)
                mode_stats[fault_mode] = {
                    "samples_ok": len(fault_lats),
                    "samples_failed": fault_failures,
                    "p50_ms": round(_pct(fault_lats, 0.50), 2),
                    "p95_ms": round(_pct(fault_lats, 0.95), 2),
                }
                await client.post(f"http://127.0.0.1:{kp}/__admin/reset")
                for t in bg_tasks:
                    t.cancel()
                await asyncio.gather(*bg_tasks, return_exceptions=True)

            baseline_ok = warmup_failures == 0 and base_failures == 0 and len(base_lats) == expected_samples
            ok = baseline_ok and all(
                st["samples_failed"] == 0
                and st["samples_ok"] == expected_samples
                and st["p50_ms"] <= allow_p50
                and st["p95_ms"] <= allow_p95
                for st in mode_stats.values()
            )
            evidence = {
                "base_samples_ok": len(base_lats),
                "base_samples_failed": base_failures,
                "base_p50_ms": round(base_p50, 2),
                "base_p95_ms": round(base_p95, 2),
                "allow_p50_ms": round(allow_p50, 2),
                "allow_p95_ms": round(allow_p95, 2),
                "fault_modes": mode_stats,
            }
            if ok:
                res.mark_pass(f"Non-Kestrel p50/p95 within 2x across hang & slow-30s: {mode_stats}", evidence=evidence)
            else:
                res.mark_fail(f"Non-Kestrel check failed (failures or latency bound): {evidence}", evidence=evidence)
    finally:
        await ctx.stop()
    return res


async def check_line_3a(worktree: Path, kp: int, ap: int, out_dir: Path) -> ProbeResult:
    """Line 3a: Rule 3.1 & 3.2 - Unresolved + Kestrel fault reports error across all 4 code paths & all routes."""
    res = ProbeResult(
        "3a",
        "All 4 Kestrel code paths report non-empty error when unresolved across /entity, /batch, /dataset/stream, /dataset",
    )
    ctx = ServerPairContext(worktree, kp, ap, initial_mode="healthy", out_dir=out_dir / "line_3a")
    await ctx.start()
    try:
        async with httpx.AsyncClient() as client:
            # 1. Standard search path under BOTH 5xx and hang timeout
            await client.post(f"http://127.0.0.1:{kp}/__admin/mode", json={"endpoint_overrides": {"hybrid-search": "5xx"}})
            r1 = await client.post(
                f"http://127.0.0.1:{ap}/api/v1/map/entity",
                json={"name": "leukemia", "entity_type": "disease"},
                timeout=20.0,
            )
            d1 = r1.json().get("result", {})
            p1_5xx_ok = (
                r1.status_code == 200
                and d1.get("chosen_kg_id") is None
                and d1.get("resolution_certificate") is None
                and bool(d1.get("error"))
            )

            await client.post(f"http://127.0.0.1:{kp}/__admin/mode", json={"endpoint_overrides": {"hybrid-search": "hang"}})
            r1_hang = await client.post(
                f"http://127.0.0.1:{ap}/api/v1/map/entity",
                json={"name": "heart attack", "entity_type": "disease"},
                timeout=30.0,
            )
            d1_hang = r1_hang.json().get("result", {})
            p1_hang_ok = (
                r1_hang.status_code == 200
                and d1_hang.get("chosen_kg_id") is None
                and d1_hang.get("resolution_certificate") is None
                and bool(d1_hang.get("error"))
            )
            p1_ok = p1_5xx_ok and p1_hang_ok

            # 2. Lipid cascade (12-HETE, annotator goslin-lipid, hybrid-search: 5xx)
            await client.post(f"http://127.0.0.1:{kp}/__admin/mode", json={"endpoint_overrides": {"hybrid-search": "5xx"}})
            r2 = await client.post(
                f"http://127.0.0.1:{ap}/api/v1/map/entity",
                json={"name": "12-HETE", "entity_type": "lipid", "options": {"annotators": ["goslin-lipid"]}},
                timeout=20.0,
            )
            d2 = r2.json().get("result", {})
            p2_ok = r2.status_code == 200 and d2.get("chosen_kg_id") is None and bool(d2.get("error"))

            # 3. Curated drug-conflated human gene GH1 (get-nodes: 5xx, discards non-human search ortholog)
            await client.post(f"http://127.0.0.1:{kp}/__admin/mode", json={"endpoint_overrides": {"get-nodes": "5xx"}})
            r3 = await client.post(
                f"http://127.0.0.1:{ap}/api/v1/map/entity",
                json={"name": "GH1", "entity_type": "gene"},
                timeout=20.0,
            )
            d3 = r3.json().get("result", {})
            p3_ok = r3.status_code == 200 and d3.get("chosen_kg_id") is None and bool(d3.get("error"))

            # 4. Provided ID linking (glucose with kegg C00031, canonicalize: 5xx) + /batch summary.failed
            await client.post(f"http://127.0.0.1:{kp}/__admin/mode", json={"endpoint_overrides": {"canonicalize": "5xx"}})
            r4 = await client.post(
                f"http://127.0.0.1:{ap}/api/v1/map/batch",
                json={
                    "entities": [
                        {
                            "name": "glucose",
                            "entity_type": "metabolite",
                            "identifiers": {"kegg": "C00031"},
                            "options": {"annotation_mode": "missing"},
                        }
                    ]
                },
                timeout=20.0,
            )
            b4 = r4.json()
            d4 = (b4.get("results") or [{}])[0]
            p4_ok = (
                r4.status_code == 200
                and d4.get("chosen_kg_id") is None
                and bool(d4.get("error"))
                and b4.get("summary", {}).get("failed") == 1
            )

            # 5. /map/dataset/stream + /map/dataset optional `error` column rule
            await client.post(f"http://127.0.0.1:{kp}/__admin/mode", json={"endpoint_overrides": {"hybrid-search": "5xx"}})
            tsv_bytes = b"name\tkegg\nglucose\tC00031\nisoleucine\t\n"
            r_stream = await client.post(
                f"http://127.0.0.1:{ap}/api/v1/map/dataset/stream",
                params={"entity_type": "metabolite", "name_column": "name", "provided_id_columns": "kegg"},
                files={"file": ("err_stream.tsv", io.BytesIO(tsv_bytes), "text/tab-separated-values")},
                timeout=20.0,
            )
            stream_lines = [json.loads(ln) for ln in r_stream.text.splitlines() if ln.strip()]
            stream_ok = (
                r_stream.status_code == 200
                and len(stream_lines) == 2
                and bool(stream_lines[0].get("chosen_kg_id"))
                and bool(stream_lines[1].get("error"))
                and stream_lines[1].get("chosen_kg_id") is None
            )

            r_ds = await client.post(
                f"http://127.0.0.1:{ap}/api/v1/map/dataset",
                params={"entity_type": "metabolite", "name_column": "name", "provided_id_columns": "kegg"},
                files={"file": ("err_ds.tsv", io.BytesIO(tsv_bytes), "text/tab-separated-values")},
                timeout=20.0,
            )
            dataset_err_col_ok = False
            if r_ds.status_code == 200:
                out_file = Path(r_ds.json().get("output_file", ""))
                if out_file.exists():
                    rows = list(csv.DictReader(out_file.read_text(encoding="utf-8").splitlines(), delimiter="\t"))
                    dataset_err_col_ok = (
                        len(rows) == 2
                        and "error" in rows[0]
                        and not (rows[0].get("error") or "").strip()
                        and bool((rows[1].get("error") or "").strip())
                        and not (rows[1].get("chosen_kg_id") or "").strip()
                    )

            evidence = {
                "p1_search_5xx_and_hang": p1_ok,
                "p2_lipid": p2_ok,
                "p3_gene": p3_ok,
                "p4_linker_batch": p4_ok,
                "stream_ok": stream_ok,
                "dataset_error_col_ok": dataset_err_col_ok,
            }
            if all(evidence.values()):
                res.mark_pass("All code paths & routes emitted error cleanly when unresolved", evidence=evidence)
            else:
                res.mark_fail(f"Failure in Line 3a checks: {evidence}", evidence=evidence)
    finally:
        await ctx.stop()
    return res


async def check_line_3b(worktree: Path, kp: int, ap: int, out_dir: Path) -> ProbeResult:
    """Line 3b: Rule 3.3 - Non-Kestrel resolution + Kestrel fault emits kestrel_degraded: true, omitted when healthy."""
    res = ProbeResult(
        "3b",
        "Emits kestrel_degraded: true when non-Kestrel vote resolves despite fault; omits key/column when healthy",
    )
    ctx = ServerPairContext(worktree, kp, ap, initial_mode="healthy", out_dir=out_dir / "line_3b")
    await ctx.start()
    try:
        async with httpx.AsyncClient() as client:
            # 1. RefMet snapshot vote resolves Cholic acid while hybrid-search fails (5xx)
            await client.post(f"http://127.0.0.1:{kp}/__admin/mode", json={"endpoint_overrides": {"hybrid-search": "5xx"}})
            r_deg = await client.post(
                f"http://127.0.0.1:{ap}/api/v1/map/entity",
                json={"name": "Cholic acid", "entity_type": "metabolite"},
                timeout=20.0,
            )
            d_deg = r_deg.json().get("result", {})
            refmet_deg_ok = (
                d_deg.get("chosen_kg_id") is not None
                and d_deg.get("kestrel_degraded") is True
                and d_deg.get("error") is None
            )

            # 2. Provided ID resolves glucose while get-nodes enrichment fails (5xx)
            await client.post(f"http://127.0.0.1:{kp}/__admin/mode", json={"endpoint_overrides": {"get-nodes": "5xx"}})
            r_prov_deg = await client.post(
                f"http://127.0.0.1:{ap}/api/v1/map/entity",
                json={
                    "name": "glucose",
                    "entity_type": "metabolite",
                    "identifiers": {"chebi": "17234"},
                    "options": {"annotation_mode": "missing"},
                },
                timeout=20.0,
            )
            dp = r_prov_deg.json().get("result", {})
            prov_deg_ok = (
                dp.get("chosen_kg_id") is not None
                and dp.get("kestrel_degraded") is True
                and dp.get("error") is None
            )

            # 3. /map/dataset TSV includes boolean kestrel_degraded column when >=1 row degraded
            await client.post(f"http://127.0.0.1:{kp}/__admin/mode", json={"endpoint_overrides": {"hybrid-search": "5xx"}})
            ds_tsv = b"name\tCHEBI\nglucose\t17234\nCholic acid\t\n"
            r_ds_deg = await client.post(
                f"http://127.0.0.1:{ap}/api/v1/map/dataset",
                params={"entity_type": "metabolite", "name_column": "name", "provided_id_columns": "CHEBI"},
                files={"file": ("deg_ds.tsv", io.BytesIO(ds_tsv), "text/tab-separated-values")},
                timeout=20.0,
            )
            ds_deg_col_ok = False
            if r_ds_deg.status_code == 200:
                out_f = Path(r_ds_deg.json().get("output_file", ""))
                if out_f.exists():
                    rows = list(csv.DictReader(out_f.read_text(encoding="utf-8").splitlines(), delimiter="\t"))
                    ds_deg_col_ok = (
                        len(rows) == 2
                        and "kestrel_degraded" in rows[0]
                        and "error" not in rows[0]
                        and rows[0]["kestrel_degraded"].lower() == "false"
                        and rows[1]["kestrel_degraded"].lower() == "true"
                    )

            # 4. Under healthy Kestrel: kestrel_degraded & error omitted from JSON and TSV
            await client.post(f"http://127.0.0.1:{kp}/__admin/reset")
            # Clear cache by querying a healthy row or checking fresh TSV
            r_healthy = await client.post(
                f"http://127.0.0.1:{ap}/api/v1/map/entity",
                json={"name": "Cholic acid", "entity_type": "metabolite"},
                timeout=20.0,
            )
            json_omitted_ok = "kestrel_degraded" not in r_healthy.text

            r_ds_healthy = await client.post(
                f"http://127.0.0.1:{ap}/api/v1/map/dataset",
                params={"entity_type": "metabolite", "name_column": "name", "provided_id_columns": "CHEBI"},
                files={"file": ("healthy_ds.tsv", io.BytesIO(ds_tsv), "text/tab-separated-values")},
                timeout=20.0,
            )
            tsv_omitted_ok = False
            if r_ds_healthy.status_code == 200:
                out_h = Path(r_ds_healthy.json().get("output_file", ""))
                if out_h.exists():
                    header = out_h.read_text(encoding="utf-8").splitlines()[0].split("\t")
                    tsv_omitted_ok = "kestrel_degraded" not in header and "error" not in header

            evidence = {
                "refmet_deg_ok": refmet_deg_ok,
                "prov_deg_ok": prov_deg_ok,
                "ds_deg_col_ok": ds_deg_col_ok,
                "json_omitted_ok": json_omitted_ok,
                "tsv_omitted_ok": tsv_omitted_ok,
            }
            if all(evidence.values()):
                res.mark_pass("Rule 3.3 verified across /entity and /dataset (degraded true & healthy omitted)", evidence=evidence)
            else:
                res.mark_fail(f"Line 3b verification failed: {evidence}", evidence=evidence)
    finally:
        await ctx.stop()
    return res


async def check_line_4(worktree: Path, kp: int, ap: int, out_dir: Path) -> ProbeResult:
    """Line 4: Timeouts and 5xx are never cached on the same running process."""
    res = ProbeResult("4", "Both timeouts (hang) and 5xx are uncached; rows resolve once Kestrel is healthy")
    ctx = ServerPairContext(worktree, kp, ap, initial_mode="healthy", out_dir=out_dir / "line_4")
    await ctx.start()
    try:
        async with httpx.AsyncClient() as client:
            # 1. Timeout fault on uncached entity 'aspirin'
            await client.post(f"http://127.0.0.1:{kp}/__admin/mode", json={"endpoint_overrides": {"hybrid-search": "hang"}})
            r_to = await client.post(
                f"http://127.0.0.1:{ap}/api/v1/map/entity",
                json={"name": "aspirin", "entity_type": "metabolite"},
                timeout=30.0,
            )
            timeout_errored_ok = bool(r_to.json().get("result", {}).get("error"))

            # 2. 5xx fault on uncached entity 'BRCA1'
            await client.post(f"http://127.0.0.1:{kp}/__admin/mode", json={"endpoint_overrides": {"hybrid-search": "5xx"}})
            r_5xx = await client.post(
                f"http://127.0.0.1:{ap}/api/v1/map/entity",
                json={"name": "BRCA1", "entity_type": "gene"},
                timeout=20.0,
            )
            http5xx_errored_ok = bool(r_5xx.json().get("result", {}).get("error"))

            # 3. Switch back to healthy on the SAME running process (allow short breaker cooldown if tripped)
            await client.post(f"http://127.0.0.1:{kp}/__admin/reset")
            aspirin_resolved = False
            brca1_resolved = False
            for _ in range(30):
                ra = await client.post(
                    f"http://127.0.0.1:{ap}/api/v1/map/entity",
                    json={"name": "aspirin", "entity_type": "metabolite"},
                    timeout=10.0,
                )
                rb = await client.post(
                    f"http://127.0.0.1:{ap}/api/v1/map/entity",
                    json={"name": "BRCA1", "entity_type": "gene"},
                    timeout=10.0,
                )
                da = ra.json().get("result", {})
                db = rb.json().get("result", {})
                if da.get("chosen_kg_id") and da.get("error") is None and "kestrel_degraded" not in ra.text:
                    aspirin_resolved = True
                if db.get("chosen_kg_id") and db.get("error") is None and "kestrel_degraded" not in rb.text:
                    brca1_resolved = True
                if aspirin_resolved and brca1_resolved:
                    break
                await asyncio.sleep(1.0)

            evidence = {
                "timeout_errored_ok": timeout_errored_ok,
                "http5xx_errored_ok": http5xx_errored_ok,
                "aspirin_resolved_after_timeout": aspirin_resolved,
                "brca1_resolved_after_5xx": brca1_resolved,
            }
            if all(evidence.values()):
                res.mark_pass("Neither timeout nor 5xx cached; both resolved cleanly upon healthy transition", evidence=evidence)
            else:
                res.mark_fail(f"Line 4 failed: {evidence}", evidence=evidence)
    finally:
        await ctx.stop()
    return res


async def check_line_5(
    worktree: Path,
    kp: int,
    ap: int,
    out_dir: Path,
    recover_after_s: float = 120.0,
    slow_delay_s: float = 30.0,
) -> ProbeResult:
    """Line 5: Automatic recovery in recovering mode <= 60s under continuous load."""
    res = ProbeResult("5", "Automatic recovery in recovering mode returns full service in <= 60s without restart")
    ctx = ServerPairContext(
        worktree,
        kp,
        ap,
        initial_mode="healthy",
        out_dir=out_dir / "line_5",
    )
    await ctx.start()
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"http://127.0.0.1:{kp}/__admin/mode",
                json={"mode": "recovering", "slow_delay_s": slow_delay_s, "recover_after_s": recover_after_s},
            )
            mode_start = time.monotonic()
            stop_bg = asyncio.Event()

            async def _bg_load(worker_idx: int) -> None:
                entities = [
                    {"name": "heart attack", "entity_type": "disease"},
                    {"name": "isoleucine", "entity_type": "metabolite"},
                    {"name": "LDLR", "entity_type": "gene"},
                    {"name": "Crohn's disease", "entity_type": "disease"},
                ]
                ent = entities[worker_idx % len(entities)]
                while not stop_bg.is_set():
                    with contextlib.suppress(Exception):
                        await client.post(f"http://127.0.0.1:{ap}/api/v1/map/entity", json=ent, timeout=35.0)
                    await asyncio.sleep(0.5)

            # Keep sustained background traffic running throughout BOTH slow and recovery windows
            bg_workers = [asyncio.create_task(_bg_load(i)) for i in range(4)]
            try:
                flip_deadline = mode_start + recover_after_s
                await asyncio.sleep(max(0.0, flip_deadline - time.monotonic()))
                flip_time = flip_deadline

                recovered = False
                recovery_dur_s = 0.0
                consecutive_ok = 0
                while time.monotonic() - flip_time <= 60.0:
                    try:
                        t0 = time.monotonic()
                        hr = await client.get(f"http://127.0.0.1:{ap}/api/v1/health", timeout=1.5)
                        h_ms = (time.monotonic() - t0) * 1000.0
                        mr = await client.post(
                            f"http://127.0.0.1:{ap}/api/v1/map/entity",
                            json={"name": "leukemia", "entity_type": "disease"},
                            timeout=5.0,
                        )
                        if hr.status_code == 200 and h_ms < 1000.0 and mr.status_code == 200:
                            res_json = mr.json().get("result", {})
                            if (
                                res_json.get("chosen_kg_id")
                                and not res_json.get("error")
                                and "kestrel_degraded" not in mr.text
                            ):
                                consecutive_ok += 1
                                if consecutive_ok >= 2:
                                    recovery_dur_s = max(0.0, time.monotonic() - flip_time)
                                    recovered = True
                                    break
                            else:
                                consecutive_ok = 0
                        else:
                            consecutive_ok = 0
                    except Exception:
                        consecutive_ok = 0
                    await asyncio.sleep(1.0)
            finally:
                stop_bg.set()
                for w in bg_workers:
                    w.cancel()
                await asyncio.gather(*bg_workers, return_exceptions=True)

            evidence = {
                "recovered": recovered,
                "recovery_time_s": round(recovery_dur_s, 2),
                "slow_window_s": recover_after_s,
                "slow_delay_s": slow_delay_s,
            }
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
    ctx = ServerPairContext(worktree, kp, ap, initial_mode="healthy", out_dir=out_dir / "line_6")
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
    recover_after_s: float = 120.0,
    slow_delay_s: float = 30.0,
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
            results.append(
                await check_line_2(worktree, kestrel_port, api_port, out_dir, slow_delay_s=slow_delay_s)
            )
        elif line_id == "3a":
            results.append(await check_line_3a(worktree, kestrel_port, api_port, out_dir))
        elif line_id == "3b":
            results.append(await check_line_3b(worktree, kestrel_port, api_port, out_dir))
        elif line_id == "4":
            results.append(await check_line_4(worktree, kestrel_port, api_port, out_dir))
        elif line_id == "5":
            results.append(
                await check_line_5(
                    worktree,
                    kestrel_port,
                    api_port,
                    out_dir,
                    recover_after_s=recover_after_s,
                    slow_delay_s=slow_delay_s,
                )
            )
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
    parser.add_argument("--recover-after-s", type=float, default=120.0, help="Recovery window for Line 5 check")
    parser.add_argument("--slow-delay-s", type=float, default=30.0, help="Slow-mode delay in seconds")
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
            slow_delay_s=args.slow_delay_s,
        )
    )
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["summary"]["fail"] == 0 else 1)


if __name__ == "__main__":
    main()
