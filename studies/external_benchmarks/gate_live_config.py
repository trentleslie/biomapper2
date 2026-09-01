"""Unit B1 — operator arms-config parsing for the live conflation-gate harness.

Config-driven + topology-agnostic (R-D1). Each arm is a FRESH DEPLOY identified by its
``deployed_commit`` — the harness never assumes an in-place env toggle flips baseline into treatment.
``api_base`` may repeat (one endpoint redeployed between arms — the restart topology) or differ
(two concurrent endpoints); both are valid. ``baseline`` + ``treatment`` are mandatory; the optional
positive-control ``plant`` arm is synthesised from the baseline downstream (Unit B4), not deployed.

Pure/offline: this only parses + validates a mapping the operator supplies. No network.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

_REQUIRED_ARMS = ("baseline", "treatment")
_REQUIRED_FIELDS = ("api_base", "kestrel_url", "deployed_commit", "attestation_token")


@dataclass(frozen=True)
class ArmSpec:
    """One deployed arm: where to resolve, which build, and the operator's cold attestation token."""

    name: str
    api_base: str
    kestrel_url: str
    deployed_commit: str
    attestation_token: str


def _parse_arm(name: str, raw: Mapping) -> ArmSpec:
    values: dict[str, str] = {}
    for field in _REQUIRED_FIELDS:
        val = raw.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            raise ValueError(f"arm {name!r} is missing required field {field!r} (fresh-deploy + attested)")
        values[field] = str(val).strip()
    return ArmSpec(name=name, **values)


def parse_arms_config(config: Mapping[str, Mapping]) -> dict[str, ArmSpec]:
    """Parse + validate the operator arms config into ``{arm_name: ArmSpec}``.

    Requires a ``baseline`` and a ``treatment`` arm, each carrying all of ``api_base``, ``kestrel_url``,
    ``deployed_commit``, ``attestation_token`` (non-blank). Raises ``ValueError`` on any omission before
    the harness touches the network, so a misconfigured run fails at parse time, not mid-resolve.
    """
    for required in _REQUIRED_ARMS:
        if required not in config:
            raise ValueError(f"arms config missing required arm {required!r}")
    return {name: _parse_arm(name, raw) for name, raw in config.items()}
