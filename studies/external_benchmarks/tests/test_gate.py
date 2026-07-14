"""Unit 0 — Phase-0 gate decision logic (offline; live observation injected)."""

from __future__ import annotations

import dataclasses

from studies.external_benchmarks.gate import (
    DEFAULT_CAP_USD,
    DEFAULT_PER_EXTERNAL_CALL_USD,
    SmokeObservation,
    run_gate,
)


def _obs(**overrides) -> SmokeObservation:
    base = SmokeObservation(
        results_nonempty=True,
        key_ok=True,
        kestrel_ok=True,
        kg_latencies_s=[0.1, 0.12],
        fallback_latencies_s=[0.5, 0.6],
        miss_rate=0.1,
        vocab_count=2,
    )
    return dataclasses.replace(base, **overrides)


def test_happy_path_within_budget_proceeds():
    result = run_gate(lambda: _obs(), n_rows=100)
    assert result.passed
    assert result.verdict == "proceed"
    assert result.estimate is not None
    assert result.estimate.est_wall_clock_s > 0


def test_missing_key_stops_with_clear_reason():
    result = run_gate(lambda: _obs(key_ok=False), n_rows=100)
    assert not result.passed
    assert "key" in result.reason.lower()


def test_kestrel_unreachable_stops():
    result = run_gate(lambda: _obs(kestrel_ok=False), n_rows=100)
    assert not result.passed
    assert "kestrel" in result.reason.lower()


def test_empty_smoke_result_stops_no_fabricated_numbers():
    result = run_gate(lambda: _obs(results_nonempty=False), n_rows=100)
    assert not result.passed
    assert result.estimate is None  # no estimate fabricated when smoke is empty
    assert "empty" in result.reason.lower()


def test_over_wall_clock_ceiling_halts_with_number():
    # 100 rows * 2 vocabs * ~0.6s weighted is small; force over-ceiling with a tiny ceiling.
    result = run_gate(lambda: _obs(), n_rows=100, max_wall_clock_s=1.0)
    assert not result.passed
    assert "wall-clock" in result.reason.lower()
    assert result.estimate is not None
    assert f"{result.estimate.est_wall_clock_s:.0f}" in result.reason


def test_over_cost_cap_halts_with_number():
    # Force a non-zero per-call cost so the USD cap trips.
    result = run_gate(lambda: _obs(miss_rate=1.0), n_rows=100, cap_usd=1.0, per_external_call_usd=1.0)
    assert not result.passed
    assert "cost" in result.reason.lower()
    assert result.estimate is not None
    assert result.estimate.est_cost_usd > 1.0


def test_default_per_call_price_is_nonzero_so_cap_can_fire():
    # Greptile P1 (gate.py:104): a strictly-zero default per-call price makes the USD cap
    # inert — no run could ever be stopped on cost. The default MUST be non-zero.
    assert DEFAULT_PER_EXTERNAL_CALL_USD > 0.0


def test_default_price_lets_expensive_run_trip_usd_cap():
    # With the default (non-zero) per-call price wired in, a large enough run trips the
    # $25 cap without the caller having to pass a price explicitly. This is the exact
    # production path orchestrate uses (it passes DEFAULT_PER_EXTERNAL_CALL_USD).
    result = run_gate(lambda: _obs(miss_rate=1.0), n_rows=10_000)  # uses the module default
    assert not result.passed
    assert "cost" in result.reason.lower()
    assert result.estimate is not None
    assert result.estimate.est_cost_usd > DEFAULT_CAP_USD

    # Regression guard for the fix: a strictly-zero price would have made the cap inert,
    # so the identical run would sail through at $0 — the bug Greptile flagged.
    zero = run_gate(lambda: _obs(miss_rate=1.0), n_rows=10_000, per_external_call_usd=0.0)
    assert zero.estimate is not None
    assert zero.estimate.est_cost_usd == 0.0
    assert zero.passed


def test_estimate_folds_in_fallback_latency():
    # Higher miss-rate must not decrease the wall-clock estimate (fallback is slower).
    low = run_gate(lambda: _obs(miss_rate=0.0), n_rows=100).estimate
    high = run_gate(lambda: _obs(miss_rate=0.5), n_rows=100).estimate
    assert low is not None and high is not None
    assert high.est_wall_clock_s > low.est_wall_clock_s
    assert high.est_external_calls > low.est_external_calls
