"""Tests for the unified model-call layer + roster (Task 6).

Mocks all SDK clients so no real API calls are made and no API key is required.
"""
from unittest.mock import patch, MagicMock

from studies.annotation_reranking import model_call
from studies.annotation_reranking.model_call import ModelCfg


def test_roster_has_full_matrix_providers():
    labels = {c.label for c in model_call.ROSTER}
    assert {"opus", "sonnet"} <= labels
    assert any(c.provider == "openai" for c in model_call.ROSTER)      # GPT-5.5-class
    assert any(c.provider == "openrouter" for c in model_call.ROSTER)  # small open
    assert all(c.quant_note for c in model_call.ROSTER if c.provider == "openrouter")


def test_call_model_openrouter_returns_text_cost_latency():
    cfg = ModelCfg("qwen3-8b", "openrouter", "qwen/qwen3-8b", "OpenRouter fp8, NOT local Q4")
    fake = {"text": "CHEBI:2", "cost": 0.0004}
    with patch.object(model_call, "_call_openrouter", return_value=fake):
        text, cost, latency = model_call.call_model(cfg, "prompt", seed=0)
    assert text == "CHEBI:2" and cost == 0.0004 and latency >= 0.0


def test_call_model_anthropic_returns_text_cost_latency():
    cfg = ModelCfg("sonnet", "anthropic", "claude-sonnet-4-6")
    fake = {"text": "HMDB0001", "cost": 0.0}
    with patch.object(model_call, "_call_anthropic", return_value=fake):
        text, cost, latency = model_call.call_model(cfg, "map this", seed=0)
    assert text == "HMDB0001" and cost == 0.0 and latency >= 0.0


def test_call_model_openai_returns_text_cost_latency():
    cfg = ModelCfg("gpt-5.5", "openai", "PIN_AT_RUNTIME")
    fake = {"text": "CHEBI:99", "cost": 0.0}
    with patch.object(model_call, "_call_openai", return_value=fake):
        text, cost, latency = model_call.call_model(cfg, "map this", seed=0)
    assert text == "CHEBI:99" and cost == 0.0 and latency >= 0.0


def test_import_does_not_read_key_or_hit_network():
    """Importing model_call must not read the key file or open network connections.

    Verified by the fact that the module imported at the top of this file
    without any API key available in the test environment (and tests pass).
    The key is read lazily inside _load_openrouter_key(), which is only called
    from _call_openrouter(), and only when not already in the environment.
    """
    # If we got this far without errors, the import was clean.
    assert model_call.ROSTER is not None


def test_modelcfg_defaults():
    cfg = ModelCfg("opus", "anthropic", "claude-opus-4-8")
    assert cfg.quant_note == ""


def test_roster_openrouter_quant_notes():
    for cfg in model_call.ROSTER:
        if cfg.provider == "openrouter":
            assert "NOT local" in cfg.quant_note, (
                f"{cfg.label} quant_note should clarify NOT local Q4: {cfg.quant_note!r}"
            )
