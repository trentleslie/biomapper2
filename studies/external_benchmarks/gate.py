"""Unit 0 — Phase-0 live gate.

A standalone gate that MUST pass before any full run touches real data. It resolves
a small fixed metabolite set across >=2 vocabs live (including >=1 name known to miss
the KG, to time the MW/PubChem fallback), records per-call latency for both the fast KG
path and the slow fallback path, estimates full-run wall-clock and external-call load
(folding in the scorer's ~2x-rows MW/PubChem resolutions), checks keys + Kestrel
reachability, and STOPs with the number if the estimate is over budget.

The live observation is injected via ``smoke_fn`` so the gate's *decision logic* is
unit-testable offline. ``build_live_smoke_fn`` wires the real Mapper + StructureResolver.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from dataclasses import dataclass

# Overnight-feasible wall-clock ceiling (seconds). Beyond this we halt for authorization.
DEFAULT_MAX_WALL_CLOCK_S: float = 8 * 60 * 60  # 8 hours
# Hard USD backstop for external-call cost.
DEFAULT_CAP_USD: float = 25.0


@dataclass(frozen=True)
class SmokeObservation:
    """What a live smoke run reports back to the gate.

    ``kg_latencies_s`` / ``fallback_latencies_s`` are per-call wall-clock samples for
    the fast KG path and the slow name-fallback path respectively. ``miss_rate`` is the
    observed fraction of names that fell through to the fallback path.
    """

    results_nonempty: bool
    key_ok: bool
    kestrel_ok: bool
    kg_latencies_s: list[float]
    fallback_latencies_s: list[float]
    miss_rate: float
    vocab_count: int


@dataclass(frozen=True)
class GateEstimate:
    est_wall_clock_s: float
    est_external_calls: int
    est_cost_usd: float
    weighted_latency_s: float


@dataclass(frozen=True)
class GateResult:
    verdict: str  # "proceed" | "stop"
    reason: str
    estimate: GateEstimate | None
    observation: SmokeObservation

    @property
    def passed(self) -> bool:
        return self.verdict == "proceed"


def estimate_run(
    obs: SmokeObservation,
    *,
    n_rows: int,
    per_external_call_usd: float,
) -> GateEstimate:
    """Estimate full-run wall-clock, external-call count, and cost from smoke samples.

    Wall-clock model: ``n_rows * vocab_count * weighted_latency`` for the mapping pass,
    plus the scorer's structure resolutions. The scorer resolves each row's predicted
    structure; misses (miss_rate) incur an MW+PubChem fallback (~2 external calls/row).
    """
    kg_mean = statistics.fmean(obs.kg_latencies_s) if obs.kg_latencies_s else 0.0
    fb_mean = statistics.fmean(obs.fallback_latencies_s) if obs.fallback_latencies_s else kg_mean
    weighted = obs.miss_rate * fb_mean + (1.0 - obs.miss_rate) * kg_mean

    mapping_pass_s = n_rows * obs.vocab_count * weighted
    # Scorer resolves predicted structure once per row per vocab; only misses hit externals.
    scorer_pass_s = n_rows * obs.vocab_count * obs.miss_rate * fb_mean
    est_wall = mapping_pass_s + scorer_pass_s

    # External calls: mapping fallbacks + scorer fallbacks, ~2 external calls per fallback
    # (MW then PubChem). KG-path calls are internal to Kestrel and not counted here.
    fallback_rows = n_rows * obs.vocab_count * obs.miss_rate
    est_calls = int(round(fallback_rows * 2 * 2))  # mapping + scorer, MW+PubChem each
    est_cost = est_calls * per_external_call_usd
    return GateEstimate(
        est_wall_clock_s=est_wall,
        est_external_calls=est_calls,
        est_cost_usd=est_cost,
        weighted_latency_s=weighted,
    )


def run_gate(
    smoke_fn: Callable[[], SmokeObservation],
    *,
    n_rows: int,
    max_wall_clock_s: float = DEFAULT_MAX_WALL_CLOCK_S,
    cap_usd: float = DEFAULT_CAP_USD,
    per_external_call_usd: float = 0.0,
) -> GateResult:
    """Run the smoke observation and decide proceed/stop. Fail loud, never fabricate.

    STOP conditions, in order:
      1. missing key or Kestrel unreachable  -> stop (clear reason)
      2. empty smoke result                   -> stop (clear reason)
      3. estimate over wall-clock ceiling     -> stop (halt-for-authorization, with number)
      4. estimate over USD cap                 -> stop (halt-for-authorization, with number)
    Otherwise proceed.
    """
    obs = smoke_fn()

    if not obs.key_ok:
        return GateResult("stop", "KESTREL_API_KEY missing/invalid", None, obs)
    if not obs.kestrel_ok:
        return GateResult("stop", "Kestrel API unreachable", None, obs)
    if not obs.results_nonempty:
        return GateResult("stop", "smoke run produced no results (empty)", None, obs)

    est = estimate_run(obs, n_rows=n_rows, per_external_call_usd=per_external_call_usd)

    if est.est_wall_clock_s > max_wall_clock_s:
        return GateResult(
            "stop",
            f"estimated wall-clock {est.est_wall_clock_s:.0f}s exceeds ceiling "
            f"{max_wall_clock_s:.0f}s — halt for authorization",
            est,
            obs,
        )
    if est.est_cost_usd > cap_usd:
        return GateResult(
            "stop",
            f"estimated cost ${est.est_cost_usd:.2f} exceeds cap ${cap_usd:.2f} — " f"halt for authorization",
            est,
            obs,
        )

    return GateResult(
        "proceed",
        f"within budget: ~{est.est_wall_clock_s:.0f}s, ~{est.est_external_calls} external "
        f"calls, ~${est.est_cost_usd:.2f}",
        est,
        obs,
    )


def build_live_smoke_fn(
    mapper,
    *,
    vocabs: tuple[str, ...] = ("CHEBI", "HMDB"),
    present_names: tuple[str, ...] = ("glucose", "cholesterol"),
    kg_missing_names: tuple[str, ...] = ("zzz_nonexistent_metabolite_xyz",),
    entity_type: str = "metabolite",
) -> Callable[[], SmokeObservation]:
    """Wire a live smoke closure over the real Mapper (network path).

    Not exercised by unit tests — it is the production entry the gate consumes at run
    time. Times a fast (KG-present) name and a deliberately KG-missing name to sample
    both latency regimes, and probes key + Kestrel reachability.
    """
    import time

    from biomapper2.config import get_kestrel_api_key

    def _smoke() -> SmokeObservation:
        key_ok = True
        try:
            get_kestrel_api_key()
        except Exception:
            key_ok = False

        kg_latencies: list[float] = []
        fallback_latencies: list[float] = []
        kestrel_ok = True
        any_result = False

        def _time_map(name: str) -> float:
            nonlocal kestrel_ok, any_result
            start = time.perf_counter()
            try:
                res = mapper.map_entity_to_kg(
                    item={"name": name},
                    name_field="name",
                    provided_id_fields=[],
                    entity_type=entity_type,
                    vocab=list(vocabs),
                    annotation_mode="all",
                )
                if isinstance(res, dict) and res.get("chosen_kg_id"):
                    any_result = True
                elif hasattr(res, "get") and res.get("chosen_kg_id"):
                    any_result = True
            except Exception:
                kestrel_ok = False
            return time.perf_counter() - start

        for nm in present_names:
            kg_latencies.append(_time_map(nm))
        for nm in kg_missing_names:
            fallback_latencies.append(_time_map(nm))

        total = len(present_names) + len(kg_missing_names)
        miss_rate = len(kg_missing_names) / total if total else 0.0
        return SmokeObservation(
            results_nonempty=any_result,
            key_ok=key_ok,
            kestrel_ok=kestrel_ok,
            kg_latencies_s=kg_latencies,
            fallback_latencies_s=fallback_latencies,
            miss_rate=miss_rate,
            vocab_count=len(vocabs),
        )

    return _smoke
