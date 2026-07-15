"""Head-to-head assembly: one comparable metric, same-row invariant, unscorable fail-loud."""

from __future__ import annotations

import json

import pytest

from studies.external_benchmarks.competitors.headtohead import (
    HeadToHeadRowMismatchError,
    HeadToHeadUnscorableError,
    assemble_head_to_head,
)
from studies.external_benchmarks.config import HGNC


def _result(*, tool=None, top1, correct, scored, cov_frac=0.9, n_pred=9, total=10, unsupported=None):
    r = {
        "comparable_core": {
            "metric": "top1_accuracy",
            "top1_accuracy": top1,
            "correct": correct,
            "scored_denominator": scored,
        },
        "coverage": {"n_predicted": n_pred, "total": total, "fraction": cov_frac},
        "curie_stats": {"precision": top1, "recall": top1, "f1": top1, "predicted_and_gold": n_pred},
    }
    if tool is not None:
        r["tool"] = tool
        r["supported_targets"] = ["ENSEMBL"]
        r["unsupported_targets"] = unsupported or []
        r["protocol_notes"] = ["delta"] if unsupported else []
    return r


def test_assemble_lists_biomapper_first_with_comparable_metric():
    bm = _result(top1=0.8, correct=8, scored=10)
    comps = [_result(tool="gconvert", top1=0.6, correct=6, scored=10)]
    out = assemble_head_to_head(config=HGNC, biomapper_result=bm, competitor_results=comps)
    assert out["comparable_metric"] == "top1_accuracy"
    assert out["scored_denominator"] == 10
    assert out["tools"][0]["tool"] == "BioMapper"
    assert {e["tool"] for e in out["tools"]} == {"BioMapper", "gconvert"}


def test_leaderboard_sorted_by_accuracy_desc():
    bm = _result(top1=0.8, correct=8, scored=10)
    comps = [
        _result(tool="gconvert", top1=0.6, correct=6, scored=10),
        _result(tool="biodbnet", top1=0.9, correct=9, scored=10),
    ]
    out = assemble_head_to_head(config=HGNC, biomapper_result=bm, competitor_results=comps)
    assert [t for t, _ in out["leaderboard"]] == ["biodbnet", "BioMapper", "gconvert"]


def test_row_mismatch_fails_loud():
    bm = _result(top1=0.8, correct=8, scored=10)
    comps = [_result(tool="gconvert", top1=0.6, correct=3, scored=5)]  # different row/gold set
    with pytest.raises(HeadToHeadRowMismatchError):
        assemble_head_to_head(config=HGNC, biomapper_result=bm, competitor_results=comps)


def test_unscorable_biomapper_fails_loud():
    bm = _result(top1=None, correct=0, scored=0)
    with pytest.raises(HeadToHeadUnscorableError):
        assemble_head_to_head(config=HGNC, biomapper_result=bm, competitor_results=[])


def test_protocol_delta_surfaced_in_entry():
    bm = _result(top1=0.8, correct=8, scored=10)
    comps = [_result(tool="uniprot_idmapping", top1=0.5, correct=5, scored=10, unsupported=["NCBIGene"])]
    out = assemble_head_to_head(config=HGNC, biomapper_result=bm, competitor_results=comps)
    entry = next(e for e in out["tools"] if e["tool"] == "uniprot_idmapping")
    assert entry["unsupported_targets"] == ["NCBIGene"]
    assert entry["protocol_notes"] == ["delta"]


def test_writes_results_json(tmp_path):
    bm = _result(top1=0.8, correct=8, scored=10)
    comps = [_result(tool="gconvert", top1=0.6, correct=6, scored=10)]
    path = tmp_path / "results.json"
    assemble_head_to_head(config=HGNC, biomapper_result=bm, competitor_results=comps, out_path=path)
    written = json.loads(path.read_text())
    assert written["dataset"] == HGNC.key
    assert written["api_access_notes"]["gconvert"].startswith("Public g:Profiler")
