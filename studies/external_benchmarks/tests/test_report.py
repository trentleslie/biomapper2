"""Unit 6 — internal report assembler + production oracle adapter (offline)."""

from __future__ import annotations

import pytest

from studies.external_benchmarks.config import HAJJAR, CompetitorResult
from studies.external_benchmarks.oracle import KGStructureOracle
from studies.external_benchmarks.report.assemble import PARITY_FRAMING, assemble_report


def _struct(top1, scored, correct, cov_pred, cov_total, fb=0):
    return {
        "comparable_core": {
            "metric": "top1_accuracy",
            "top1_accuracy": top1,
            "scored_denominator": scored,
            "correct": correct,
        },
        "coverage": {"n_predicted": cov_pred, "total": cov_total, "fraction": cov_pred / cov_total},
        "fallback_bucket": {"count": fb, "rows": []},
    }


def _paper(mr, matched, total):
    return {"metric": "match_rate", "match_rate": mr, "matched": matched, "total": total, "input_type": "name"}


@pytest.fixture
def competitors():
    return [
        CompetitorResult(
            tool="CTS", metric="conversion_accuracy", input_type="name", value=0.94, doi="10.1007/x", table_ref="T2"
        ),
        CompetitorResult(
            tool="MetaNetX",
            metric="conversion_accuracy",
            input_type="name",
            value=None,
            doi="10.1007/x",
            table_ref="T2",
        ),
    ]


def test_report_has_parity_framing_and_no_wiki(tmp_path, competitors):
    out = tmp_path / "report.md"
    text = assemble_report(
        config=HAJJAR,
        per_vocab_results={"CHEBI": _struct(0.9, 90, 81, 98, 100, fb=2)},
        paper_metrics={"CHEBI": _paper(0.98, 98, 100)},
        competitors=competitors,
        figure_paths={"S1": "runs/x/S1.png", "S2": "runs/x/S2.png"},
        integrity={"reconciliation_passed": True, "validation_passed": True, "protocol_parity": (0.95, 0.95, 0.02)},
        out_path=out,
    )
    assert out.exists()
    assert PARITY_FRAMING in text
    assert "parity-establishment" in text.lower()
    assert "INTERNAL" in text
    # dataset + both figures referenced
    assert HAJJAR.key in text
    assert "S1.png" in text and "S2.png" in text
    # competitor DOI cited; untranscribed shown as such, not 0
    assert "10.1007/x" in text
    assert "not transcribed" in text


def test_report_numbers_trace_to_inputs(tmp_path, competitors):
    out = tmp_path / "report.md"
    text = assemble_report(
        config=HAJJAR,
        per_vocab_results={"CHEBI": _struct(0.9, 90, 81, 98, 100, fb=2)},
        paper_metrics={"CHEBI": _paper(0.98, 98, 100)},
        competitors=competitors,
        figure_paths={"S1": "s1.png", "S2": "s2.png"},
        integrity={"reconciliation_passed": True, "validation_passed": True, "protocol_parity": None},
        out_path=out,
    )
    # the reported top-1 (90.0%) and match-rate (98.0%) come straight from inputs
    assert "90.0%" in text
    assert "98.0%" in text
    assert "94.0%" in text  # CTS transcribed value


# ---------- production oracle adapter ----------


class _FakeLinker:
    def __init__(self, records):
        self._records = records

    def get_node_records(self, ids):
        return {i: self._records.get(i) for i in ids}


class _FakeResolver:
    def __init__(self, blocks):
        self._blocks = blocks

    def inchikey_block(self, node_id, node_name, records):
        return self._blocks.get(node_id)


def test_kg_oracle_kg_block_from_record():
    linker = _FakeLinker(
        {"CHEBI:1": {"name": "glucose", "equivalent_ids": {"INCHIKEY": ["WQZGKKKJIJFFOK-GASJEMHNSA-N"]}}}
    )
    oracle = KGStructureOracle(_FakeResolver({}), linker)
    assert oracle.kg_block("CHEBI:1") == "WQZGKKKJIJFFOK"


def test_kg_oracle_kg_block_none_when_no_structure():
    linker = _FakeLinker({"CHEBI:2": {"name": "x", "equivalent_ids": {}}})
    oracle = KGStructureOracle(_FakeResolver({"CHEBI:2": "FALLBACKBLOCK0"}), linker)
    assert oracle.kg_block("CHEBI:2") is None
    # resolved_block delegates to the resolver (fallback path)
    assert oracle.resolved_block("CHEBI:2") == "FALLBACKBLOCK0"


def test_run_module_imports():
    # orchestration module imports without constructing a live Mapper
    import studies.external_benchmarks.run as run_mod

    assert hasattr(run_mod, "orchestrate")
    assert hasattr(run_mod, "main")
