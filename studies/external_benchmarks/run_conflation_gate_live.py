"""Unit B7 — LIVE, SUPERVISED conflation-gate operator harness (fills the stubs).

This is the ``# pragma: no cover`` driver: it drives Unit E per arm (fresh deploy, cold by
construction) x >=3 replicates against a COLD dev API, captures the raw ``ResolvedRows`` as the cache
for the A2 byte-identical guard, resolves the source-tagged PubChem-by-name oracle (lipids honestly
``refused``; A4 disjointness enforced), scores each replicate, injects the positive-control plant from
the baseline, assembles the arms, and runs the HARDENED pure gate WITH caches. It persists
``prereg.json`` FIRST, then ``result.json``, under a timestamped path (R23) and prints the path.

Only the config-validation entrypoints are unit-tested (they raise a clear operator error with no
config, before any network); the resolve/replicate loop itself is never in pytest — its correctness is
carried by the pure units A1-A4 + B1-B6, exercised through the orchestrator.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .conflation_gate import GateResult
from .gate_live_config import parse_arms_config

_PREFIX = "conflation_gate_live_"


def _require_config(config: Mapping | None) -> dict:
    """Validate the operator arms config; raise a clear operator error when it is absent/empty.

    Covered by unit tests: a no-config call must fail here, BEFORE any network, so a stray import or a
    misinvoked stub can never start a live run by accident.
    """
    if not config:
        raise ValueError(
            "operator error: the live conflation gate requires an arms config "
            "({'baseline': {...}, 'treatment': {...}}); refusing to start a live run without it"
        )
    return dict(parse_arms_config(config))  # validates required fields; raises on omission


def run_live(config: Mapping | None = None, **kwargs: Any) -> GateResult:
    """Operator entry for the whole gate. Validate config (covered), then execute live (uncovered)."""
    arms = _require_config(config)
    return _execute_gate(arms, **kwargs)


def resolve_and_persist_live(config: Mapping | None = None, **kwargs: Any) -> Any:
    """Operator entry for a single-arm resolve+persist. Validate config (covered), then execute live."""
    arms = _require_config(config)
    return _execute_resolve(arms, **kwargs)


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _out_dir() -> Path:  # pragma: no cover - filesystem side effect on the live path
    override = os.environ.get("CONFLATION_GATE_OUT")
    root = Path(override).expanduser() if override else Path.home() / "external_benchmark_runs"
    return root / f"{_PREFIX}{_now_ts()}"


def _execute_resolve(arms, **kwargs):  # pragma: no cover - supervised live network step
    """Resolve+persist one arm's panels via the dev API + source-tagged oracle (mirror Unit E)."""
    raise NotImplementedError(
        "resolve_and_persist_live is the supervised per-arm live step; run it from the gated operator "
        "harness with a live COLD dev API + PubChem oracle"
    )


def _execute_gate(arms, *, replicates: int = 3, **kwargs) -> GateResult:  # pragma: no cover - live
    """The supervised resolve/replicate/score/plant/assemble/evaluate/persist loop.

    Never exercised in pytest (network + filesystem). Sketch of the wiring the operator runs:

      * per arm (fresh deploy, cold by construction) x >=``replicates``: resolve panels via
        ``{api_base}/api/v1/map/batch`` (mirror ``xu_necs_certificate_diagnosis._resolve_panel``),
        capture the raw ``ResolvedRows`` as the arm's cache (the A2 guard input);
      * resolve the source-tagged PubChem-by-name oracle (``gate_live_oracle.oracle_by_name``),
        enforce A4 disjointness against the candidate source, ``score_arm`` each replicate;
      * build the plant from the baseline rows + known conflations (``gate_live_plant``) and verify it
        refutes under the SAME oracle (ABORT-worthy if degenerate);
      * assemble arms (``gate_live_assemble.assemble_arms``) + build the prereg/manifest
        (``gate_live_provenance.build_prereg``, pinning per-arm commit + Kestrel fingerprint + masks +
        attestation + known set + baseline refused fraction);
      * ``run_gate(prereg, arms, caches=per_arm_rows)`` — the hardened gate WITH the cache guard;
      * persist ``prereg.json`` FIRST then ``result.json`` under a timestamped dir (R23); print the path.
    """
    out = _out_dir()
    out.mkdir(parents=True, exist_ok=True)
    # prereg.json is written BEFORE result.json (R23) so the pre-registered contract is on disk even if
    # the observation step is interrupted.
    raise NotImplementedError(
        f"the live resolve/replicate loop is a supervised operator step (out dir {out}); wire it to a "
        "live COLD dev API per arm + PubChem oracle and it will persist prereg.json then result.json"
    )


def _persist(out: Path, prereg_manifest: dict, result: GateResult) -> Path:  # pragma: no cover - live
    """Persist prereg.json FIRST, then result.json (R23). Returns the run directory."""
    (out / "prereg.json").write_text(json.dumps(prereg_manifest, indent=2, default=str))
    (out / "result.json").write_text(
        json.dumps(
            {
                "decision": result.decision,
                "deltas": dict(result.deltas),
                "noise_floor": dict(result.noise_floor),
                "excluded_pairs": [list(p) for p in result.excluded_pairs],
                "positive_control_ok": result.positive_control_ok,
                "reasons": list(result.reasons),
            },
            indent=2,
        )
    )
    print(f"[done] {out}/result.json", flush=True)
    return out
