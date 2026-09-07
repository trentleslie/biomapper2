"""Unit B7 — LIVE, SUPERVISED conflation-gate operator harness (fills the stubs).

This is the ``# pragma: no cover`` driver: it drives Unit E per arm (fresh deploy, cold by
construction) x >=3 replicates against a COLD dev API, captures the raw ``ResolvedRows`` as the cache
for the A2 byte-identical guard, resolves the source-tagged PubChem-by-name oracle (lipids honestly
``refused``; A4 disjointness enforced), scores each replicate, injects the positive-control plant from
the baseline, assembles the arms, and runs the HARDENED pure gate WITH caches. It persists
``prereg.json`` FIRST, then ``result.json``, under a timestamped path (R23) and prints the path.

The orchestration is factored into ``_build_gate``, whose network / oracle / KG-fingerprint / canary
dependencies are ALL injected. ``_execute_gate`` supplies the live providers; a unit test drives the
same core with monkeypatched fakes (no network) — so the loop is proven to execute end-to-end without
a live call, closing the "advertised harness cannot execute" gap. The data-source inputs (the pair's
two panels, the RefMet masks, the pre-registered adjudicable population, and the known-conflation set)
are OPERATOR/analysis inputs supplied via kwargs, not invented here.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .conflation_gate import GateResult
from .cross_cohort_devapi_sweep import ResolvedRows, score_arm
from .gate_live_assemble import assemble_arms, run_gate
from .gate_live_canary import attested_canary
from .gate_live_config import parse_arms_config
from .gate_live_oracle import enforce_disjoint, oracle_by_name
from .gate_live_plant import build_plant_rows, load_known_conflations, verify_plant_refutes
from .gate_live_provenance import build_prereg, fetch_kg_build_info

_PREFIX = "conflation_gate_live_"

# A resolver is (api_base, names) -> ResolvedRows; the live one POSTs the dev-API batch endpoint, a test
# injects a fake. An oracle resolver exposes block_for_name(name) -> InChIKey block | None.
ResolveFn = Callable[[str, Sequence[str]], ResolvedRows]


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


def _require_kwarg(kwargs: Mapping, name: str) -> Any:
    """Fetch a required operator input, raising a clear error naming what is missing (before network)."""
    if name not in kwargs or kwargs[name] is None:
        raise ValueError(
            f"operator error: the live gate requires '{name}' (analysis input); supply it in the call — "
            "the harness does not invent panels/masks/adjudicable-population/known-conflations"
        )
    return kwargs[name]


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


def _resolve_panel_live(api_base, key, names, *, batch=25, timeout=300):  # pragma: no cover - live network
    """POST the dev-API batch endpoint for ``names`` -> ResolvedRows {name: {chosen_kg_id, ...}}.

    Mirrors ``cross_cohort_certificate_characterization.resolve_panel``: the API key is header-only and
    never persisted; a per-entity ``error`` is kept (an errored name carries chosen_kg_id None so it
    does not link, but the error is not silently dropped).
    """
    import requests

    rows: dict[str, dict] = {}
    names = list(names)
    for i in range(0, len(names), batch):
        chunk = names[i : i + batch]
        resp = requests.post(
            api_base,
            headers={"X-API-Key": key},
            json={
                "entities": [{"name": n, "entity_type": "metabolite"} for n in chunk],
                "options": {"annotation_mode": "all"},
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        for r in resp.json()["results"]:
            rows[r["name"]] = {
                "chosen_kg_id": r.get("chosen_kg_id"),
                "kg_equivalent_ids": r.get("kg_equivalent_ids") or {},
                "error": r.get("error"),
            }
    return rows


def _independent_maps(a_names, b_names, oracle_resolver):
    """Build the source-tagged oracle ONCE over the union of names, enforce A4 disjointness against the
    KG candidate source, and split into per-side name->block maps for ``score_arm``.

    The candidate link structures come from the KG (``chosen_kg_id``), so every name's candidate source
    is ``"kg"``; ``enforce_disjoint`` withholds any oracle block that would grade a name with that same
    source (never, for a PubChem-by-name oracle — but the guard is applied, not assumed).
    """
    names = list(dict.fromkeys([*a_names, *b_names]))
    sourced = oracle_by_name(names, oracle_resolver)
    disjoint = enforce_disjoint(sourced, {n: "kg" for n in names})
    a_independent = {n: disjoint.get(n) for n in a_names}
    b_independent = {n: disjoint.get(n) for n in b_names}
    return a_independent, b_independent


def _build_prereg(
    *,
    arms_specs,
    masks_by_arm,
    adjudicable_pairs,
    known_conflations_path,
    baseline_refused_fraction,
    thresholds,
    cold_canary_expected,
    pair_id,
    fetch=fetch_kg_build_info,
):
    """Build the pre-registration contract + manifest BEFORE any arm is observed (R4/R23).

    ``baseline_refused_fraction`` is a PRE-REGISTERED input (from a prior characterization), NOT computed
    from this run's baseline — pinning it here keeps the A1 refused-rise expectation independent of the
    observation. ``fetch`` reads each arm's KG build identity (a pre-observation pin). Returns
    ``(prereg, manifest, known_conflations)``.
    """
    known = load_known_conflations(known_conflations_path)
    prereg, manifest = build_prereg(
        arms={k: arms_specs[k] for k in ("baseline", "treatment")},
        refmet_masks=masks_by_arm,
        adjudicable_pairs=list(adjudicable_pairs),
        known_conflations=list(known),
        baseline_refused_fraction=baseline_refused_fraction,
        thresholds=thresholds,
        cold_canary_expected=cold_canary_expected,
        pair_ids=(pair_id,),
        fetch=fetch,
    )
    return prereg, manifest, known


def _observe_and_gate(
    prereg,
    *,
    arms_specs,
    a_names,
    b_names,
    replicates,
    resolve_fn,
    oracle_resolver,
    masks_by_arm,
    known,
    shared_prefix="CHEBI",
):
    """Observe (resolve+score) the arms, build+verify the plant, assemble, run the hardened gate.

    Called ONLY after the prereg is built and persisted, so the contract is fixed before observation.
    Returns ``(result, caches)``.
    """
    a_independent, b_independent = _independent_maps(a_names, b_names, oracle_resolver)

    reps_by_arm: dict[str, list] = {}
    caches: dict[str, ResolvedRows] = {}
    canary_by_arm: dict[str, str] = {}
    baseline_rows: dict[str, dict] = {}
    for arm_name in ("baseline", "treatment"):
        spec = arms_specs[arm_name]
        scores = []
        for rep in range(replicates):
            a_rows = resolve_fn(spec.api_base, a_names)
            b_rows = resolve_fn(spec.api_base, b_names)
            scores.append(score_arm(a_rows, b_rows, a_independent, b_independent))
            if rep == 0:
                caches[arm_name] = {**a_rows, **b_rows}
                if arm_name == "baseline":
                    baseline_rows = {**a_rows, **b_rows}
        reps_by_arm[arm_name] = scores
        canary_by_arm[arm_name] = attested_canary(spec)

    # Positive-control plant: force known-bad pairs from the BASELINE rows onto a shared non-structural
    # CURIE so they link, and verify the certificate refutes them under the SAME oracle (raises if the
    # plant is degenerate — never a silent good self-test).
    plant_a, plant_b = build_plant_rows(baseline_rows, known, shared_prefix)
    verify_plant_refutes(plant_a, plant_b, a_independent, b_independent)
    plant_score = score_arm(plant_a, plant_b, a_independent, b_independent)
    reps_by_arm["plant"] = [plant_score] * replicates
    caches["plant"] = {**plant_a, **plant_b}
    canary_by_arm["plant"] = canary_by_arm["baseline"]  # synthetic, derived from the cold baseline rows

    assembled = assemble_arms(reps_by_arm, canary_by_arm, masks_by_arm)
    result = run_gate(prereg, assembled, caches)
    return result, caches


def _run_gate_flow(
    out: Path,
    *,
    arms_specs,
    a_names,
    b_names,
    replicates,
    resolve_fn,
    oracle_resolver,
    masks_by_arm,
    adjudicable_pairs,
    known_conflations_path,
    baseline_refused_fraction,
    thresholds,
    cold_canary_expected,
    pair_id,
    fetch=fetch_kg_build_info,
):
    """Ordered flow: build prereg -> PERSIST prereg.json -> observe+gate -> persist result.json.

    Persisting the prereg BEFORE observation is the pre-registration guarantee (R4/R23): the contract is
    on disk before any arm is resolved, so an interrupted run still leaves its pinned contract, and a
    successful run's contract cannot have been shaped by what was observed. All I/O is injected, so a
    test drives the whole ordered flow offline. Returns the GateResult.
    """
    prereg, manifest, known = _build_prereg(
        arms_specs=arms_specs,
        masks_by_arm=masks_by_arm,
        adjudicable_pairs=adjudicable_pairs,
        known_conflations_path=known_conflations_path,
        baseline_refused_fraction=baseline_refused_fraction,
        thresholds=thresholds,
        cold_canary_expected=cold_canary_expected,
        pair_id=pair_id,
        fetch=fetch,
    )
    out.mkdir(parents=True, exist_ok=True)
    (out / "prereg.json").write_text(json.dumps(manifest, indent=2, default=str))  # BEFORE observation
    result, _caches = _observe_and_gate(
        prereg,
        arms_specs=arms_specs,
        a_names=a_names,
        b_names=b_names,
        replicates=replicates,
        resolve_fn=resolve_fn,
        oracle_resolver=oracle_resolver,
        masks_by_arm=masks_by_arm,
        known=known,
    )
    _persist_result(out, result)
    return result


def _execute_gate(arms, *, replicates: int = 3, **kwargs) -> GateResult:  # pragma: no cover - live
    """Supervised live gate: wire the ordered flow to the real dev API + PubChem oracle.

    Operator kwargs (analysis inputs): ``a_names``/``b_names`` (the pair's two panels), ``masks_by_arm``,
    ``adjudicable_pairs``, ``known_conflations_path``, ``baseline_refused_fraction`` (pre-registered from
    a prior characterization), ``thresholds``, ``cold_canary_expected``, ``pair_id``. The API key is read
    header-only from ``/tmp/.bmk`` and never persisted.
    """
    from .scorers.independent_inchikey import PubChemInChIKeyResolver

    key = Path("/tmp/.bmk").read_text().strip()
    resolver = PubChemInChIKeyResolver()

    def _resolve(api_base, names):
        return _resolve_panel_live(api_base, key, names)

    return _run_gate_flow(
        _out_dir(),
        arms_specs=arms,
        a_names=_require_kwarg(kwargs, "a_names"),
        b_names=_require_kwarg(kwargs, "b_names"),
        replicates=replicates,
        resolve_fn=_resolve,
        oracle_resolver=resolver,
        masks_by_arm=_require_kwarg(kwargs, "masks_by_arm"),
        adjudicable_pairs=_require_kwarg(kwargs, "adjudicable_pairs"),
        known_conflations_path=kwargs.get("known_conflations_path"),
        baseline_refused_fraction=_require_kwarg(kwargs, "baseline_refused_fraction"),
        thresholds=_require_kwarg(kwargs, "thresholds"),
        cold_canary_expected=_require_kwarg(kwargs, "cold_canary_expected"),
        pair_id=_require_kwarg(kwargs, "pair_id"),
    )


def _execute_resolve(arms, **kwargs):  # pragma: no cover - supervised live network step
    """Resolve+persist ONE arm's pair panels via the dev API + source-tagged oracle, score, persist.

    Operator kwargs: ``arm`` (which arm to resolve, default 'treatment'), ``a_names``/``b_names``, plus
    ``pair_id``. Persists a small manifest + the scored counts under a timestamped dir (R23).
    """
    from .scorers.independent_inchikey import PubChemInChIKeyResolver

    key = Path("/tmp/.bmk").read_text().strip()
    arm_name = kwargs.get("arm", "treatment")
    spec = arms[arm_name]
    a_names = _require_kwarg(kwargs, "a_names")
    b_names = _require_kwarg(kwargs, "b_names")
    a_independent, b_independent = _independent_maps(a_names, b_names, PubChemInChIKeyResolver())

    a_rows = _resolve_panel_live(spec.api_base, key, a_names)
    b_rows = _resolve_panel_live(spec.api_base, key, b_names)
    score = score_arm(a_rows, b_rows, a_independent, b_independent)

    out = _out_dir()
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{arm_name}_score.json").write_text(
        json.dumps(
            {
                "arm": arm_name,
                "pair_id": kwargs.get("pair_id"),
                "deployed_commit": spec.deployed_commit,
                "certified": score.certified.certified,
                "refuted": score.certified.refuted,
                "refused": score.certified.refused,
                "note": "api key NOT recorded; scrub internal endpoints before publish",
            },
            indent=2,
        )
    )
    print(f"[done] {out}/{arm_name}_score.json", flush=True)
    return score


def _persist_result(out: Path, result: GateResult) -> Path:
    """Persist result.json (the prereg.json contract is written earlier, before observation). Returns out."""
    out.mkdir(parents=True, exist_ok=True)
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
