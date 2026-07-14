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
# Assumed USD cost per external fallback call (one MW or PubChem lookup). The public
# structure APIs are nominally free, but a strictly-zero price makes DEFAULT_CAP_USD inert:
# the USD backstop could never fire no matter how many external fallbacks a run incurs. A
# conservative non-zero default keeps the cap live (retries / rate-limit backoff / any
# metered proxy are real costs); tune per deployment.
DEFAULT_PER_EXTERNAL_CALL_USD: float = 0.001


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
    per_external_call_usd: float = DEFAULT_PER_EXTERNAL_CALL_USD,
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
            f"estimated cost ${est.est_cost_usd:.2f} exceeds cap ${cap_usd:.2f} — halt for authorization",
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


# ---------------------------------------------------------------------------
# Gene/protein Phase-0 smoke (cross-category feasibility).
#
# The feasibility review flagged symbol -> UniProt resolution as UNVERIFIED (a gene symbol
# resolving to a *protein* namespace crosses Biolink categories). So the gene/protein arm gets
# its own gate: resolve a few HGNC symbols live and assert each yields BOTH a non-empty Ensembl
# AND a non-empty UniProt CURIE. Fail loud with the offending symbol; never proceed on a symbol
# that produced neither cross-ref (that would silently score the arm at 0% for an infra reason).
# ---------------------------------------------------------------------------

# Default probe symbols (stable, well-annotated human genes with clear Ensembl + UniProt xrefs).
DEFAULT_GENE_SYMBOLS: tuple[str, ...] = ("TP53", "BRCA1", "EGFR", "INS", "TNF")

# Namespaces the smoke requires each symbol to reach (prefix match, case-insensitive).
REQUIRED_GENE_NAMESPACES: tuple[str, ...] = ("ENSEMBL", "UNIPROTKB")


@dataclass(frozen=True)
class GeneProteinObservation:
    """What a live gene/protein smoke reports back.

    ``per_symbol`` maps each probed symbol to the set of CURIE namespace prefixes BioMapper
    produced for it (e.g. ``{"ENSEMBL", "NCBIGENE", "UNIPROTKB"}``).
    """

    key_ok: bool
    kestrel_ok: bool
    per_symbol: dict[str, set[str]]


@dataclass(frozen=True)
class GeneProteinGateResult:
    verdict: str  # "proceed" | "stop"
    reason: str
    observation: GeneProteinObservation

    @property
    def passed(self) -> bool:
        return self.verdict == "proceed"


def run_gene_protein_gate(
    smoke_fn: Callable[[], GeneProteinObservation],
    *,
    required_namespaces: tuple[str, ...] = REQUIRED_GENE_NAMESPACES,
) -> GeneProteinGateResult:
    """Assert every probed symbol reached each required namespace. Fail loud, name the gap."""
    obs = smoke_fn()
    if not obs.key_ok:
        return GeneProteinGateResult("stop", "KESTREL_API_KEY missing/invalid", obs)
    if not obs.kestrel_ok:
        return GeneProteinGateResult("stop", "Kestrel API unreachable", obs)
    if not obs.per_symbol:
        return GeneProteinGateResult("stop", "gene/protein smoke produced no results (empty)", obs)

    required = {ns.upper() for ns in required_namespaces}
    for symbol, namespaces in obs.per_symbol.items():
        present = {ns.upper() for ns in namespaces}
        missing = required - present
        if missing:
            return GeneProteinGateResult(
                "stop",
                f"symbol {symbol!r} resolved to {sorted(present)} but is missing required "
                f"namespace(s) {sorted(missing)} — cross-category symbol->UniProt unverified",
                obs,
            )
    return GeneProteinGateResult(
        "proceed",
        f"all {len(obs.per_symbol)} probe symbols reached {sorted(required)}",
        obs,
    )


def _namespace_of(curie: str) -> str | None:
    s = str(curie).strip()
    if ":" not in s:
        return None
    return s.split(":", 1)[0].strip().upper()


def build_live_gene_protein_smoke_fn(
    mapper,
    *,
    symbols: tuple[str, ...] = DEFAULT_GENE_SYMBOLS,
    entity_type: str = "gene",
    vocabs: tuple[str, ...] = ("ENSEMBL", "NCBIGene", "UniProtKB"),
) -> Callable[[], GeneProteinObservation]:
    """Wire a live gene/protein smoke closure over the real Mapper (network path).

    Not exercised by unit tests. Resolves each symbol and collects the namespace prefixes of the
    chosen id + its KG equivalent ids, so the gate can assert Ensembl AND UniProt coverage.
    """
    from biomapper2.config import get_kestrel_api_key

    def _smoke() -> GeneProteinObservation:
        key_ok = True
        try:
            get_kestrel_api_key()
        except Exception:
            key_ok = False

        kestrel_ok = True
        per_symbol: dict[str, set[str]] = {}
        for sym in symbols:
            namespaces: set[str] = set()
            try:
                res = mapper.map_entity_to_kg(
                    item={"name": sym},
                    name_field="name",
                    provided_id_fields=[],
                    entity_type=entity_type,
                    vocab=list(vocabs),
                    annotation_mode="all",
                )
                chosen = res.get("chosen_kg_id") if isinstance(res, dict) else None
                ns = _namespace_of(chosen) if chosen else None
                if ns:
                    namespaces.add(ns)
                equiv = (res.get("kg_equivalent_ids") if isinstance(res, dict) else None) or {}
                for _k, ids in equiv.items():
                    values = ids if isinstance(ids, (list, tuple, set)) else [ids]
                    for v in values:
                        vns = _namespace_of(v)
                        if vns:
                            namespaces.add(vns)
            except Exception:
                kestrel_ok = False
            per_symbol[sym] = namespaces
        return GeneProteinObservation(key_ok=key_ok, kestrel_ok=kestrel_ok, per_symbol=per_symbol)

    return _smoke
