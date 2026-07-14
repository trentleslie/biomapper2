"""Tests for the CLI config builder + model registry (no live calls)."""

import pytest

from studies.tier3_determinism import dataset, run


def test_smoke_preset_is_cheap_and_defaults_here() -> None:
    cfg = run.build_config(preset="smoke")
    assert cfg.dataset_path == dataset.HELD_OUT_QUERY_SET
    assert cfg.n_repeats <= 5  # cheap
    assert cfg.limit is not None and cfg.limit <= 3  # only a couple of queries
    assert 0.0 in cfg.temperatures  # temp=0 always included
    assert len(cfg.models) == 1


def test_full_preset_uses_matrix_and_big_n() -> None:
    cfg = run.build_config(preset="full")
    assert cfg.n_repeats >= 20  # N = 20-30 per protocol
    assert cfg.limit is None  # whole set
    assert {m.label for m in cfg.models} >= {"opus-4.8", "gpt-4o", "qwen3-8b"}
    assert 0.0 in cfg.temperatures and any(t > 0 for t in cfg.temperatures)


def test_overrides_apply() -> None:
    cfg = run.build_config(preset="smoke", n_repeats=7, models=["gpt", "opus"], temps=[0.0], no_arm_b=True)
    assert cfg.n_repeats == 7
    assert [m.label for m in cfg.models] == ["gpt-4o", "opus-4.8"]
    assert cfg.temperatures == [0.0]
    assert cfg.run_arm_b is False


def test_unknown_model_label_rejected() -> None:
    with pytest.raises(KeyError):
        run.build_config(preset="smoke", models=["not-a-model"])


def test_missing_provider_keys_reported(monkeypatch) -> None:
    """Preflight should name every provider whose API key is absent, before any spend."""
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    cfg = run.build_config(preset="full")  # opus/sonnet/gpt/qwen -> all three providers
    missing = run.missing_provider_keys(cfg)
    assert set(missing) == {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"}


def test_present_provider_keys_not_reported(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    cfg = run.build_config(preset="smoke")  # gpt only -> openai
    assert run.missing_provider_keys(cfg) == []


def test_preflight_raises_on_missing_keys(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    cfg = run.build_config(preset="smoke", models=["qwen"])
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        run.preflight_keys(cfg)
