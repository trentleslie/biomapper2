"""Unit 4 (layer a) — reconciliation (offline)."""

from __future__ import annotations

import copy

import pandas as pd
import pytest

from studies.external_benchmarks.adapters.hajjar import HAS_STRUCTURE_COL
from studies.external_benchmarks.config import HAJJAR
from studies.external_benchmarks.scorers.paper_metric import score_paper_metric
from studies.external_benchmarks.scorers.structure_oracle_scorer import score_structure_oracle
from studies.external_benchmarks.verify import reconcile

GLU, ALA, CAF, ETH = "WQZGKKKJIJFFOK", "QNAYBMKLOCPYGJ", "RYYVLZVUVIJVGH", "LFQSCWFLJHTTHZ"


@pytest.fixture
def mapped_df():
    return pd.DataFrame(
        {
            HAJJAR.name_column: ["D-Glucose", "L-Alanine", "Caffeine", "Mystery lipid", "Ethanol"],
            HAJJAR.gold_inchikey_column: [
                f"{GLU}-GASJEMHNSA-N",
                f"{ALA}-REOHCLBHSA-N",
                f"{CAF}-UHFFFAOYSA-N",
                "",
                f"{ETH}-UHFFFAOYSA-N",
            ],
            HAS_STRUCTURE_COL: [True, True, True, False, True],
            "chosen_kg_id": ["CHEBI:4167", "CHEBI:DIFF", "CHEBI:WRONG", "CHEBI:12345", "CHEBI:16236"],
        }
    )


@pytest.fixture
def oracle(fake_oracle_factory):
    kg = {
        "CHEBI:4167": GLU,
        "CHEBI:DIFF": ALA,
        "CHEBI:WRONG": "AAAAAAAAAAAAAA",
        "CHEBI:12345": "BBBBBBBBBBBBBB",
        "CHEBI:16236": None,
    }
    return fake_oracle_factory(kg, {"CHEBI:16236": ETH})


@pytest.fixture
def results(mapped_df, oracle):
    return {
        "structure": score_structure_oracle(mapped_df, HAJJAR, oracle, vocab="CHEBI"),
        "paper": score_paper_metric(mapped_df, HAJJAR, vocab="CHEBI"),
    }


def test_consistent_artifacts_reconcile(results, mapped_df, oracle):
    report = reconcile(results, mapped_df, HAJJAR, oracle)
    assert report.passed
    assert report.mismatches == []


def test_tampered_accuracy_fails_naming_metric(results, mapped_df, oracle):
    tampered = copy.deepcopy(results)
    tampered["structure"]["comparable_core"]["top1_accuracy"] = 1.0  # was 0.75
    report = reconcile(tampered, mapped_df, HAJJAR, oracle)
    assert not report.passed
    assert any(m["metric"] == "top1_accuracy" for m in report.mismatches)


def test_tampered_fallback_count_fails(results, mapped_df, oracle):
    tampered = copy.deepcopy(results)
    tampered["structure"]["fallback_bucket"]["count"] = 0  # was 1
    report = reconcile(tampered, mapped_df, HAJJAR, oracle)
    assert not report.passed
    assert any(m["metric"] == "fallback_count" for m in report.mismatches)


def test_tampered_match_rate_fails(results, mapped_df, oracle):
    tampered = copy.deepcopy(results)
    tampered["paper"]["match_rate"] = 0.5  # was 1.0
    report = reconcile(tampered, mapped_df, HAJJAR, oracle)
    assert not report.passed
    assert any(m["metric"] == "match_rate" for m in report.mismatches)
