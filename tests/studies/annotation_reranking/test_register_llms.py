"""Tests for _register_llms in studies/annotation_reranking/run.py.

TDD (Task 9): test written first (RED), then implementation added (GREEN).

The test verifies that after _register_llms registers an LLM reranker with a
stubbed call_fn, calling select() on that reranker properly populates
last_cost_usd and last_latency_s — proving that the seam feeds score_case
(which reads those fields after select() returns).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from studies.annotation_reranking.models_data import Candidate, EvalCase
from studies.annotation_reranking.rerankers.base import REGISTRY
from studies.annotation_reranking.run import _register_llms


def _c(cid: str) -> Candidate:
    return Candidate(id=cid, score=1.0, name=cid, equivalent_ids=[])


def _case() -> EvalCase:
    return EvalCase(
        name="test",
        level="MS1",
        refmet_id="1",
        refmet_name="",
        biomapper_ids=[],
        biomapper_name="",
        category="metabolite",
        correct_id=None,
        label_source="refmet_agreement",
    )


# ---------------------------------------------------------------------------
# _register_llms tests
# ---------------------------------------------------------------------------


class TestRegisterLlms:
    def setup_method(self):
        """Snapshot REGISTRY before test so we can clean up after."""
        self._pre_keys = set(REGISTRY.keys())

    def teardown_method(self):
        """Remove any keys added by _register_llms during this test."""
        for k in list(REGISTRY.keys()):
            if k not in self._pre_keys:
                del REGISTRY[k]

    def test_registers_both_blind_and_non_blind(self):
        """_register_llms adds both blind and non-blind entries for the model."""
        with patch(
            "studies.annotation_reranking.run.call_model",
            return_value=("CHEBI:1", 0.0, 0.0),
        ):
            _register_llms(["sonnet"])

        assert "llm:sonnet/blind" in REGISTRY
        assert "llm:sonnet" in REGISTRY

    def test_select_sets_last_cost_and_latency(self):
        """After select(), last_cost_usd and last_latency_s reflect the stub return values.

        This is the key seam: score_case reads these attributes off the reranker
        after select() returns.  The test proves _register_llms wires call_model
        into the LlmReranker correctly.
        """
        with patch(
            "studies.annotation_reranking.run.call_model",
            return_value=("CHEBI:1", 0.0123, 0.4),
        ):
            _register_llms(["sonnet"])

        reranker = REGISTRY["llm:sonnet/blind"]
        cands = [_c("CHEBI:1")]

        # call_model is already patched via _register_llms above — the call_fn
        # captured inside _register_llms is a closure that calls call_model.
        # We re-patch here so the reranker's closure hits the patched version
        # when select() fires.
        with patch(
            "studies.annotation_reranking.run.call_model",
            return_value=("CHEBI:1", 0.0123, 0.4),
        ):
            selected_id, review_flag = reranker.select(cands, _case())

        assert selected_id == "CHEBI:1"
        assert review_flag is None
        assert reranker.last_cost_usd == pytest.approx(0.0123)
        assert reranker.last_latency_s == pytest.approx(0.4)

    def test_last_cost_and_latency_initialized_to_zero(self):
        """Before any select() call, last_cost_usd and last_latency_s default to 0.0."""
        with patch(
            "studies.annotation_reranking.run.call_model",
            return_value=("CHEBI:1", 0.0, 0.0),
        ):
            _register_llms(["sonnet"])

        reranker = REGISTRY["llm:sonnet/blind"]
        assert reranker.last_cost_usd == 0.0
        assert reranker.last_latency_s == 0.0

    def test_empty_model_list_registers_nothing_extra(self):
        """_register_llms([]) must not add any new LLM entries to REGISTRY."""
        _register_llms([])
        new_keys = set(REGISTRY.keys()) - self._pre_keys
        assert new_keys == set()

    def test_unknown_label_raises_key_error(self):
        """An unrecognised model label (not in ROSTER) should raise KeyError."""
        with pytest.raises(KeyError):
            _register_llms(["not_a_real_model"])
