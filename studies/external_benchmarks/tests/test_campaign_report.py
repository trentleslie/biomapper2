"""Campaign report assembler — two arms, one number per dataset, no competitor section."""

from __future__ import annotations

import studies.external_benchmarks.run as run_mod
from studies.external_benchmarks.report.campaign import (
    CAMPAIGN_FRAMING,
    assemble_campaign_report,
)


def _metab_result(strict, cn):
    return {
        "comparable_core": {
            "metric": "top1_accuracy",
            "top1_accuracy": strict,
            "correct": 50,
            "scored_denominator": 55,
        },
        "comparable_core_charge_normalized": (
            None if cn is None else {"top1_accuracy": cn, "correct": 53, "scored_denominator": 55}
        ),
        "coverage": {"n_predicted": 80, "total": 100, "fraction": 0.8},
        "fallback_bucket": {"count": 3, "rows": []},
    }


def _curie_result(acc):
    return {
        "comparable_core": {
            "metric": "top1_accuracy",
            "top1_accuracy": acc,
            "correct": 900,
            "scored_denominator": 1000,
        },
        "coverage": {"n_predicted": 950, "total": 1000, "fraction": 0.95},
        "curie_stats": {"precision": 0.94, "recall": 0.90, "f1": 0.92, "predicted_and_gold": 960},
    }


def test_campaign_report_two_arms_one_number_each(tmp_path):
    out = tmp_path / "campaign.md"
    text = assemble_campaign_report(
        metabolite_entries=[{"key": "necs-metabolon", "result": _metab_result(0.82, 0.965)}],
        curie_entries=[
            {"key": "hgnc-complete-set", "arm": "gene", "result": _curie_result(0.90)},
            {"key": "uniprot-idmapping", "arm": "protein", "result": _curie_result(0.88)},
        ],
        integrity={"reconciliation_passed": True, "validation_passed": None},
        out_path=out,
    )
    assert out.exists()
    assert CAMPAIGN_FRAMING in text
    assert "INTERNAL" in text
    # both datasets present, one headline accuracy each
    assert "necs-metabolon" in text
    assert "hgnc-complete-set" in text
    assert "uniprot-idmapping" in text
    # metabolite arm reports BOTH strict and charge-normalized
    assert "82.0%" in text and "96.5%" in text
    # gene/protein arm reports its curie accuracy + precision/recall/F1
    assert "90.0%" in text and "94.0%" in text
    # learning #3: NO competitor section/figure is fabricated
    assert "competitor" in text.lower()  # only as an explicit "no competitor exists" note
    assert "not transcribed" not in text  # no fabricated competitor cells
    # learning #1: no per-vocab axis language
    assert "per-vocab" in text.lower()  # the note explaining its omission


def test_run_module_exposes_new_orchestrations():
    assert hasattr(run_mod, "orchestrate_necs")
    assert hasattr(run_mod, "orchestrate_backbone")
    # existing entry points untouched
    assert hasattr(run_mod, "orchestrate")
    assert hasattr(run_mod, "main")
