"""MetaBench report + baseline citation discipline (offline)."""

from __future__ import annotations

from studies.external_benchmarks.config import METABENCH, METABENCH_BASELINES
from studies.external_benchmarks.report.metabench import assemble_metabench_report
from studies.external_benchmarks.validate import citation_spot_check


def _result() -> dict:
    return {
        "comparable_core": {
            "metric": "top1_accuracy",
            "top1_accuracy": 0.42,
            "correct": 420,
            "scored_denominator": 1000,
        },
        "coverage": {"n_predicted": 900, "total": 1000, "fraction": 0.9},
        "curie_stats": {"precision": 0.46, "recall": 0.42, "f1": 0.44, "predicted_and_gold": 900},
    }


def _card() -> dict:
    return {
        "n_rows": 1000,
        "n_id2id": 400,
        "n_name2id": 600,
        "source_sha256": "a" * 64,
        "expected_source_sha256": METABENCH.expected_source_sha256,
    }


def test_baselines_pass_citation_spot_check_with_value_none():
    # Every baseline carries a DOI + table_ref (value left None / needs-verification) -> passes.
    report = citation_spot_check(METABENCH_BASELINES)
    assert report.passed
    assert all(b.value is None for b in METABENCH_BASELINES)


def test_baseline_missing_doi_fails_spot_check():
    from studies.external_benchmarks.config import CompetitorResult

    bad = (CompetitorResult(tool="X", metric="m", input_type="grounding", value=None, doi="", table_ref="t"),)
    assert not citation_spot_check(bad).passed


def test_report_places_number_alongside_baseline_distribution(tmp_path):
    out = tmp_path / "metabench_report.md"
    text = assemble_metabench_report(
        config=METABENCH,
        result=_result(),
        card=_card(),
        baselines=METABENCH_BASELINES,
        integrity={"reconciliation_passed": True, "validation_passed": True},
        out_path=out,
    )
    assert out.exists()
    assert "42.0%" in text  # BioMapper's headline number is rendered
    assert "25-model distribution" in text
    # baselines render as needs-verification (never a from-memory number)
    assert "needs verification" in text
    assert "10.48550/arXiv.2510.14944" in text
