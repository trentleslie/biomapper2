"""Unit B6 — assemble scored replicates + the plant into ``ArmReplicates`` and run the hardened gate.

Pure/offline glue between the live-observed ``ArmScore`` replicates (Unit E / B7) and the hardened pure
decision core (``evaluate_conflation_gate``). ``assemble_arms`` packs per-arm replicates + canary
readings + RefMet masks into ``ArmReplicates``; ``run_gate`` runs the gate WITH the per-arm caches so
the byte-identical-cache guard (A2) is live — and REFUSES to produce a verdict without them, because a
live verdict that skipped the cache guard is exactly the confound that invalidated an earlier sweep.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .conflation_gate import ArmReplicates, GateResult, Prereg, evaluate_conflation_gate
from .cross_cohort_devapi_sweep import ArmScore, ResolvedRows

Pair = tuple[str, str]


def assemble_arms(
    replicates_by_arm: Mapping[str, Sequence[ArmScore]],
    canary_by_arm: Mapping[str, str],
    masks_by_arm: Mapping[str, Mapping[Pair, frozenset]] | None = None,
) -> dict[str, ArmReplicates]:
    """Pack per-arm scored replicates + canary readings + RefMet masks into ``ArmReplicates``.

    ``masks_by_arm`` is optional per arm (an arm without a declared mask gets an empty one — A3 fails
    closed at the gate when the prereg declares an adjudicable population the mask does not cover).
    """
    masks = masks_by_arm or {}
    arms: dict[str, ArmReplicates] = {}
    for name, reps in replicates_by_arm.items():
        arms[name] = ArmReplicates(
            name=name,
            replicates=tuple(reps),
            canary_reading=canary_by_arm[name],
            refmet_mask=dict(masks.get(name, {})),
        )
    return arms


def run_gate(
    prereg: Prereg,
    arms: Mapping[str, ArmReplicates],
    caches: Mapping[str, ResolvedRows] | None,
) -> GateResult:
    """Run the hardened gate on assembled arms WITH per-arm caches. Refuse a verdict without caches.

    A live verdict must be defended by the byte-identical-cache guard (A2). Passing ``caches=None``
    here is a wiring error for the live path, so it raises rather than silently skip the guard. (Pure
    unit tests that want the no-cache path call ``evaluate_conflation_gate`` directly.)
    """
    if caches is None:
        raise ValueError(
            "run_gate requires per-arm caches for a live verdict (the byte-identical-cache guard, A2); "
            "refusing to produce a verdict without them"
        )
    return evaluate_conflation_gate(prereg, arms, caches=caches)
