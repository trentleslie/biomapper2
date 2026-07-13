"""Tests for the well-engineered Arm-A prompt and its answer parser.

NAR reviewers reject strawman baselines, so these lock in the fairness properties:
a clear schema, few-shot exemplars, permission to answer "unknown", and few-shot
exemplars disjoint from the held-out eval set (no leakage).
"""

from studies.tier3_determinism import dataset, prompt
from studies.tier3_determinism.models import Query

_Q = Query(
    query_id="q",
    query_name="caffeine",
    entity_type="metabolite",
    target_namespace="CHEBI",
    gold_curie="CHEBI:27732",
)


def test_messages_include_schema_unknown_and_query_context() -> None:
    messages = prompt.build_messages(_Q)

    assert messages[0]["role"] == "system"
    blob = " ".join(m["content"] for m in messages).lower()
    assert "caffeine" in blob  # the query
    assert "chebi" in blob  # the target namespace
    assert "unknown" in blob  # permission to abstain
    assert "json" in blob  # explicit output schema
    assert len(messages) >= 4  # system + >=1 few-shot exchange + user


def test_few_shot_exemplars_do_not_leak_held_out_queries() -> None:
    held_out_names = {q.query_name.lower() for q in dataset.load_query_set(dataset.HELD_OUT_QUERY_SET)}
    exemplar_blob = " ".join(
        m["content"].lower() for m in prompt.build_messages(_Q) if m["role"] in ("user", "assistant")
    )
    # the only held-out name allowed to appear is the query itself
    leaked = {n for n in held_out_names if n != "caffeine" and n in exemplar_blob}
    assert leaked == set()


def test_parse_answer_extracts_curie_from_clean_json() -> None:
    assert prompt.parse_answer('{"id": "CHEBI:27732"}') == "CHEBI:27732"


def test_parse_answer_handles_code_fence_and_prose() -> None:
    raw = 'Here is my answer:\n```json\n{"id": "CHEBI:16113"}\n```\nHope that helps!'
    assert prompt.parse_answer(raw) == "CHEBI:16113"


def test_parse_answer_returns_none_for_unknown_and_garbage() -> None:
    assert prompt.parse_answer('{"id": "unknown"}') is None
    assert prompt.parse_answer('{"id": ""}') is None
    assert prompt.parse_answer("I could not determine an identifier.") is None


def test_prompt_fingerprint_is_stable_hex() -> None:
    fp = prompt.prompt_fingerprint()
    assert fp == prompt.prompt_fingerprint()
    assert len(fp) == 64 and all(c in "0123456789abcdef" for c in fp)
