"""Unit B2 — cold attestation (operator claim, not a measurement) — pure/offline.

Cold is defended two ways: (1) fresh-deploy per arm (cold by construction) + the operator's per-arm
attestation token, recorded here as a HUMAN CLAIM in ``ArmReplicates.canary_reading``, and (2) the
independent byte-identical-cache guard (A2), which needs no attestation. B2 only handles (1): it
turns the config token into the canary reading, refuses a blank/absent token (never an implicit
"cold"), and records which arms fail to match the pre-registered cold sentinel — without pretending
the token is a measurement.
"""

from __future__ import annotations

import pytest

from studies.external_benchmarks.conflation_gate import Prereg, Thresholds, canary_ok
from studies.external_benchmarks.gate_live_canary import (
    attested_canary,
    canary_mismatches,
    canary_readings,
)
from studies.external_benchmarks.gate_live_config import ArmSpec

_SENTINEL = "COLD_2026-09-01"


def _spec(token: str) -> ArmSpec:
    return ArmSpec(
        name="baseline",
        api_base="http://localhost:8003",
        kestrel_url="http://localhost:8001",
        deployed_commit="aaaa1111",
        attestation_token=token,
    )


def _prereg() -> Prereg:
    return Prereg(
        pair_ids=("necs__xuetal",),
        thresholds=Thresholds(),
        positive_control_arm="plant",
        positive_control_required="FAIL",
        deployed_commit="aaaa1111",
        metagraph_fingerprint="build-2.0.1:abc",
        cold_canary_expected=_SENTINEL,
    )


def test_attested_token_becomes_the_canary_reading():
    assert attested_canary(_spec(_SENTINEL)) == _SENTINEL


def test_attested_reading_feeds_canary_ok_deterministically():
    # An arm attested with the pre-registered sentinel passes canary_ok; a warm/other value fails.
    from studies.external_benchmarks.conflation_gate import ArmReplicates

    arm = ArmReplicates(name="baseline", replicates=(), canary_reading=attested_canary(_spec(_SENTINEL)))
    assert canary_ok(arm, _prereg()) is True


def test_blank_token_raises_no_silent_cold():
    # Positive control: a blank token is NOT an implicit cold attestation.
    with pytest.raises(ValueError, match="attestation"):
        attested_canary(_spec(""))


def test_canary_readings_maps_every_arm():
    arms = {"baseline": _spec(_SENTINEL), "treatment": _spec(_SENTINEL)}
    assert canary_readings(arms) == {"baseline": _SENTINEL, "treatment": _SENTINEL}


def test_canary_mismatches_records_arms_that_miss_the_sentinel():
    # Edge: a mismatched token across arms is RECORDED (for the manifest); the cache guard stays
    # independent of this claim.
    readings = {"baseline": _SENTINEL, "treatment": "WARM_xyz"}
    assert canary_mismatches(readings, _SENTINEL) == ["treatment"]
    assert canary_mismatches({"baseline": _SENTINEL}, _SENTINEL) == []
