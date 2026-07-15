"""Name-hit head-to-head report assembler (internal; BioMapper vs transcribed baselines)."""

from __future__ import annotations

from studies.external_benchmarks.config import METABOLITEANNOTATOR_COMPETITORS, METABOLITEANNOTATOR_POS
from studies.external_benchmarks.report.name_hit import assemble_name_hit_report


def _result(rate, matched, total):
    return {
        "comparable_core": {"metric": "name_hit_rate", "name_hit_rate": rate, "matched": matched, "total": total},
        "id_concordance": {"scored": total, "concordant": matched, "concordance_rate": matched / total},
        "structure_concordance_charge_normalized": None,
        "mode": "positive",
    }


def test_report_renders_biomapper_and_transcribed_competitors(tmp_path):
    out = tmp_path / "report.md"
    text = assemble_name_hit_report(
        entries=[{"key": METABOLITEANNOTATOR_POS.key, "mode": "positive", "result": _result(0.9, 90, 100)}],
        competitors=METABOLITEANNOTATOR_COMPETITORS,
        integrity={"accessions_status": "needs-fetching"},
        out_path=out,
    )
    assert out.exists()
    # BioMapper's own number is rendered
    assert "90.0%" in text
    # transcribed competitor tools appear; their unverified values render as n/a (never fabricated)
    assert "MetaboAnalyst 6.0" in text
    assert "metaboliteIDmapping" in text
    assert "n/a" in text  # competitor value=None -> not baked
    # internal-only marker + needs-fetching surfaced
    assert "INTERNAL" in text
    assert "needs-fetching" in text
