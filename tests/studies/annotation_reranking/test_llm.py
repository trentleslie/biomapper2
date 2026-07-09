"""Tests for LLM reranker: build_prompt (RM-blinding), parse_selection, LlmReranker.

Revision 2026-07-08: select() returns (selected_id, review_flag) tuple;
LlmReranker always returns (selected_id, None).
"""
from studies.annotation_reranking.rerankers.llm import build_prompt, parse_selection, LlmReranker
from studies.annotation_reranking.models_data import Candidate


def _c(cid, rm):
    # Two RM entries when rm=True so blinding tests cover exhaustive removal.
    return Candidate(
        id=cid,
        score=1.0,
        name=cid,
        equivalent_ids=(["RM:9", "RM:10", "HMDB:1"] if rm else ["HMDB:1"]),
    )


# ---------------------------------------------------------------------------
# build_prompt tests
# ---------------------------------------------------------------------------


def test_blind_strips_rm_ids_from_prompt():
    cands = [_c("CHEBI:1", True), _c("CHEBI:2", False)]
    # Exhaustive check: no RM: prefix of any kind survives blinding.
    assert "RM:" in build_prompt(cands, blind_rm=False)
    assert "RM:" not in build_prompt(cands, blind_rm=True)


def test_non_blind_includes_rm_ids():
    cands = [_c("CHEBI:1", True)]
    prompt = build_prompt(cands, blind_rm=False)
    assert "RM:9" in prompt
    assert "RM:10" in prompt
    assert "HMDB:1" in prompt


def test_prompt_includes_candidate_ids():
    cands = [_c("CHEBI:1", True), _c("CHEBI:2", False)]
    prompt = build_prompt(cands, blind_rm=False)
    assert "CHEBI:1" in prompt
    assert "CHEBI:2" in prompt


# ---------------------------------------------------------------------------
# parse_selection tests
# ---------------------------------------------------------------------------


def test_parse_accepts_in_list_curie():
    cands = [_c("CHEBI:1", True), _c("CHEBI:2", False)]
    assert parse_selection("I choose CHEBI:2 because ...", cands) == "CHEBI:2"


def test_parse_accepts_first_matching_curie():
    cands = [_c("CHEBI:1", True), _c("CHEBI:2", False)]
    # both in prompt — should return whichever appears first in text
    assert parse_selection("CHEBI:1 is better than CHEBI:2", cands) == "CHEBI:1"


def test_parse_rejects_off_list_or_garbage():
    cands = [_c("CHEBI:1", True)]
    assert parse_selection("CHEBI:99999", cands) is None      # hallucinated / off-list
    assert parse_selection("none of these", cands) is None


def test_parse_rejects_empty_text():
    cands = [_c("CHEBI:1", True)]
    assert parse_selection("", cands) is None


# ---------------------------------------------------------------------------
# LlmReranker tests (tuple protocol: (selected_id, None))
# ---------------------------------------------------------------------------


def test_llm_reranker_uses_injected_call_fn():
    cands = [_c("CHEBI:1", True), _c("CHEBI:2", False)]
    # stub returns a 3-tuple for test bookkeeping only; call_fn contract is
    # (model_name: str, prompt: str) -> str, so we pass [0] (the text) to LlmReranker.
    stub = lambda model, prompt: ("CHEBI:2", 0.0, 0.0)  # (text, cost, latency)
    r = LlmReranker("sonnet", call_fn=lambda m, p: stub(m, p)[0], blind_rm=True)
    assert r.name == "llm:sonnet/blind"
    assert r.select(cands) == ("CHEBI:2", None)


def test_llm_reranker_name_non_blind():
    r = LlmReranker("opus", call_fn=lambda m, p: "", blind_rm=False)
    assert r.name == "llm:opus"


def test_llm_reranker_empty_candidates_returns_none_tuple():
    r = LlmReranker("sonnet", call_fn=lambda m, p: "CHEBI:1", blind_rm=False)
    assert r.select([]) == (None, None)


def test_llm_reranker_review_flag_always_none():
    """LLM rerankers never emit a review flag per Revision 2026-07-08."""
    cands = [_c("CHEBI:1", True), _c("CHEBI:2", False)]
    r = LlmReranker("sonnet", call_fn=lambda m, p: "CHEBI:1", blind_rm=False)
    selected_id, review_flag = r.select(cands)
    assert review_flag is None


def test_llm_reranker_off_list_response_returns_none_id():
    """If model returns an off-list CURIE, selected_id is None (parse returns None)."""
    cands = [_c("CHEBI:1", True)]
    r = LlmReranker("sonnet", call_fn=lambda m, p: "CHEBI:99999", blind_rm=False)
    selected_id, review_flag = r.select(cands)
    assert selected_id is None
    assert review_flag is None


def test_llm_reranker_blind_passes_blind_rm_to_prompt():
    """Verify that blind reranker actually strips RM: from the prompt passed to call_fn."""
    captured = {}

    def capturing_fn(model, prompt):
        captured["prompt"] = prompt
        return "CHEBI:1"

    cands = [_c("CHEBI:1", True)]
    r = LlmReranker("sonnet", call_fn=capturing_fn, blind_rm=True)
    r.select(cands)
    assert "RM:9" not in captured["prompt"]


def test_llm_reranker_select_accepts_case_kwarg():
    """select() accepts optional case= kwarg without error (protocol compatibility)."""
    from studies.annotation_reranking.models_data import EvalCase
    cands = [_c("CHEBI:1", True)]
    r = LlmReranker("sonnet", call_fn=lambda m, p: "CHEBI:1", blind_rm=False)
    case = EvalCase(
        name="test", level="", refmet_id="1", refmet_name="",
        biomapper_ids=[], biomapper_name="", category="",
        correct_id=None, label_source="",
    )
    result = r.select(cands, case=case)
    assert result == ("CHEBI:1", None)
