"""Tests for fault-exempt Fake Kestrel fixtures and offline benchmark execution.

Proves that ``/__fixtures/predicate_mapping.yaml`` stays fault-exempt and never hangs
under any fault mode or endpoint override, and that benchmark ``healthy`` mode passes
end-to-end with all non-loopback network traffic blocked.
"""

from __future__ import annotations

import asyncio
import os
import socket
import tempfile
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import requests

from studies.kestrel_fault_benchmark.fake_kestrel import DEFAULT_PREDICATE_MAP_PATH, create_app
from studies.kestrel_fault_benchmark.runner import ALL_MODES, run_benchmark_run

REPO_ROOT = Path(__file__).resolve().parents[2]


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_predicate_mapping_route_exempt_in_every_fault_mode() -> None:
    """Fault-exempt predicate-mapping route responds immediately across all fault modes and overrides."""
    expected_bytes = DEFAULT_PREDICATE_MAP_PATH.read_bytes()

    async def _exercise() -> None:
        app = create_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            for mode in ALL_MODES:
                await client.post(
                    "/__admin/mode",
                    json={
                        "mode": mode,
                        "seed": 101,
                        "slow_delay_s": 30.0,
                        "recover_after_s": 120.0,
                        "endpoint_overrides": {
                            "__fixtures/predicate_mapping.yaml": "hang",
                            "predicate_mapping.yaml": "hang",
                            "health": "hang",
                            "categories": "hang",
                        },
                    },
                )
                for _ in range(4):
                    resp = await asyncio.wait_for(
                        client.get("/__fixtures/predicate_mapping.yaml"),
                        timeout=0.5,
                    )
                    assert resp.status_code == 200
                    assert resp.content == expected_bytes
                state = (await client.get("/__admin/state")).json()
                assert state["active_hangs"] == 0

    asyncio.run(_exercise())


def test_healthy_benchmark_mode_passes_with_outbound_network_blocked() -> None:
    """Benchmark healthy mode initializes Mapper and passes with non-loopback network blocked."""
    kp = _pick_free_port()
    ap = _pick_free_port()
    closed_proxy_port = _pick_free_port()
    dead_proxy = f"http://127.0.0.1:{closed_proxy_port}"

    blocked_env = {
        "HTTP_PROXY": dead_proxy,
        "HTTPS_PROXY": dead_proxy,
        "http_proxy": dead_proxy,
        "https_proxy": dead_proxy,
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
    }

    with tempfile.TemporaryDirectory() as out_dir_str, patch.dict(os.environ, blocked_env):
        # Prove outbound non-loopback HTTP/HTTPS is genuinely blocked in this environment
        with pytest.raises(requests.RequestException):
            requests.get(
                "https://raw.githubusercontent.com/biolink/biolink-model/v4.2.2/predicate_mapping.yaml",
                timeout=2.0,
            )

        summary = asyncio.run(
            run_benchmark_run(
                candidate="shared-base",
                worktree=REPO_ROOT,
                mode="healthy",
                seed=101,
                kestrel_port=kp,
                api_port=ap,
                out_root=Path(out_dir_str),
                window_s=1.5,
            )
        )

    assert summary["health_total_count"] > 0
    assert summary["health_ok_count"] == summary["health_total_count"]
    assert summary["kestrel_requests_completed"] > 0
    assert summary["kestrel_requests_errored"] == 0
    assert summary["non_kestrel_rps"] > 0.0
