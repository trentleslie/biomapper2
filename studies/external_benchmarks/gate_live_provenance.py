"""Unit B5 — Prereg + manifest assembly for the live conflation gate (R-D5, R-A3).

Assembles the pre-registered decision contract (``Prereg``) and a JSON-serialisable manifest that pins
everything needed to audit/reproduce the later verdict:

  * per-arm ``deployed_commit`` + Kestrel build fingerprint (from ``fetch_kg_build_info``, injected so
    unit tests mock it; it degrades to ``unknown`` on a live failure, never raising),
  * the RefMet masks + the declared adjudicable population (A3's fail-closed expectation),
  * the per-arm attestation tokens + the cold sentinel,
  * the known-conflation set (the plant's source), and the baseline refused fraction.

The positive control is the synthetic ``plant`` arm, required to ``FAIL``. Missing thresholds or a
missing / non-covering mask declaration RAISE — the gate is never assembled with a silent default.

Pure/offline apart from the injected ``fetch``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from biomapper2.provenance import KgBuildInfo, fetch_kg_build_info

from .conflation_gate import Prereg, Thresholds
from .gate_live_config import ArmSpec

Pair = tuple[str, str]
FetchFn = Callable[[str], tuple[str, KgBuildInfo]]


def _fingerprint(kestrel_version: str, kg: KgBuildInfo) -> str:
    """A compact build fingerprint: kestrel version + KG version + KG git commit (or 'unknown')."""
    return f"kestrel={kestrel_version};kg_version={kg.kg_version};kg_commit={kg.git_commit}"


def build_prereg(
    *,
    arms: Mapping[str, ArmSpec],
    refmet_masks: Mapping[str, Mapping[Pair, frozenset]],
    adjudicable_pairs: list[Pair],
    known_conflations: list[Pair],
    baseline_refused_fraction: float,
    thresholds: Thresholds | None,
    cold_canary_expected: str,
    pair_ids: tuple[str, ...],
    fetch: FetchFn = fetch_kg_build_info,
) -> tuple[Prereg, dict]:
    """Assemble ``(Prereg, manifest)``; raise on a missing threshold posture or mask declaration."""
    if thresholds is None:
        raise ValueError("thresholds must be declared (pass Thresholds() explicitly) — no silent default gate")
    if not adjudicable_pairs:
        raise ValueError("adjudicable population (mask declaration) is empty — refusing a gate with no A3 scope")

    declared = set(adjudicable_pairs)
    for arm_name in ("baseline", "treatment"):
        mask = refmet_masks.get(arm_name, {})
        missing = declared - set(mask)
        if missing:
            raise ValueError(
                f"arm {arm_name!r} RefMet mask does not cover the declared adjudicable population "
                f"({len(missing)}/{len(declared)} pairs unmasked) — A3 would fail closed; declare it fully"
            )

    adjudicable_tuple = tuple(sorted(declared))
    treatment = arms["treatment"]

    arm_manifest: dict[str, dict] = {}
    treatment_fingerprint = ""
    for name, spec in arms.items():
        kestrel_version, kg = fetch(spec.kestrel_url)
        fp = _fingerprint(kestrel_version, kg)
        arm_manifest[name] = {
            "deployed_commit": spec.deployed_commit,
            "api_base": spec.api_base,
            "kestrel_url": spec.kestrel_url,
            "attestation_token": spec.attestation_token,
            "kg_fingerprint": fp,
        }
        if name == "treatment":
            treatment_fingerprint = fp

    prereg = Prereg(
        pair_ids=pair_ids,
        thresholds=thresholds,
        positive_control_arm="plant",
        positive_control_required="FAIL",
        deployed_commit=treatment.deployed_commit,
        metagraph_fingerprint=treatment_fingerprint,
        cold_canary_expected=cold_canary_expected,
        adjudicable_pairs=adjudicable_tuple,
    )

    manifest = {
        "pair_ids": list(pair_ids),
        "positive_control_arm": "plant",
        "positive_control_required": "FAIL",
        "adjudicable_pairs": [list(p) for p in adjudicable_tuple],
        "refmet_masks": {
            arm: {f"{a}||{b}": sorted(names) for (a, b), names in mask.items()}
            for arm, mask in refmet_masks.items()
        },
        "known_conflations": [list(p) for p in known_conflations],
        "baseline_refused_fraction": baseline_refused_fraction,
        "cold_canary_expected": cold_canary_expected,
        "arms": arm_manifest,
    }
    return prereg, manifest
