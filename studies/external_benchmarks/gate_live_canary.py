"""Unit B2 — cold attestation for the live conflation-gate harness (R-D3).

The per-arm attestation token is the operator's COLD claim for that arm's resolve window. It is NOT
a measurement: the real, independent cold defense is fresh-deploy-per-arm (cold by construction) plus
the A2 byte-identical-cache guard. This module only turns the config token into the arm's
``canary_reading`` and records which arms fail to match the pre-registered cold sentinel — refusing a
blank/absent token so a run can never auto-"cold" itself into a pass.

Pure/offline: no network, no clock.
"""

from __future__ import annotations

from collections.abc import Mapping

from .gate_live_config import ArmSpec


def attested_canary(spec: ArmSpec) -> str:
    """Return the arm's attestation token as its canary reading; raise on a blank/absent token.

    A missing attestation is a hard error, never an implicit cold: the operator must positively claim
    the arm ran cold (and match the pre-registered sentinel downstream via ``canary_ok``).
    """
    token = (spec.attestation_token or "").strip()
    if not token:
        raise ValueError(f"arm {spec.name!r} has no cold attestation token — refusing an implicit 'cold'")
    return token


def canary_readings(arms: Mapping[str, ArmSpec]) -> dict[str, str]:
    """Map each arm to its attested canary reading (raising on any blank token)."""
    return {name: attested_canary(spec) for name, spec in arms.items()}


def canary_mismatches(readings: Mapping[str, str], expected: str) -> list[str]:
    """Return the arms whose attested reading != the pre-registered cold sentinel (for the manifest).

    Recorded as a human-claim discrepancy, not a gate by itself — ``canary_ok`` already ABSTAINs on a
    per-arm mismatch, and the byte-identical-cache guard is independent of this attestation.
    """
    return [name for name, reading in readings.items() if reading != expected]
