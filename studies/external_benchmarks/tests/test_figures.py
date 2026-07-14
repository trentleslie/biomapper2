"""Unit 5 — figures (offline; Agg backend). Values must trace to validated results."""

from __future__ import annotations

from studies.external_benchmarks.config import CompetitorResult
from studies.external_benchmarks.figures.competitor_panel import build_s2_data, render_s2
from studies.external_benchmarks.figures.vocab_bar import build_s1_data, render_s1


def _struct_result(top1, scored):
    return {
        "comparable_core": {
            "metric": "top1_accuracy",
            "top1_accuracy": top1,
            "scored_denominator": scored,
            "correct": int((top1 or 0) * scored),
        }
    }


def test_s1_renders_and_values_trace(tmp_path):
    per_vocab = {"CHEBI": _struct_result(0.9, 90), "HMDB": _struct_result(0.8, 85)}
    out = tmp_path / "s1.png"
    result = render_s1(per_vocab, out)
    assert out.exists()
    # every plotted value equals the validated results value
    data = {d["vocab"]: d for d in result["data"]}
    assert data["CHEBI"]["top1_accuracy"] == 0.9
    assert data["CHEBI"]["scored_denominator"] == 90
    assert result["input_type"] == "name"


def test_s1_excluded_cell_rendered_not_silent_zero(tmp_path):
    per_vocab = {"KEGG": _struct_result(None, 0)}  # no scored rows
    data = build_s1_data(per_vocab)
    assert data[0]["excluded"] is True
    out = tmp_path / "s1_excl.png"
    render_s1(per_vocab, out)  # must not raise on None accuracy
    assert out.exists()


def test_s2_renders_same_dataset_and_traces(tmp_path):
    competitors = [
        CompetitorResult(
            tool="CTS", metric="conversion_accuracy", input_type="name", value=0.94, doi="10.x", table_ref="T2"
        ),
        CompetitorResult(
            tool="MetaboAnalyst",
            metric="conversion_accuracy",
            input_type="name",
            value=0.97,
            doi="10.x",
            table_ref="T2",
        ),
    ]
    out = tmp_path / "s2.png"
    result = render_s2(0.92, competitors, out)
    assert out.exists()
    assert result["same_dataset"] is True
    bars = {b["tool"]: b for b in result["data"]["bars"]}
    assert bars["BioMapper"]["value"] == 0.92
    assert bars["CTS"]["value"] == 0.94


def test_s2_untranscribed_competitor_not_zero(tmp_path):
    competitors = [
        CompetitorResult(tool="MetaNetX", metric="m", input_type="name", value=None, doi="10.x", table_ref="T2")
    ]
    data = build_s2_data(0.9, competitors)
    metanetx = next(b for b in data["bars"] if b["tool"] == "MetaNetX")
    assert metanetx["transcribed"] is False
    out = tmp_path / "s2b.png"
    render_s2(0.9, competitors, out)  # renders "not transcribed", no crash
    assert out.exists()
