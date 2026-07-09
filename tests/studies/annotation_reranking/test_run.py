"""Tests for studies/annotation_reranking/run.py — Task 8 orchestrator.

TDD: tests are written first (RED), then run.py is implemented (GREEN).

Amendment-aware: uses 2-arg classify_regime(case, candidates), 2-tuple unpack
from reranker.select, and verifies cost_usd/latency_s seam.
"""
from __future__ import annotations

import json
import os
import tempfile
from unittest import mock
from unittest.mock import patch

import pytest

from studies.annotation_reranking.models_data import Candidate, EvalCase, RerankResult
from studies.annotation_reranking.rerankers.deterministic import RmAnchorReranker
from studies.annotation_reranking.run import build_manifest, score_case, run_matrix


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _case(correct_id: str | None, label_source: str) -> EvalCase:
    """Minimal EvalCase factory."""
    return EvalCase(
        name="test_metabolite",
        level="MS2",
        refmet_id="1",
        refmet_name="refmet_name",
        biomapper_ids=["CHEBI:2"],
        biomapper_name="biomapper_name",
        category="metabolite",
        correct_id=correct_id,
        label_source=label_source,
    )


def _cand(cid: str, score: float = 3.0, has_rm: bool = False) -> Candidate:
    equiv = ["RM:1"] if has_rm else []
    return Candidate(id=cid, score=score, name=cid, equivalent_ids=equiv)


# ---------------------------------------------------------------------------
# build_manifest
# ---------------------------------------------------------------------------

class TestBuildManifest:
    def test_pins_reproducibility_fields(self):
        m = build_manifest("SOME.csv", 20, (0, 1, 2), [], "test-box")
        for key in ("dataset_sha256", "top_n", "seeds", "temperature", "models", "hardware"):
            assert key in m, f"Missing key: {key}"

    def test_temperature_is_zero(self):
        m = build_manifest("SOME.csv", 20, (0, 1, 2), [], "test-box")
        assert m["temperature"] == 0

    def test_hardware_pinned(self):
        m = build_manifest("SOME.csv", 20, (0,), [], "my-gpu-box")
        assert m["hardware"] == "my-gpu-box"

    def test_seeds_preserved(self):
        m = build_manifest("SOME.csv", 10, (0, 1, 2), [], "box")
        assert m["seeds"] == [0, 1, 2]

    def test_top_n_preserved(self):
        m = build_manifest("SOME.csv", 15, (0,), [], "box")
        assert m["top_n"] == 15


# ---------------------------------------------------------------------------
# score_case — shadow paths
# ---------------------------------------------------------------------------

class TestScoreCaseEmptyCandidates:
    def test_error_is_empty_candidates(self):
        r = score_case(_case("CHEBI:9", "independent_refmet_error"), [], RmAnchorReranker(), None)
        assert r.error == "empty_candidates"

    def test_selected_id_is_none(self):
        r = score_case(_case("CHEBI:9", "independent_refmet_error"), [], RmAnchorReranker(), None)
        assert r.selected_id is None

    def test_is_correct_is_false(self):
        r = score_case(_case("CHEBI:9", "independent_refmet_error"), [], RmAnchorReranker(), None)
        assert r.is_correct is False

    def test_review_flag_is_none(self):
        r = score_case(_case("CHEBI:9", "independent_refmet_error"), [], RmAnchorReranker(), None)
        assert r.review_flag is None


class TestScoreCaseRefmetAgreement:
    def test_is_unscored_when_no_correct_id(self):
        """refmet_agreement cases have correct_id=None → is_correct must be None."""
        cands = [_cand("CHEBI:2", has_rm=True)]
        r = score_case(_case(None, "refmet_agreement"), cands, RmAnchorReranker(), None)
        assert r.is_correct is None


class TestScoreCaseIndependent:
    def test_correct_pick_scores_true(self):
        """RmAnchorReranker picks the RM-bearing candidate; correct_id matches."""
        cands = [
            _cand("CHEBI:9", score=3.0, has_rm=False),
            _cand("CHEBI:2", score=5.0, has_rm=True),  # rm_anchor will pick this
        ]
        # correct_id = CHEBI:2 (the RM-bearing one rm_anchor picks)
        r = score_case(_case("CHEBI:2", "independent_biomapper_error"), cands, RmAnchorReranker(), None)
        assert r.selected_id == "CHEBI:2"
        assert r.is_correct is True

    def test_wrong_pick_scores_false(self):
        cands = [
            _cand("CHEBI:9", score=3.0, has_rm=False),
            _cand("CHEBI:2", score=5.0, has_rm=True),  # rm_anchor will pick CHEBI:2
        ]
        # correct_id = CHEBI:9, but rm_anchor picks CHEBI:2
        r = score_case(_case("CHEBI:9", "independent_biomapper_error"), cands, RmAnchorReranker(), None)
        assert r.selected_id == "CHEBI:2"
        assert r.is_correct is False


class TestScoreCaseReviewFlag:
    def test_review_flag_threaded_through(self):
        """A reranker stub that returns a review_flag must have it stored on RerankResult."""

        class StubReranker:
            name = "stub_with_flag"

            def select(self, candidates, case=None):
                return candidates[0].id, "divergent_refmet"

        cands = [_cand("CHEBI:9")]
        r = score_case(_case("CHEBI:9", "independent_biomapper_error"), cands, StubReranker(), None)
        assert r.review_flag == "divergent_refmet"
        assert r.is_correct is True


class TestScoreCaseCostLatencySeam:
    def test_reads_last_cost_and_latency_from_reranker(self):
        """score_case reads last_cost_usd and last_latency_s off reranker after select."""

        class LlmStub:
            name = "llm_stub"
            last_cost_usd: float = 0.0
            last_latency_s: float = 0.0

            def select(self, candidates, case=None):
                self.last_cost_usd = 0.042
                self.last_latency_s = 1.23
                return candidates[0].id, None

        stub = LlmStub()
        cands = [_cand("CHEBI:9")]
        r = score_case(_case("CHEBI:9", "independent_biomapper_error"), cands, stub, "gpt-4o")
        assert r.cost_usd == pytest.approx(0.042)
        assert r.latency_s == pytest.approx(1.23)

    def test_defaults_to_zero_when_absent(self):
        """Deterministic rerankers don't set last_cost_usd; score_case defaults to 0.0."""
        cands = [_cand("CHEBI:9", has_rm=True)]
        r = score_case(_case("CHEBI:9", "independent_biomapper_error"), cands, RmAnchorReranker(), None)
        assert r.cost_usd == 0.0
        assert r.latency_s == 0.0


class TestScoreCaseExceptionHandling:
    def test_exception_stored_as_error(self):
        """Reranker that raises an exception → error=str(e), is_correct=False."""

        class BrokenReranker:
            name = "broken"

            def select(self, candidates, case=None):
                raise RuntimeError("api timeout")

        cands = [_cand("CHEBI:9")]
        r = score_case(_case("CHEBI:9", "independent_biomapper_error"), cands, BrokenReranker(), None)
        assert r.error == "api timeout"
        assert r.is_correct is False
        assert r.selected_id is None

    def test_off_list_none_marks_error(self):
        """Reranker returning (None, None) → error='off_list'."""

        class OffListReranker:
            name = "off_list_reranker"

            def select(self, candidates, case=None):
                return None, None

        cands = [_cand("CHEBI:9")]
        r = score_case(_case("CHEBI:9", "independent_biomapper_error"), cands, OffListReranker(), None)
        assert r.error == "off_list"
        assert r.is_correct is False


# ---------------------------------------------------------------------------
# run_matrix — network-mocked integration test
# ---------------------------------------------------------------------------

class TestRunMatrix:
    def _minimal_csv(self, tmp_path) -> str:
        """Write a 1-row CSV compatible with load_eval_cases."""
        csv_path = str(tmp_path / "test.csv")
        with open(csv_path, "w") as fh:
            fh.write("name,level,refmet_id,refmet_name,biomapper_id,biomapper_name,category\n")
            fh.write("glucose,MS1,28,Glucose,CHEBI:17234,Glucose,metabolite\n")
        return csv_path

    def test_run_matrix_writes_manifest_and_results(self, tmp_path):
        csv_path = self._minimal_csv(tmp_path)
        out_dir = str(tmp_path / "run_out")

        fake_candidates = [_cand("CHEBI:17234", score=4.5, has_rm=True)]

        with patch(
            "studies.annotation_reranking.run.fetch_candidates",
            return_value=fake_candidates,
        ):
            returned_path = run_matrix(
                csv_path=csv_path,
                top_n=5,
                seeds=(0,),
                out_dir=out_dir,
            )

        assert returned_path == out_dir
        assert os.path.isfile(os.path.join(out_dir, "manifest.json"))
        assert os.path.isfile(os.path.join(out_dir, "results.jsonl"))

    def test_run_matrix_results_have_required_fields(self, tmp_path):
        csv_path = self._minimal_csv(tmp_path)
        out_dir = str(tmp_path / "run_out2")

        fake_candidates = [_cand("CHEBI:17234", score=4.5, has_rm=True)]

        with patch(
            "studies.annotation_reranking.run.fetch_candidates",
            return_value=fake_candidates,
        ):
            run_matrix(csv_path=csv_path, top_n=5, seeds=(0,), out_dir=out_dir)

        with open(os.path.join(out_dir, "results.jsonl")) as fh:
            lines = fh.readlines()

        assert len(lines) > 0
        record = json.loads(lines[0])
        for field in ("selected_id", "is_correct", "regime", "cost_usd", "latency_s", "review_flag"):
            assert field in record, f"Missing field in results.jsonl: {field}"

    def test_run_matrix_manifest_temperature_zero(self, tmp_path):
        csv_path = self._minimal_csv(tmp_path)
        out_dir = str(tmp_path / "run_out3")

        with patch(
            "studies.annotation_reranking.run.fetch_candidates",
            return_value=[],
        ):
            run_matrix(csv_path=csv_path, top_n=5, seeds=(0,), out_dir=out_dir)

        with open(os.path.join(out_dir, "manifest.json")) as fh:
            manifest = json.load(fh)

        assert manifest["temperature"] == 0

    def _csv_with_taxonomy_category(self, tmp_path) -> str:
        """Write a 1-row CSV where category is a disagreement taxonomy label (NOT 'metabolite').

        This is critical for the regression test: if the fixture category were 'metabolite'
        the test could not distinguish whether run_matrix passed case.category or the
        literal 'metabolite' to fetch_candidates.
        """
        csv_path = str(tmp_path / "test_taxonomy.csv")
        with open(csv_path, "w") as fh:
            fh.write("name,level,refmet_id,refmet_name,biomapper_id,biomapper_name,category\n")
            fh.write(
                "glucose,MS1,28,Glucose,CHEBI:17234,Glucose,"
                "divergent (different compound)\n"
            )
        return csv_path

    def test_fetch_candidates_always_called_with_metabolite_category(self, tmp_path):
        """Regression: run_matrix must pass 'metabolite' to fetch_candidates, never case.category.

        The CSV row has category='divergent (different compound)' — a disagreement taxonomy
        label, not a biolink entity type. If run_matrix ever regresses to passing case.category
        the mock assertion below will catch it.
        """
        csv_path = self._csv_with_taxonomy_category(tmp_path)
        out_dir = str(tmp_path / "run_out_regression")

        with patch(
            "studies.annotation_reranking.run.fetch_candidates",
            return_value=[],
        ) as mock_fetch:
            run_matrix(csv_path=csv_path, top_n=5, seeds=(0,), out_dir=out_dir)

        # Every call must use the literal "metabolite", not the taxonomy category string.
        mock_fetch.assert_called_once_with("glucose", "metabolite", top_n=5)


# ---------------------------------------------------------------------------
# run_matrix — derive_labels wiring (Task 10)
# ---------------------------------------------------------------------------

class TestRunMatrixDeriveLabels:
    def _minimal_csv(self, tmp_path) -> str:
        csv_path = str(tmp_path / "test_dl.csv")
        with open(csv_path, "w") as fh:
            fh.write("name,level,refmet_id,refmet_name,biomapper_id,biomapper_name,category\n")
            fh.write("glucose,MS1,28,Glucose,CHEBI:17234,Glucose,metabolite\n")
        return csv_path

    def test_derive_labels_invoked_when_flag_true(self, tmp_path):
        """run_matrix with derive_labels=True must call labels.derive_labels on the loaded cases."""
        csv_path = self._minimal_csv(tmp_path)
        out_dir = str(tmp_path / "run_out_dl")

        # A real non-empty sentinel list so we can verify the exact object passed.
        sentinel_cases = [_case(None, "refmet_agreement")]

        with (
            patch(
                "studies.annotation_reranking.run.fetch_candidates",
                return_value=[],
            ),
            patch(
                "studies.annotation_reranking.run.load_eval_cases",
                return_value=sentinel_cases,
            ),
            patch(
                "studies.annotation_reranking.run._labels_module.derive_labels",
                return_value=sentinel_cases,
            ) as mock_derive,
        ):
            run_matrix(csv_path=csv_path, top_n=5, seeds=(0,), out_dir=out_dir, derive_labels=True)

        # Verify called exactly once AND with the cases list (not csv_path or empty list).
        mock_derive.assert_called_once_with(mock.ANY)
        actual_arg = mock_derive.call_args[0][0]
        assert actual_arg is sentinel_cases, (
            f"derive_labels was called with {type(actual_arg)!r} instead of the cases list"
        )
        assert len(actual_arg) > 0, "derive_labels must not be called with an empty list"

    def test_derive_labels_not_invoked_by_default(self, tmp_path):
        """run_matrix with default derive_labels=False must NOT call labels.derive_labels."""
        csv_path = self._minimal_csv(tmp_path)
        out_dir = str(tmp_path / "run_out_no_dl")

        with (
            patch(
                "studies.annotation_reranking.run.fetch_candidates",
                return_value=[],
            ),
            patch(
                "studies.annotation_reranking.run._labels_module.derive_labels",
                return_value=[],
            ) as mock_derive,
        ):
            run_matrix(csv_path=csv_path, top_n=5, seeds=(0,), out_dir=out_dir)

        mock_derive.assert_not_called()
