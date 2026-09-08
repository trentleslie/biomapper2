"""Unit B1 — operator arms-config parsing/validation (pure/offline).

The arm difference is a DEPLOYED COMMIT (fresh deploy per arm), never an in-place env toggle, so
every arm must carry its own ``deployed_commit`` + ``attestation_token``. ``api_base`` may repeat
(restart topology, one endpoint redeployed between arms) or differ (concurrent endpoints); both parse.
A ``baseline`` and a ``treatment`` are mandatory. Missing required fields raise before any network.
"""

from __future__ import annotations

import pytest

from studies.external_benchmarks.gate_live_config import ArmSpec, parse_arms_config


def _arm(**over):
    base = {
        "api_base": "http://localhost:8003",
        "kestrel_url": "http://localhost:8001",
        "deployed_commit": "aaaa1111",
        "attestation_token": "COLD_baseline",
    }
    base.update(over)
    return base


def _config(**over):
    cfg = {
        "baseline": _arm(deployed_commit="aaaa1111", attestation_token="COLD_baseline"),
        "treatment": _arm(deployed_commit="bbbb2222", attestation_token="COLD_treatment"),
    }
    cfg.update(over)
    return cfg


def test_same_api_base_restart_topology_parses():
    arms = parse_arms_config(_config())
    assert set(arms) == {"baseline", "treatment"}
    assert isinstance(arms["baseline"], ArmSpec)
    assert arms["baseline"].api_base == arms["treatment"].api_base  # same endpoint, redeployed
    assert arms["baseline"].deployed_commit != arms["treatment"].deployed_commit


def test_different_api_base_concurrent_topology_parses():
    cfg = _config(treatment=_arm(api_base="http://localhost:8004", deployed_commit="bbbb2222",
                                 attestation_token="COLD_treatment"))
    arms = parse_arms_config(cfg)
    assert arms["baseline"].api_base != arms["treatment"].api_base


def test_missing_baseline_raises():
    cfg = _config()
    del cfg["baseline"]
    with pytest.raises(ValueError, match="baseline"):
        parse_arms_config(cfg)


def test_missing_treatment_raises():
    cfg = _config()
    del cfg["treatment"]
    with pytest.raises(ValueError, match="treatment"):
        parse_arms_config(cfg)


def test_missing_kestrel_url_raises():
    cfg = _config(baseline=_arm(kestrel_url=None))
    with pytest.raises(ValueError, match="kestrel_url"):
        parse_arms_config(cfg)


def test_missing_attestation_token_raises():
    # Cold must be attested: a missing/blank token is not an implicit cold arm.
    cfg = _config(treatment=_arm(deployed_commit="bbbb2222", attestation_token=""))
    with pytest.raises(ValueError, match="attestation_token"):
        parse_arms_config(cfg)


def test_missing_deployed_commit_raises():
    cfg = _config(baseline=_arm(deployed_commit="", attestation_token="COLD_baseline"))
    with pytest.raises(ValueError, match="deployed_commit"):
        parse_arms_config(cfg)
