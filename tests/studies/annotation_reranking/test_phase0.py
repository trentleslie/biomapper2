"""Tests for phase0.py — Phase 0 decision gate.

All network calls are mocked. We patch fetch_candidates, load_eval_cases,
dataset_sha256, AND the source_weight_guard in REGISTRY so no live
Kestrel / MW / PubChem traffic occurs in CI.
"""
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from studies.annotation_reranking.models_data import Candidate, EvalCase


# ---------------------------------------------------------------------------
# Synthetic test data
# ---------------------------------------------------------------------------

def _candidate(cid: str, score: float = 2.0) -> Candidate:
    return Candidate(id=cid, score=score, name=cid)


# Case A: target CHEBI:28683 IS in candidates; SWG picks refmet (divergent_refmet flag)
CASE_A = EvalCase(
    name="compound_a",
    level="",
    refmet_id="28683",
    refmet_name="compound_a_refmet",
    biomapper_ids=["CHEBI:100"],
    biomapper_name="compound_a",
    category="metabolite",
    correct_id=None,          # target_id → CHEBI:28683
    label_source="refmet_agreement",
)

# Candidates for Case A: majority is CHEBI:100 (score 4.0), refmet CHEBI:28683 present (score 2.0)
CANDS_A = [
    _candidate("CHEBI:100", score=4.0),
    _candidate("CHEBI:28683", score=2.0),
]

# Case B: target NOT in candidates → not_retrieved
CASE_B = EvalCase(
    name="compound_b",
    level="",
    refmet_id="99999",
    refmet_name="compound_b_refmet",
    biomapper_ids=["CHEBI:200"],
    biomapper_name="compound_b",
    category="metabolite",
    correct_id=None,          # target_id → CHEBI:99999
    label_source="refmet_agreement",
)

# Candidates for Case B: CHEBI:99999 is absent
CANDS_B = [
    _candidate("CHEBI:200", score=3.5),
    _candidate("CHEBI:201", score=2.0),
]


def _side_effect_fetch(name: str, category: str, top_n: int = 20) -> list[Candidate]:
    if name == "compound_a":
        return CANDS_A
    if name == "compound_b":
        return CANDS_B
    return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import_run_phase0():
    """Late import so patching load_eval_cases works at module level."""
    from studies.annotation_reranking.phase0 import run_phase0
    return run_phase0


def _make_fake_swg(selected_id: str = "CHEBI:100", review_flag: str = "divergent_refmet") -> MagicMock:
    """Return a MagicMock that stands in for the source_weight_guard reranker.

    select() returns (selected_id, review_flag) so the caller never reaches
    connectivity_match / get_equivalent_ids / MW / PubChem.
    """
    fake = MagicMock()
    fake.select.return_value = (selected_id, review_flag)
    return fake


def _swg_patch(fake_swg: MagicMock):
    """patch.dict context manager that replaces REGISTRY['source_weight_guard']."""
    return patch.dict(
        "studies.annotation_reranking.phase0.REGISTRY",
        {"source_weight_guard": fake_swg},
        clear=False,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_run_phase0_summary_keys(tmp_path):
    """run_phase0 returns a dict with all required summary keys."""
    run_phase0 = _import_run_phase0()
    fake_swg = _make_fake_swg()

    with (
        patch(
            "studies.annotation_reranking.phase0.fetch_candidates",
            side_effect=_side_effect_fetch,
        ),
        patch(
            "studies.annotation_reranking.phase0.load_eval_cases",
            return_value=[CASE_A, CASE_B],
        ),
        patch(
            "studies.annotation_reranking.phase0.dataset_sha256",
            return_value="deadbeef" * 8,
        ),
        _swg_patch(fake_swg),
    ):
        summary = run_phase0(
            csv_path="/fake/path.csv",
            top_n=20,
            out_dir=str(tmp_path),
        )

    required_keys = {
        "retrievable",
        "not_retrieved",
        "dataset_sha256",
        "top_n",
        "n_swg_disagrees_correct",
        "flag_divergent_refmet",
        "flag_conflict_no_structure",
        "flag_none",
    }
    assert required_keys.issubset(summary.keys()), (
        f"Missing keys: {required_keys - summary.keys()}"
    )


def test_run_phase0_counts(tmp_path):
    """Retrievable/not_retrieved counts match the synthetic case set."""
    run_phase0 = _import_run_phase0()
    fake_swg = _make_fake_swg()

    with (
        patch(
            "studies.annotation_reranking.phase0.fetch_candidates",
            side_effect=_side_effect_fetch,
        ),
        patch(
            "studies.annotation_reranking.phase0.load_eval_cases",
            return_value=[CASE_A, CASE_B],
        ),
        patch(
            "studies.annotation_reranking.phase0.dataset_sha256",
            return_value="deadbeef" * 8,
        ),
        _swg_patch(fake_swg),
    ):
        summary = run_phase0(
            csv_path="/fake/path.csv",
            top_n=20,
            out_dir=str(tmp_path),
        )

    assert summary["retrievable"] == 1   # Case A only
    assert summary["not_retrieved"] == 1  # Case B only
    assert summary["top_n"] == 20
    assert summary["dataset_sha256"] == "deadbeef" * 8


def test_run_phase0_writes_json(tmp_path):
    """run_phase0 writes phase0_regimes.json to out_dir."""
    run_phase0 = _import_run_phase0()
    fake_swg = _make_fake_swg()

    with (
        patch(
            "studies.annotation_reranking.phase0.fetch_candidates",
            side_effect=_side_effect_fetch,
        ),
        patch(
            "studies.annotation_reranking.phase0.load_eval_cases",
            return_value=[CASE_A, CASE_B],
        ),
        patch(
            "studies.annotation_reranking.phase0.dataset_sha256",
            return_value="abc123",
        ),
        _swg_patch(fake_swg),
    ):
        run_phase0(
            csv_path="/fake/path.csv",
            top_n=20,
            out_dir=str(tmp_path),
        )

    json_path = tmp_path / "phase0_regimes.json"
    assert json_path.exists(), "phase0_regimes.json was not written"

    with open(json_path) as f:
        data = json.load(f)

    assert "summary" in data
    assert "per_case" in data
    assert len(data["per_case"]) == 2


def test_run_phase0_per_case_structure(tmp_path):
    """Each per_case entry has name, regime, selected_id, review_flag."""
    run_phase0 = _import_run_phase0()
    fake_swg = _make_fake_swg()

    with (
        patch(
            "studies.annotation_reranking.phase0.fetch_candidates",
            side_effect=_side_effect_fetch,
        ),
        patch(
            "studies.annotation_reranking.phase0.load_eval_cases",
            return_value=[CASE_A, CASE_B],
        ),
        patch(
            "studies.annotation_reranking.phase0.dataset_sha256",
            return_value="abc123",
        ),
        _swg_patch(fake_swg),
    ):
        run_phase0(
            csv_path="/fake/path.csv",
            top_n=20,
            out_dir=str(tmp_path),
        )

    with open(tmp_path / "phase0_regimes.json") as f:
        data = json.load(f)

    for entry in data["per_case"]:
        assert "name" in entry
        assert "regime" in entry
        assert "selected_id" in entry
        assert "review_flag" in entry
        assert entry["regime"] in {"retrievable", "not_retrieved"}


def test_run_phase0_default_out_dir(tmp_path, monkeypatch):
    """When out_dir uses default path, the JSON is still written."""
    run_phase0 = _import_run_phase0()
    fake_swg = _make_fake_swg()

    default_dir = tmp_path / "studies" / "annotation_reranking" / "runs" / "phase0"

    with (
        patch(
            "studies.annotation_reranking.phase0.fetch_candidates",
            side_effect=_side_effect_fetch,
        ),
        patch(
            "studies.annotation_reranking.phase0.load_eval_cases",
            return_value=[CASE_A],
        ),
        patch(
            "studies.annotation_reranking.phase0.dataset_sha256",
            return_value="abc123",
        ),
        patch(
            "studies.annotation_reranking.phase0._DEFAULT_OUT_DIR",
            str(default_dir),
        ),
        _swg_patch(fake_swg),
    ):
        summary = run_phase0(csv_path="/fake/path.csv", top_n=20)

    assert (default_dir / "phase0_regimes.json").exists()
