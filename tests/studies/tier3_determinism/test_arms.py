"""Tests for the Arm-A (LLM) and Arm-B (BioMapper) drivers, with injected callables."""

from studies.tier3_determinism import arms
from studies.tier3_determinism.call_model import ModelResponse
from studies.tier3_determinism.models import DecodingParams, ModelSpec, Query

_QUERIES = [
    Query(
        query_id="q1",
        query_name="caffeine",
        entity_type="metabolite",
        target_namespace="CHEBI",
        gold_curie="CHEBI:27732",
    ),
    Query(query_id="q2", query_name="mystery", entity_type="metabolite", target_namespace="CHEBI", gold_curie=None),
]
_SPEC = ModelSpec(provider="openai", model_id="gpt-x", label="gpt")
_TEMPS = [DecodingParams(temperature=0.0), DecodingParams(temperature=0.7)]


def test_run_arm_a_produces_all_repeats_and_scores_vs_gold() -> None:
    def fake_call(spec, messages, decoding, client=None):
        return ModelResponse(text='{"id": "CHEBI:27732"}', prompt_tokens=1, completion_tokens=1, latency_s=0.0)

    calls = arms.run_arm_a([_QUERIES[0]], [_SPEC], _TEMPS, n_repeats=3, call_fn=fake_call)

    # 1 query x 1 model x 2 temps x 3 repeats
    assert len(calls) == 6
    assert {c.repeat_index for c in calls} == {0, 1, 2}
    assert {c.temperature for c in calls} == {0.0, 0.7}
    assert all(c.parsed_curie == "CHEBI:27732" and c.is_correct is True for c in calls)


def test_run_arm_a_marks_none_correct_when_no_gold_and_parses_unknown() -> None:
    def fake_call(spec, messages, decoding, client=None):
        return ModelResponse(text='{"id": "unknown"}', prompt_tokens=1, completion_tokens=1, latency_s=0.0)

    calls = arms.run_arm_a([_QUERIES[1]], [_SPEC], [_TEMPS[0]], n_repeats=1, call_fn=fake_call)

    assert len(calls) == 1
    assert calls[0].parsed_curie is None  # "unknown" -> abstain
    assert calls[0].is_correct is None  # no gold


def test_run_arm_a_records_transport_error() -> None:
    def fake_call(spec, messages, decoding, client=None):
        return ModelResponse(text="", prompt_tokens=None, completion_tokens=None, latency_s=0.1, error="boom")

    calls = arms.run_arm_a([_QUERIES[0]], [_SPEC], [_TEMPS[0]], n_repeats=1, call_fn=fake_call)
    assert calls[0].error == "boom" and calls[0].parsed_curie is None


def test_temperature_unsupported_model_gets_native_none_label_not_zero() -> None:
    """Opus-class models (supports_temperature=False) omit temperature in the provider
    call, so their results must carry the native/None sentinel -- NOT 0.0, which would
    misreport the headline condition and collapse into the temp-0 bucket."""
    opus = ModelSpec(provider="anthropic", model_id="claude-opus-x", label="opus-4.8", supports_temperature=False)

    def fake_call(spec, messages, decoding, client=None):
        return ModelResponse(text='{"id": "CHEBI:27732"}', prompt_tokens=1, completion_tokens=1, latency_s=0.0)

    # Two temps supplied, but the sweep is not expressible: collapses to ONE native decoding.
    calls = arms.run_arm_a([_QUERIES[0]], [opus], _TEMPS, n_repeats=3, call_fn=fake_call)

    assert len(calls) == 3  # 1 query x 1 native decoding x 3 repeats (no temp sweep)
    assert all(c.temperature is None for c in calls)  # native, not 0.0
    assert {c.repeat_index for c in calls} == {0, 1, 2}


def test_temperature_supported_model_keeps_numeric_label() -> None:
    """A temperature-supporting model still records the real numeric temperature."""

    def fake_call(spec, messages, decoding, client=None):
        return ModelResponse(text='{"id": "CHEBI:27732"}', prompt_tokens=1, completion_tokens=1, latency_s=0.0)

    calls = arms.run_arm_a([_QUERIES[0]], [_SPEC], _TEMPS, n_repeats=1, call_fn=fake_call)
    assert {c.temperature for c in calls} == {0.0, 0.7}
    assert None not in {c.temperature for c in calls}


def test_run_arm_b_is_byte_identical_when_resolver_deterministic() -> None:
    def fake_resolve(query: Query) -> str | None:
        return "CHEBI:27732" if query.query_id == "q1" else "CHEBI:99"

    calls = arms.run_arm_b(_QUERIES, n_repeats=4, resolve_fn=fake_resolve)

    assert len(calls) == 8  # 2 queries x 4 repeats
    q1 = [c for c in calls if c.query_id == "q1"]
    assert all(c.chosen_kg_id == "CHEBI:27732" and c.is_correct is True for c in q1)
    assert all(c.is_correct is None for c in calls if c.query_id == "q2")  # no gold


def test_run_arm_b_captures_resolver_exception() -> None:
    def boom(query: Query) -> str | None:
        raise RuntimeError("kestrel unreachable")

    calls = arms.run_arm_b([_QUERIES[0]], n_repeats=2, resolve_fn=boom)
    assert len(calls) == 2
    assert all(c.chosen_kg_id is None and "kestrel" in (c.error or "") for c in calls)
