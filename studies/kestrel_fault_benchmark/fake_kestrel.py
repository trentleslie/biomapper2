"""Fake Kestrel knowledge graph API server for fault injection benchmarking.

Replays recorded real Kestrel responses from fixtures/kestrel_cassette.json.gz,
verifying core_payload_sha256 on load. Implements 5 fault modes (healthy, slow-30s,
hang, 50% 5xx, recovering) and endpoint-level overrides with zero-latency admin control.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import gzip
import hashlib
import json
import logging
import random
import time
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

EXPECTED_PAYLOAD_SHA256 = "2d1abd1da7e925fef354d727bd3fd9bfdf945c351f4b012f4a8b22df375db875"
DEFAULT_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "kestrel_cassette.json.gz"


def canonical_key(method: str, endpoint: str, request_json: dict[str, Any] | None) -> str:
    """Format canonical key for exact response lookup: METHOD:ENDPOINT:JSON_STR."""
    clean_endpoint = endpoint.strip("/").removeprefix("api/").strip("/")
    if request_json is not None:
        body_str = json.dumps(request_json, sort_keys=True, separators=(",", ":"))
    else:
        body_str = ""
    return f"{method.upper()}:{clean_endpoint}:{body_str}"


class FakeKestrelState:
    """Internal state for fault injection and request counting."""

    def __init__(
        self,
        mode: str = "healthy",
        seed: int = 101,
        slow_delay_s: float = 30.0,
        recover_after_s: float = 120.0,
        endpoint_overrides: dict[str, str] | None = None,
    ) -> None:
        self.mode = mode
        self.seed = seed
        self.slow_delay_s = slow_delay_s
        self.recover_after_s = recover_after_s
        self.endpoint_overrides: dict[str, str] = dict(endpoint_overrides or {})
        self.recovering_start_time = time.monotonic()
        self.active_hangs = 0
        self.hang_event = asyncio.Event()
        self.deck_lock = asyncio.Lock()
        self.rng = random.Random(seed)
        self.deck: list[int] = []
        self.request_counts: dict[str, int] = {}

    def effective_behavior(self, endpoint: str) -> str:
        """Resolve effective fault behavior for a given endpoint."""
        override = self.endpoint_overrides.get(endpoint)
        return override if override is not None else self.mode

    def set_mode(
        self,
        mode: str | None = None,
        seed: int | None = None,
        slow_delay_s: float | None = None,
        recover_after_s: float | None = None,
        endpoint_overrides: dict[str, str] | None = None,
    ) -> None:
        """Update fault mode and parameters."""
        old_mode = self.mode
        old_overrides = dict(self.endpoint_overrides)

        if seed is not None:
            self.seed = int(seed)
            self.rng = random.Random(self.seed)
            self.deck.clear()
        if slow_delay_s is not None:
            self.slow_delay_s = float(slow_delay_s)
        if recover_after_s is not None:
            self.recover_after_s = float(recover_after_s)
        if endpoint_overrides is not None:
            self.endpoint_overrides = dict(endpoint_overrides)

        if mode is not None:
            self.mode = mode
            if mode == "recovering":
                self.recovering_start_time = time.monotonic()

        mode_left_hang = old_mode == "hang" and self.mode != "hang"
        override_left_hang = (
            "hang" in old_overrides.values() and self.endpoint_overrides != old_overrides
        )
        if mode_left_hang or override_left_hang:
            self.hang_event.set()
            self.hang_event = asyncio.Event()

    def reset(self) -> None:
        """Reset state to healthy defaults."""
        self.mode = "healthy"
        self.seed = 101
        self.slow_delay_s = 30.0
        self.recover_after_s = 120.0
        self.endpoint_overrides.clear()
        self.recovering_start_time = time.monotonic()
        self.rng = random.Random(self.seed)
        self.deck.clear()
        self.request_counts.clear()
        self.hang_event.set()
        self.hang_event = asyncio.Event()

    def get_state_dict(self) -> dict[str, Any]:
        """Serialize current state."""
        recovering_elapsed = (
            time.monotonic() - self.recovering_start_time if self.mode == "recovering" else 0.0
        )
        return {
            "mode": self.mode,
            "seed": self.seed,
            "slow_delay_s": self.slow_delay_s,
            "recover_after_s": self.recover_after_s,
            "endpoint_overrides": dict(self.endpoint_overrides),
            "active_hangs": self.active_hangs,
            "recovering_elapsed_s": round(recovering_elapsed, 2),
            "request_counts": dict(self.request_counts),
        }


def create_app(cassette_path: Path | str = DEFAULT_FIXTURE_PATH) -> FastAPI:
    """Create FastAPI app wired to cassette payload."""
    path = Path(cassette_path)
    if not path.exists():
        raise FileNotFoundError(f"Cassette fixture not found: {path}")

    with gzip.open(path, "rt", encoding="utf-8") as f:
        cassette_data = json.load(f)

    payload = cassette_data["payload"]
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    actual_sha256 = hashlib.sha256(payload_bytes).hexdigest()

    expected_sha256 = cassette_data.get("provenance", {}).get("core_payload_sha256")
    if actual_sha256 != expected_sha256 or actual_sha256 != EXPECTED_PAYLOAD_SHA256:
        raise RuntimeError(
            f"Cassette sha256 mismatch: actual={actual_sha256}, expected={EXPECTED_PAYLOAD_SHA256}"
        )

    exact_responses = payload.get("exact_responses", {})
    search_scoped = payload.get("search_scoped", {})
    search_fallback = payload.get("search_fallback", {})
    canonicalize_table = payload.get("canonicalize", {})
    get_nodes_table = payload.get("get_nodes", {})
    categories_data = payload.get("categories", [])
    health_data = payload.get("health", {"status": "healthy"})

    state = FakeKestrelState()

    app = FastAPI(title="Fake Kestrel Server")
    app.state.fake_kestrel = state

    # -------------------------------------------------------------------------
    # Admin Endpoints (Always bypass fault injection, <5ms)
    # -------------------------------------------------------------------------

    @app.get("/__admin/state")
    async def admin_get_state() -> JSONResponse:
        return JSONResponse(content=state.get_state_dict())

    @app.post("/__admin/mode")
    async def admin_post_mode(request: Request) -> JSONResponse:
        body: dict[str, Any] = {}
        with contextlib.suppress(Exception):
            body = await request.json()
        state.set_mode(
            mode=body.get("mode"),
            seed=body.get("seed"),
            slow_delay_s=body.get("slow_delay_s"),
            recover_after_s=body.get("recover_after_s"),
            endpoint_overrides=body.get("endpoint_overrides"),
        )
        return JSONResponse(content=state.get_state_dict())

    @app.post("/__admin/reset")
    async def admin_post_reset() -> JSONResponse:
        state.reset()
        return JSONResponse(content=state.get_state_dict())

    # -------------------------------------------------------------------------
    # Fault Injection Handler
    # -------------------------------------------------------------------------

    async def _apply_fault_mode(endpoint: str, request: Request) -> Response | None:
        """Apply active fault mode or override. Returns Response if faulted, None if healthy."""
        state.request_counts[endpoint] = state.request_counts.get(endpoint, 0) + 1

        active_behavior = state.effective_behavior(endpoint)

        if active_behavior == "healthy":
            return None

        if active_behavior in ("5xx", "500"):
            return JSONResponse(
                status_code=500,
                content={"detail": f"Injected Kestrel 500 on {endpoint}"},
            )

        if active_behavior == "hang":
            req_hang_event = state.hang_event
            state.active_hangs += 1
            try:
                while not req_hang_event.is_set() and state.effective_behavior(endpoint) == "hang":
                    if await request.is_disconnected():
                        break
                    await asyncio.sleep(0.05)
            finally:
                state.active_hangs = max(0, state.active_hangs - 1)
            return JSONResponse(
                status_code=504,
                content={"detail": f"Injected Kestrel hang aborted on {endpoint}"},
            )

        if active_behavior == "slow-30s":
            await asyncio.sleep(state.slow_delay_s)
            return None

        if active_behavior == "50% 5xx":
            async with state.deck_lock:
                if not state.deck:
                    state.deck = [200, 200, 500, 500]
                    state.rng.shuffle(state.deck)
                status_code = state.deck.pop(0)

            if status_code == 500:
                return JSONResponse(
                    status_code=500,
                    content={"detail": f"Injected Kestrel 500 on {endpoint}"},
                )
            return None

        if active_behavior == "recovering":
            elapsed = time.monotonic() - state.recovering_start_time
            if elapsed < state.recover_after_s:
                await asyncio.sleep(state.slow_delay_s)
            return None

        return None

    # -------------------------------------------------------------------------
    # Response Dispatchers
    # -------------------------------------------------------------------------

    def _assemble_search(endpoint: str, body: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        search_text: list[str] = body.get("search_text", [])
        category: str = str(body.get("category") or "")
        pref: str = ",".join(sorted(body.get("prefix") or []))
        limit: int | None = body.get("limit")

        scoped_key = f"{endpoint}|{category}|{pref}"
        scoped = search_scoped.get(scoped_key, {})
        fallback = search_fallback.get(endpoint, {})

        result: dict[str, list[dict[str, Any]]] = {}
        for term in search_text:
            nodes = scoped.get(term)
            if nodes is None:
                nodes = fallback.get(term, [])
            if limit is not None and isinstance(nodes, list):
                nodes = nodes[:limit]
            result[term] = list(nodes)
        return result

    def _assemble_canonicalize(body: dict[str, Any]) -> dict[str, str | None]:
        curies: list[str] = body.get("curies", [])
        return {c: canonicalize_table.get(c) for c in curies}

    def _assemble_get_nodes(body: dict[str, Any]) -> dict[str, Any]:
        curies: list[str] = body.get("curies", [])
        return {c: get_nodes_table[c] for c in curies if c in get_nodes_table}

    async def _handle_request(
        endpoint: str,
        request: Request,
        default_handler: Any,
    ) -> Response:
        fault_resp = await _apply_fault_mode(endpoint, request)
        if fault_resp is not None:
            return fault_resp

        body: dict[str, Any] | None = None
        if request.method in ("POST", "PUT"):
            with contextlib.suppress(Exception):
                body = await request.json()

        key = canonical_key(request.method, endpoint, body)
        if key in exact_responses:
            rec = exact_responses[key]
            return JSONResponse(
                content=rec["response_json"],
                status_code=rec.get("status_code", 200),
            )

        content = default_handler(body)
        return JSONResponse(content=content, status_code=200)

    # Route definitions supporting both /<endpoint> and /api/<endpoint>
    @app.get("/health")
    @app.get("/api/health")
    async def health_handler(request: Request) -> Response:
        fault_resp = await _apply_fault_mode("health", request)
        if fault_resp is not None:
            return fault_resp
        return JSONResponse(content=health_data, status_code=200)

    @app.get("/categories")
    @app.get("/api/categories")
    async def categories_handler(request: Request) -> Response:
        return await _handle_request("categories", request, lambda _: categories_data)

    @app.post("/text-search")
    @app.post("/api/text-search")
    async def text_search_handler(request: Request) -> Response:
        return await _handle_request("text-search", request, lambda b: _assemble_search("text-search", b or {}))

    @app.post("/hybrid-search")
    @app.post("/api/hybrid-search")
    async def hybrid_search_handler(request: Request) -> Response:
        return await _handle_request("hybrid-search", request, lambda b: _assemble_search("hybrid-search", b or {}))

    @app.post("/vector-search")
    @app.post("/api/vector-search")
    async def vector_search_handler(request: Request) -> Response:
        return await _handle_request("vector-search", request, lambda b: _assemble_search("vector-search", b or {}))

    @app.post("/canonicalize")
    @app.post("/api/canonicalize")
    async def canonicalize_handler(request: Request) -> Response:
        return await _handle_request("canonicalize", request, lambda b: _assemble_canonicalize(b or {}))

    @app.post("/get-nodes")
    @app.post("/api/get-nodes")
    async def get_nodes_handler(request: Request) -> Response:
        return await _handle_request("get-nodes", request, lambda b: _assemble_get_nodes(b or {}))

    return app


class FakeKestrelServer:
    """Convenience wrapper for launching Fake Kestrel in test suites or background tasks."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 18100,
        cassette_path: Path | str = DEFAULT_FIXTURE_PATH,
    ) -> None:
        self.host = host
        self.port = port
        self.app = create_app(cassette_path)
        self.server: uvicorn.Server | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the server asynchronously in the active event loop."""
        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        self.server = uvicorn.Server(config)
        self._task = asyncio.create_task(self.server.serve())
        # Wait until started
        for _ in range(50):
            if self.server.started:
                break
            await asyncio.sleep(0.05)

    async def stop(self) -> None:
        """Stop server cleanly."""
        if self.server:
            self.server.should_exit = True
            if self._task:
                await self._task
                self._task = None


def main() -> None:
    """CLI entrypoint for standalone Fake Kestrel server."""
    parser = argparse.ArgumentParser(description="Fake Kestrel Fault Benchmark Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=18100, help="Port to bind to")
    parser.add_argument("--cassette", default=str(DEFAULT_FIXTURE_PATH), help="Cassette fixture path")
    parser.add_argument("--mode", default="healthy", help="Initial fault mode")
    parser.add_argument("--seed", type=int, default=101, help="Random seed")
    parser.add_argument("--slow-delay-s", type=float, default=30.0, help="Slow delay in seconds")
    parser.add_argument("--recover-after-s", type=float, default=120.0, help="Recovery window in seconds")
    args = parser.parse_args()

    app = create_app(args.cassette)
    state: FakeKestrelState = app.state.fake_kestrel
    state.set_mode(
        mode=args.mode,
        seed=args.seed,
        slow_delay_s=args.slow_delay_s,
        recover_after_s=args.recover_after_s,
    )

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
