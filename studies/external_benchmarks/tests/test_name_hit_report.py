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


def test_report_renders_equivalence_columns_and_confusion(tmp_path):
    from studies.external_benchmarks.report.name_hit import assemble_name_hit_report

    result = {
        "comparable_core": {"metric": "name_hit_rate", "name_hit_rate": 0.949, "matched": 2774, "total": 2923},
        "id_concordance": {"metric": "id_concordance_rate", "scored": 2923, "concordant": 207,
                            "concordance_rate": 0.071, "excluded_nonchemical": 0},
        "id_concordance_uci_equivalence": {"metric": "id_concordance_uci_equivalence_rate", "scored": 2923,
                                           "concordant": 1600, "concordance_rate": 0.547, "needs_verification": 40},
        "id_concordance_inchikey_bridge": {"metric": "id_concordance_inchikey_bridge_rate", "scored": 2923,
                                           "concordant": 2283, "concordance_rate": 0.781, "needs_verification": 12},
        "structure_concordance_charge_normalized": None,
        "namespace_confusion": {"HMDB": {"CHEBI": 900}, "KEGG": {"CHEBI": 300}},
    }
    out = tmp_path / "name_hit.md"
    text = assemble_name_hit_report(
        entries=[{"key": "metaboliteannotator-positive", "mode": "positive", "result": result}],
        competitors=[], out_path=out,
    )
    assert "ID-eq(UCI)" in text and "ID-eq(bridge)" in text
    assert "7.1%" in text and "54.7%" in text and "78.1%" in text  # strict beside both equivalence numbers
    assert "Namespace divergence" in text
    assert "HMDB" in text and "CHEBI" in text  # confusion matrix rendered
