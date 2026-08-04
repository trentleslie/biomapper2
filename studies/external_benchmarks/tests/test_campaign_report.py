"""Campaign report assembler — two arms, one number per dataset, no competitor section."""

from __future__ import annotations

import studies.external_benchmarks.run as run_mod
from studies.external_benchmarks.report.campaign import (
    CAMPAIGN_FRAMING,
    LIPID_CHARGE_NORM_NOTE,
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


def _regime(strict, cn, correct, scored, n_rows, n_pred):
    return {
        "comparable_core": {"top1_accuracy": strict, "correct": correct, "scored_denominator": scored},
        "comparable_core_charge_normalized": (
            None if cn is None else {"top1_accuracy": cn, "correct": correct, "scored_denominator": scored}
        ),
        "n_rows": n_rows,
        "coverage": {"n_predicted": n_pred, "total": n_rows, "fraction": n_pred / n_rows},
    }


def test_campaign_report_renders_name_source_regime_breakout(tmp_path):
    out = tmp_path / "lmsd.md"
    result = _metab_result(0.55, 0.55)  # blended; charge-norm coincides with strict (lipid case)
    result["by_name_source_regime"] = {
        "shorthand": _regime(0.50, 0.50, 675, 1350, 1350, 1350),  # the hard class, ~90% of the sample
        "common_systematic": _regime(0.95, 0.95, 142, 150, 150, 150),
    }
    text = assemble_campaign_report(
        metabolite_entries=[{"key": "lmsd", "result": result}],
        curie_entries=[],
        integrity={"reconciliation_passed": True, "validation_passed": None},
        out_path=out,
    )
    # blended overall retained for continuity
    assert "55.0%" in text
    # both regimes broken out, shorthand listed as the hard class
    assert "shorthand (ABBREVIATION)" in text
    assert "common / systematic" in text
    assert "50.0%" in text and "95.0%" in text
    # the charge-norm == strict note is stated once
    assert LIPID_CHARGE_NORM_NOTE in text
    assert text.count(LIPID_CHARGE_NORM_NOTE) == 1


def test_campaign_report_omits_regime_section_when_absent(tmp_path):
    # A metabolite entry without the breakout (e.g. NECS/RefMet) must not render the regime section.
    out = tmp_path / "necs.md"
    text = assemble_campaign_report(
        metabolite_entries=[{"key": "necs-metabolon", "result": _metab_result(0.82, 0.965)}],
        curie_entries=[],
        integrity={"reconciliation_passed": True, "validation_passed": None},
        out_path=out,
    )
    assert "regime breakout" not in text.lower()
    assert LIPID_CHARGE_NORM_NOTE not in text


def test_run_module_exposes_new_orchestrations():
    assert hasattr(run_mod, "orchestrate_necs")
    assert hasattr(run_mod, "orchestrate_backbone")
    # existing entry points untouched
    assert hasattr(run_mod, "orchestrate")
    assert hasattr(run_mod, "main")


def test_flagrate_entries_render_separate_table_never_blended(tmp_path):
    from studies.external_benchmarks.report.campaign import assemble_campaign_report

    accuracy = {
        "comparable_core": {"metric": "top1_accuracy", "top1_accuracy": 0.90, "correct": 9, "scored_denominator": 10},
        "coverage": {"n_predicted": 10, "total": 10, "fraction": 1.0},
        "curie_stats": {"precision": 0.9, "recall": 0.9, "f1": 0.9, "predicted_and_gold": 10},
    }
    flagging = {
        "arm": "gene",
        "input_type": "name",
        "partition": "ambiguous",
        "comparable_core": {"metric": "flag_rate", "flag_rate": 0.25, "flagged": 1, "n_ambiguous": 4},
        "silent_over_commit_rate": 0.25,
        "member_when_committed": 0.667,
        "committed": 3,
    }
    out = tmp_path / "r.md"
    text = assemble_campaign_report(
        metabolite_entries=[],
        curie_entries=[{"key": "nlm-gene (unambiguous — accuracy)", "arm": "gene", "result": accuracy}],
        flagrate_entries=[{"key": "nlm-gene (ambiguous — flag-rate)", "arm": "gene", "result": flagging}],
        out_path=out,
    )
    assert "EITL flag-rate" in text
    assert "Flag-rate" in text and "Silent over-commit" in text
    # the two partitions are separate table rows/sections — never a single blended number
    assert "nlm-gene (unambiguous — accuracy)" in text
    assert "nlm-gene (ambiguous — flag-rate)" in text
    assert "25.0%" in text  # flag-rate rendered as a percent


def test_backward_compatible_without_flagrate_entries(tmp_path):
    from studies.external_benchmarks.report.campaign import assemble_campaign_report

    text = assemble_campaign_report(metabolite_entries=[], curie_entries=[], out_path=tmp_path / "r2.md")
    assert "EITL flag-rate" not in text  # section omitted when no flag-rate entries
