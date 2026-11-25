"""Tests for the unified call_model() routing layer (fake clients, no network)."""

from types import SimpleNamespace

import pytest

from studies.tier3_determinism import call_model as cm
from studies.tier3_determinism.models import DecodingParams, ModelSpec

_MESSAGES = [
    {"role": "system", "content": "sys"},
    {"role": "user", "content": "u1"},
    {"role": "assistant", "content": "a1"},
    {"role": "user", "content": "u2"},
]
_DECODE = DecodingParams(temperature=0.0, top_p=0.9, max_tokens=64, seed=7)


class _FakeOpenAIClient:
    def __init__(self) -> None:
        self.kwargs: dict = {}
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"id": "CHEBI:1"}'))],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=3),
        )


class _FakeAnthropicClient:
    def __init__(self) -> None:
        self.kwargs: dict = {}
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            content=[SimpleNamespace(text='{"id": "CHEBI:2"}')],
            usage=SimpleNamespace(input_tokens=9, output_tokens=4),
        )


def test_openai_route_forwards_decoding_and_extracts_text() -> None:
    client = _FakeOpenAIClient()
    spec = ModelSpec(provider="openai", model_id="gpt-x", label="gpt")

    resp = cm.call_model(spec, _MESSAGES, _DECODE, client=client)

    assert resp.text == '{"id": "CHEBI:1"}'
    assert resp.error is None
    assert client.kwargs["temperature"] == 0.0
    assert client.kwargs["top_p"] == 0.9
    assert client.kwargs["max_tokens"] == 64
    assert client.kwargs["seed"] == 7
    assert client.kwargs["model"] == "gpt-x"
    assert resp.prompt_tokens == 11 and resp.completion_tokens == 3


def test_openrouter_uses_openai_chat_path() -> None:
    client = _FakeOpenAIClient()
    spec = ModelSpec(provider="openrouter", model_id="qwen/qwen3-8b", label="qwen3-8b")

    resp = cm.call_model(spec, _MESSAGES, _DECODE, client=client)

    assert resp.text == '{"id": "CHEBI:1"}'
    assert client.kwargs["model"] == "qwen/qwen3-8b"


def test_anthropic_route_splits_system_and_omits_seed() -> None:
    client = _FakeAnthropicClient()
    spec = ModelSpec(provider="anthropic", model_id="claude-x", label="opus")

    resp = cm.call_model(spec, _MESSAGES, _DECODE, client=client)

    assert resp.text == '{"id": "CHEBI:2"}'
    assert client.kwargs["system"] == "sys"  # system pulled out of messages
    assert all(m["role"] != "system" for m in client.kwargs["messages"])
    assert "seed" not in client.kwargs  # Anthropic API has no seed param
    assert resp.prompt_tokens == 9 and resp.completion_tokens == 4


def test_error_is_captured_not_raised() -> None:
    class _Boom:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._boom))

        def _boom(self, **kwargs):
            raise RuntimeError("429 rate limited")

    spec = ModelSpec(provider="openai", model_id="gpt-x", label="gpt")
    resp = cm.call_model(spec, _MESSAGES, _DECODE, client=_Boom())

    assert resp.text == ""
    assert resp.error is not None and "429" in resp.error
    assert isinstance(resp.latency_s, float)


def test_unknown_provider_rejected() -> None:
    spec = ModelSpec.model_construct(provider="grok", model_id="x", label="x")
    with pytest.raises(ValueError):
        cm.call_model(spec, _MESSAGES, _DECODE, client=_FakeOpenAIClient())


def test_openrouter_sends_default_provider_policy() -> None:
    client = _FakeOpenAIClient()
    spec = ModelSpec(provider="openrouter", model_id="qwen/qwen3-32b", label="q")

    cm.call_model(spec, _MESSAGES, _DECODE, client=client)

    assert client.kwargs["extra_body"] == {"provider": {"quantizations": ["fp8"], "require_parameters": True}}


def test_openrouter_order_pins_and_disables_fallbacks() -> None:
    client = _FakeOpenAIClient()
    spec = ModelSpec(provider="openrouter", model_id="qwen/qwen3-32b", label="q", provider_order=("deepinfra/fp8",))

    cm.call_model(spec, _MESSAGES, _DECODE, client=client)

    pol = client.kwargs["extra_body"]["provider"]
    assert pol["order"] == ["deepinfra/fp8"] and pol["allow_fallbacks"] is False
    assert "order" not in cm.OPENROUTER_BASE_POLICY


def test_openai_route_sends_no_provider_policy() -> None:
    client = _FakeOpenAIClient()
    spec = ModelSpec(provider="openai", model_id="gpt-x", label="gpt")

    cm.call_model(spec, _MESSAGES, _DECODE, client=client)

    assert "extra_body" not in client.kwargs


def test_openrouter_records_served_provider() -> None:
    client = _FakeOpenAIClient()
    orig = client._create

    def _create(**kwargs):
        resp = orig(**kwargs)
        resp.provider = "DeepInfra"
        return resp

    client.chat.completions.create = _create
    spec = ModelSpec(provider="openrouter", model_id="qwen/qwen3-32b", label="q")

    resp = cm.call_model(spec, _MESSAGES, _DECODE, client=client)

    assert resp.served_provider == "DeepInfra"
