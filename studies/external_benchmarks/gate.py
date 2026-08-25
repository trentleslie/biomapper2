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
    error: str | None = None  # first smoke exception (so the gate reason names the real cause)


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
        detail = f" (smoke error: {obs.error})" if obs.error else ""
        return GateResult("stop", f"Kestrel smoke call failed{detail}", None, obs)
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

    from biomapper2.config import KESTREL_API_URL, get_kestrel_api_key
    from biomapper2.utils import kestrel_host_accepts_credentials

    def _smoke() -> SmokeObservation:
        # A key is only *required* when the configured host actually accepts one. The public
        # endpoint is keyless, so an unset key there is correct, not a failure. (This used to be a
        # try/except around get_kestrel_api_key(), which stopped raising when the key became
        # optional — leaving key_ok permanently True and this precondition dead.)
        key_ok = get_kestrel_api_key() is not None or not kestrel_host_accepts_credentials(KESTREL_API_URL)

        kg_latencies: list[float] = []
        fallback_latencies: list[float] = []
        kestrel_ok = True
        any_result = False
        first_error: str | None = None

        def _time_map(name: str) -> float:
            nonlocal kestrel_ok, any_result, first_error
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
            except Exception as exc:  # capture the real cause — not every failure is unreachability
                kestrel_ok = False
                if first_error is None:
                    first_error = f"{type(exc).__name__}: {exc}"
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
            error=first_error,
        )

    return _smoke


# ---------------------------------------------------------------------------
# Gene/protein Phase-0 smoke (cross-category feasibility).
#
# The feasibility review flagged symbol -> UniProt resolution as UNVERIFIED (a gene symbol
# resolving to a *protein* namespace crosses Biolink categories). So the gene/protein arm gets
# its own gate: resolve a few HGNC symbols live and assert they reach the cross-category cross-ref
# namespaces (Ensembl, UniProt) at a reasonable rate. Fail loud, name the namespace + the observed
# rate; never proceed on a batch path that cannot produce those cross-refs (that would silently
# score the arm near 0% for an infra reason).
#
# CRITICAL: the smoke MUST observe the SAME path the arm runs on — the BATCH
# ``mapper.map_dataset_to_kg`` path (see runner.run_vocab), NOT the single-entity
# ``map_entity_to_kg`` path. The single-entity probe under-populates the equivalent-ID namespaces
# relative to the batch path (it tends to return only NCBIGene), so gating the batch arm on the
# single-entity path is a false-negative that blocks a working capability. A live batch run scored
# HGNC symbol resolution at 96.3% overall (per-namespace: UniProtKB ~90.6%, Ensembl ~76.7%), so the
# batch path DOES cross the category boundary at high rates. The gate therefore probes via the batch
# path and asserts a per-namespace coverage FLOOR that sits below real batch capability but well
# above a broken path (~0%) — so it still STOPs loudly if the batch path genuinely can't resolve
# gene symbols to cross-refs, without false-negativing on the path the arm actually uses.
#
# The smoke runs ONE batch call per target vocab and keeps each call's results ISOLATED (a
# ``VocabProbe`` per vocab): each required namespace's coverage floor is checked against the call
# that TARGETS it (never merged across calls), and a failure in a NON-gated call (e.g. NCBIGene) is
# not allowed to abort the gate — only a gated call's failure, or a genuine Kestrel-unreachable
# condition (no call succeeded), stops the run. (Greptile PR #18.)
# ---------------------------------------------------------------------------

# Default probe symbols (stable, well-annotated human genes with clear Ensembl + UniProt xrefs).
DEFAULT_GENE_SYMBOLS: tuple[str, ...] = ("TP53", "BRCA1", "EGFR", "INS", "TNF")

# Cross-category cross-ref namespaces the batch smoke must cover at a reasonable rate (prefix match,
# case-insensitive). These are the non-trivial targets: a gene *symbol* resolving into the *protein*
# namespace (UniProtKB) is the specific risk the feasibility review flagged; Ensembl gene is the
# second held-out target. NCBIGene is intentionally NOT gated here — it is the same-category "free"
# cross-ref the single-entity path already returned, so requiring it proves nothing about the risk.
REQUIRED_GENE_NAMESPACES: tuple[str, ...] = ("ENSEMBL", "UNIPROTKB")

# Minimum fraction of probe symbols that must reach EACH required namespace via the BATCH path.
# Calibrated below live batch capability (per-namespace: UniProtKB ~90.6%, Ensembl ~76.7% on the
# full HGNC set; these 5 probes are top-tier genes so should resolve even higher) but well above a
# broken path (~0%). The gate STOPs loudly if the batch path cannot produce cross-category cross-refs
# while never false-negativing on the working batch path the arm runs on.
DEFAULT_MIN_NAMESPACE_COVERAGE: float = 0.6


@dataclass(frozen=True)
class VocabProbe:
    """Result of ONE batch ``map_dataset_to_kg`` call for a single target vocab.

    ``ok`` is False iff that specific call raised (call-level isolation — one vocab's failure is
    not the others'). ``per_symbol`` maps each probe symbol to the set of CURIE namespace prefixes
    observed in *this call's* output (``chosen_kg_id`` + every ``kg_equivalent_ids``).

    Coverage for a required namespace is only ever counted from the probe of the call that TARGETS
    that namespace — never merged across calls — so a broken Ensembl-target call cannot be masked by
    Ensembl equivalents that happen to surface in the UniProt or NCBIGene call.
    """

    ok: bool
    per_symbol: dict[str, set[str]]


@dataclass(frozen=True)
class GeneProteinObservation:
    """What a live gene/protein smoke reports back.

    ``per_vocab`` maps each queried vocab (e.g. ``"ENSEMBL"``) to its ``VocabProbe`` — the namespaces
    that vocab's *own* batch ``map_dataset_to_kg`` call produced per symbol, plus whether the call
    succeeded. Keeping the results per-call (not merged) is what lets the gate hold each namespace's
    coverage floor against the call that guards it. ``kestrel_ok`` is False only when Kestrel is
    genuinely unreachable — i.e. NO vocab call succeeded; a single non-gated call throwing does not
    clear it.
    """

    key_ok: bool
    kestrel_ok: bool
    per_vocab: dict[str, VocabProbe]


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
    min_namespace_coverage: float = DEFAULT_MIN_NAMESPACE_COVERAGE,
) -> GeneProteinGateResult:
    """Assert the BATCH path resolves probe symbols to each required cross-ref namespace at a
    reasonable rate. Fail loud, name the namespace + the observed rate.

    Two properties the gate must hold (Greptile PR #18):

    1. **Coverage is per-target-call, never merged.** Each required namespace's floor is checked
       against the probe of the call that TARGETS it (Ensembl floor from the ``ENSEMBL`` call,
       UniProt floor from the ``UniProtKB`` call). Equivalents that leak into a *different* vocab's
       call can never satisfy a namespace whose own target call is broken.
    2. **A non-gated call's failure never aborts the gate.** Only a failure that prevents evaluating
       a GATED namespace (its target call threw), or a genuine Kestrel-unreachable condition (no call
       succeeded at all), stops the run. A transient throw in the NCBIGene call — which is not gated —
       is ignored when the gated Ensembl + UniProt calls passed with sufficient coverage.

    A coverage floor (not per-symbol all-or-nothing) is the right assertion: a couple of the 5 probes
    missing a namespace is normal batch behaviour (~77-91% per-namespace live), but a target call that
    resolves NO symbols to its namespace (~0%) is a real infra failure and MUST STOP — else the arm
    would silently score near 0% for an infra reason.
    """
    obs = smoke_fn()
    if not obs.key_ok:
        return GeneProteinGateResult("stop", "KESTREL_API_KEY missing/invalid", obs)
    if not obs.per_vocab:
        return GeneProteinGateResult("stop", "gene/protein smoke produced no results (empty)", obs)
    if not obs.kestrel_ok:
        return GeneProteinGateResult("stop", "Kestrel API unreachable (no batch call succeeded)", obs)

    # Associate each required namespace with the vocab call that TARGETS it (case-insensitive on the
    # vocab label). Coverage is only ever read from that call's own probe — finding #1.
    probe_by_ns = {vocab.upper(): (vocab, probe) for vocab, probe in obs.per_vocab.items()}

    stats: dict[str, tuple[int, int]] = {}  # namespace -> (hits, n)
    for raw_ns in required_namespaces:
        ns = raw_ns.upper()
        entry = probe_by_ns.get(ns)
        if entry is None:
            return GeneProteinGateResult(
                "stop",
                f"no batch call targeted required namespace {ns!r} — cannot evaluate its coverage; "
                f"probed vocabs were {sorted(obs.per_vocab)}",
                obs,
            )
        vocab, probe = entry
        # finding #2: a GATED namespace's target call failing IS fatal (we cannot judge the arm the
        # gate guards). A non-gated call (e.g. NCBIGene) failing never reaches here, so it is ignored.
        if not probe.ok:
            return GeneProteinGateResult(
                "stop",
                f"batch call for gated vocab {vocab!r} failed — cannot evaluate {ns} coverage on the "
                f"batch path this gate guards",
                obs,
            )
        n = len(probe.per_symbol)
        hits = sum(1 for names in probe.per_symbol.values() if ns in {x.upper() for x in names})
        stats[ns] = (hits, n)

    low = {ns: (h, n) for ns, (h, n) in stats.items() if n == 0 or (h / n) < min_namespace_coverage}
    if low:
        detail = ", ".join(f"{ns} {(h / n if n else 0.0):.0%} ({h}/{n})" for ns, (h, n) in sorted(low.items()))
        return GeneProteinGateResult(
            "stop",
            f"batch path resolved probe symbols to required namespace(s) below the "
            f"{min_namespace_coverage:.0%} floor (each counted only from its own target call): "
            f"{detail} — cross-category symbol->cross-ref resolution not demonstrated on the batch "
            f"path the arm runs on",
            obs,
        )
    summary = ", ".join(f"{ns} {(h / n if n else 0.0):.0%}" for ns, (h, n) in sorted(stats.items()))
    return GeneProteinGateResult(
        "proceed",
        f"batch path resolved probe symbols to {sorted(stats)} at/above the "
        f"{min_namespace_coverage:.0%} floor (per target call): {summary}",
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
    name_column: str = "symbol",
    vocabs: tuple[str, ...] = ("ENSEMBL", "NCBIGene", "UniProtKB"),
) -> Callable[[], GeneProteinObservation]:
    """Wire a live gene/protein smoke closure over the real Mapper's BATCH path.

    Probes the symbols through ``mapper.map_dataset_to_kg`` — the SAME path the backbone arm runs on
    (``runner.run_vocab``) — NOT the single-entity ``map_entity_to_kg`` path. Runs the probe symbols
    as a small dataset per target vocab into a throwaway temp dir, reads each ``*_MAPPED`` split, and
    collects per symbol the namespace prefixes of ``chosen_kg_id`` + every ``kg_equivalent_ids``
    (reusing ``curie_scorer.predicted_curies``, exactly as the scorer does), so the gate asserts real
    batch-path Ensembl/UniProt coverage rather than the impoverished single-entity view.

    Not exercised by the offline suite over a live Mapper (needs Kestrel + network); the batch
    namespace-extraction + gate decision are covered offline with a fake mapper.
    """
    import tempfile
    from pathlib import Path

    import pandas as pd

    from biomapper2.config import KESTREL_API_URL, get_kestrel_api_key
    from biomapper2.utils import kestrel_host_accepts_credentials

    from .scorers.curie_scorer import predicted_curies

    def _smoke() -> GeneProteinObservation:
        # See build_live_smoke_fn: a key is required only for a host that accepts one.
        key_ok = get_kestrel_api_key() is not None or not kestrel_host_accepts_credentials(KESTREL_API_URL)

        input_df = pd.DataFrame({name_column: list(symbols)})
        per_vocab: dict[str, VocabProbe] = {}

        with tempfile.TemporaryDirectory() as tmp:
            for vocab in vocabs:
                # One batch call PER vocab, kept isolated: its namespaces and its ok-flag stay with
                # this vocab so the gate can hold each namespace's floor against its own target call
                # and never abort on a non-gated call's failure.
                per_symbol: dict[str, set[str]] = {sym: set() for sym in symbols}
                ok = True
                try:
                    output_tsv, _stats = mapper.map_dataset_to_kg(
                        dataset=input_df,
                        entity_type=entity_type,
                        name_column=name_column,
                        provided_id_columns=[],
                        vocab=vocab,
                        annotation_mode="all",
                        output_dir=Path(tmp),
                        output_prefix=f"gate_gene_protein_{vocab}",
                    )
                    mapped_df = pd.read_csv(output_tsv, sep="\t")
                    for _, row in mapped_df.iterrows():
                        sym = row.get(name_column)
                        if sym not in per_symbol:
                            continue
                        for curie in predicted_curies(row):
                            ns = _namespace_of(curie)
                            if ns:
                                per_symbol[sym].add(ns)
                except Exception:
                    ok = False
                per_vocab[vocab] = VocabProbe(ok=ok, per_symbol=per_symbol)

        # Kestrel is "unreachable" only if NOTHING succeeded; one non-gated call throwing is not that.
        kestrel_ok = any(probe.ok for probe in per_vocab.values())
        return GeneProteinObservation(key_ok=key_ok, kestrel_ok=kestrel_ok, per_vocab=per_vocab)

    return _smoke
