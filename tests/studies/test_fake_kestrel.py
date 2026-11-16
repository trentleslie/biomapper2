"""Tests for Fake Kestrel fault injection server.

Verifies cassette digest integrity, healthy endpoint responses, fault modes,
health endpoint fault participation, deck ratio, and admin overrides.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from studies.kestrel_fault_benchmark.fake_kestrel import create_app


@pytest.fixture
def fake_client() -> TestClient:
    app = create_app()
    return TestClient(app)


def test_fake_kestrel_sha256_verification() -> None:
    """Fake Kestrel raises RuntimeError on payload digest mismatch."""
    with patch("studies.kestrel_fault_benchmark.fake_kestrel.EXPECTED_PAYLOAD_SHA256", "bad_hash_123"):
        with pytest.raises(RuntimeError, match="Cassette sha256 mismatch"):
            create_app()


def test_fake_kestrel_healthy_mode_endpoints(fake_client: TestClient) -> None:
    """Fake Kestrel serves deterministic real responses across all endpoints in healthy mode."""
    h_resp = fake_client.get("/api/health")
    assert h_resp.status_code == 200
    assert h_resp.json()["status"] == "healthy"

    cat_resp = fake_client.get("/categories")
    assert cat_resp.status_code == 200
    assert "biolink:Disease" in cat_resp.json()

    search_resp = fake_client.post(
        "/hybrid-search",
        json={"search_text": ["leukemia"], "category": "biolink:Disease", "limit": 20},
    )
    assert search_resp.status_code == 200
    assert len(search_resp.json()["leukemia"]) == 20

    canon_resp = fake_client.post("/api/canonicalize", json={"curies": ["CHEBI:13127"]})
    assert canon_resp.status_code == 200
    assert canon_resp.json()["CHEBI:13127"] == "CHEBI:13127"


def test_fake_kestrel_slow_mode(fake_client: TestClient) -> None:
    """slow-30s mode delays responses by configured slow_delay_s."""
    admin_resp = fake_client.post("/__admin/mode", json={"mode": "slow-30s", "slow_delay_s": 0.15})
    assert admin_resp.status_code == 200

    t0 = time.monotonic()
    r = fake_client.get("/api/categories")
    elapsed = time.monotonic() - t0
    assert r.status_code == 200
    assert elapsed >= 0.14


def test_fake_kestrel_50_pct_5xx_deck_ratio(fake_client: TestClient) -> None:
    """Error mode guarantees exact equal block ratio over chunks."""
    fake_client.post("/__admin/mode", json={"mode": "50% 5xx", "seed": 42})

    statuses: list[int] = []
    for _ in range(16):
        r = fake_client.post("/canonicalize", json={"curies": ["CHEBI:13127"]})
        statuses.append(r.status_code)

    assert statuses.count(200) == 8
    assert statuses.count(500) == 8
    # Assert every 4-item chunk has exactly two 200s and two 500s
    for i in range(0, 16, 4):
        chunk = statuses[i : i + 4]
        assert chunk.count(200) == 2
        assert chunk.count(500) == 2


def test_fake_kestrel_recovering_mode(fake_client: TestClient) -> None:
    """recovering mode starts slow and flips automatically to healthy after recover_after_s."""
    fake_client.post("/__admin/mode", json={"mode": "recovering", "slow_delay_s": 0.15, "recover_after_s": 0.3})

    # Initially in slow window
    t0 = time.monotonic()
    r1 = fake_client.get("/api/categories")
    e1 = time.monotonic() - t0
    assert r1.status_code == 200
    assert e1 >= 0.14

    # Wait for recovery flip
    time.sleep(0.35)
    t0 = time.monotonic()
    r2 = fake_client.get("/api/categories")
    e2 = time.monotonic() - t0
    assert r2.status_code == 200
    assert e2 < 0.10


def test_fake_kestrel_health_fault_participation(fake_client: TestClient) -> None:
    """GET /health participates in the active fault mode unless overridden."""
    fake_client.post("/__admin/mode", json={"mode": "50% 5xx", "seed": 101})

    # /health yields 5xx and 200 under fault mode
    statuses = [fake_client.get("/health").status_code for _ in range(4)]
    assert 500 in statuses
    assert 200 in statuses

    # Admin endpoints always bypass faults
    assert fake_client.get("/__admin/state").status_code == 200


def test_fake_kestrel_admin_endpoint_overrides(fake_client: TestClient) -> None:
    """endpoint_overrides apply targeted fault behaviors per endpoint."""
    fake_client.post(
        "/__admin/mode",
        json={
            "mode": "healthy",
            "endpoint_overrides": {
                "hybrid-search": "5xx",
                "canonicalize": "healthy",
            },
        },
    )

    r_search = fake_client.post("/hybrid-search", json={"search_text": ["leukemia"]})
    assert r_search.status_code == 500

    r_canon = fake_client.post("/canonicalize", json={"curies": ["CHEBI:13127"]})
    assert r_canon.status_code == 200
