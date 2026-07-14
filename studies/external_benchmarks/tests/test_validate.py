"""Unit 4 (layer b) — validation (offline; RDKit used for the second-source check)."""

from __future__ import annotations

import pandas as pd

from studies.external_benchmarks.adapters.hajjar import build_input_df
from studies.external_benchmarks.config import HAJJAR, HAJJAR_COMPETITORS, CompetitorResult
from studies.external_benchmarks.scorers.structure_oracle_scorer import score_structure_oracle
from studies.external_benchmarks.validate import (
    citation_spot_check,
    protocol_parity_gate,
    recompute_fallback_bucket,
    second_source_structure_check,
    spot_check_gold_column,
    validate_all,
)

ETH_IK = "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"
CAF_IK = "RYYVLZVUVIJVGH-UHFFFAOYSA-N"


# ---------- (a) gold-column spot-check ----------


def test_spot_check_passes_on_faithful_adapter(raw_hajjar_df):
    input_df = build_input_df(raw_hajjar_df, HAJJAR)
    report = spot_check_gold_column(input_df, raw_hajjar_df, HAJJAR)
    assert report.passed


def test_spot_check_fails_on_swapped_gold_column(raw_hajjar_df):
    input_df = build_input_df(raw_hajjar_df, HAJJAR)
    # inject upstream corruption: shift the gold column by one row
    input_df[HAJJAR.gold_inchikey_column] = input_df[HAJJAR.gold_inchikey_column].shift(1).fillna("X")
    report = spot_check_gold_column(input_df, raw_hajjar_df, HAJJAR)
    assert not report.passed
    assert any(f["check"] == "gold_column_spotcheck" for f in report.failures)


# ---------- (b) second-source structure via RDKit ----------


def test_structure_check_passes_when_smiles_agrees():
    df = pd.DataFrame(
        {
            HAJJAR.name_column: ["Ethanol"],
            HAJJAR.gold_inchikey_column: [ETH_IK],
            HAJJAR.gold_smiles_column: ["CCO"],
        }
    )
    report = second_source_structure_check(df, HAJJAR)
    assert report.passed


def test_structure_check_fails_on_mis_resolved_structure():
    # gold InChIKey (caffeine) disagrees with the SMILES (ethanol) -> corruption caught
    df = pd.DataFrame(
        {
            HAJJAR.name_column: ["Corrupted"],
            HAJJAR.gold_inchikey_column: [CAF_IK],
            HAJJAR.gold_smiles_column: ["CCO"],
        }
    )
    report = second_source_structure_check(df, HAJJAR)
    assert not report.passed
    assert any(f["check"] == "second_source_structure" for f in report.failures)


def test_structure_check_skips_when_no_smiles():
    df = pd.DataFrame(
        {
            HAJJAR.name_column: ["NoSmiles"],
            HAJJAR.gold_inchikey_column: [ETH_IK],
            HAJJAR.gold_smiles_column: [""],
        }
    )
    report = second_source_structure_check(df, HAJJAR)
    assert report.passed  # not failed
    assert report.skips  # skipped with logged reason


# ---------- (c) fallback bucket recompute ----------


def test_fallback_recompute_matches(fake_oracle_factory):
    df = pd.DataFrame(
        {
            HAJJAR.name_column: ["a", "b"],
            HAJJAR.gold_inchikey_column: ["AAAAAAAAAAAAAA-x-N", "BBBBBBBBBBBBBB-x-N"],
            "chosen_kg_id": ["CHEBI:1", "CHEBI:2"],
        }
    )
    oracle = fake_oracle_factory({"CHEBI:1": "AAAAAAAAAAAAAA", "CHEBI:2": None}, {"CHEBI:2": "BBBBBBBBBBBBBB"})
    results = {"structure": score_structure_oracle(df, HAJJAR, oracle)}
    report = recompute_fallback_bucket(results, df, HAJJAR, oracle)
    assert report.passed


def test_fallback_recompute_catches_tamper(fake_oracle_factory):
    df = pd.DataFrame(
        {HAJJAR.name_column: ["b"], HAJJAR.gold_inchikey_column: ["BBBBBBBBBBBBBB-x-N"], "chosen_kg_id": ["CHEBI:2"]}
    )
    oracle = fake_oracle_factory({"CHEBI:2": None}, {"CHEBI:2": "BBBBBBBBBBBBBB"})
    results = {"structure": {"fallback_bucket": {"count": 0}}}  # tampered (true count is 1)
    report = recompute_fallback_bucket(results, df, HAJJAR, oracle)
    assert not report.passed


# ---------- (d) protocol-parity gate ----------


def test_protocol_parity_within_tolerance_passes():
    report = protocol_parity_gate(0.94, 0.95, tolerance=0.02)
    assert report.passed


def test_protocol_parity_outside_tolerance_blocks():
    report = protocol_parity_gate(0.80, 0.95, tolerance=0.02)
    assert not report.passed
    assert any(f["check"] == "protocol_parity_gate" for f in report.failures)


# ---------- (e) citation spot-check ----------


def test_citation_check_passes_on_registry_competitors():
    report = citation_spot_check(HAJJAR_COMPETITORS)
    assert report.passed


def test_citation_check_fails_when_doi_missing():
    bad = [CompetitorResult(tool="X", metric="m", input_type="name", value=0.9, doi="", table_ref="T1")]
    report = citation_spot_check(bad)
    assert not report.passed
    assert any(f["check"] == "citation_spotcheck" for f in report.failures)


# ---------- validate_all integration: injected corruption fails validation ----------


def test_validate_all_catches_injected_corruption(raw_hajjar_df, fake_oracle_factory):
    input_df = build_input_df(raw_hajjar_df, HAJJAR)
    corrupted = input_df.copy()
    corrupted[HAJJAR.gold_inchikey_column] = corrupted[HAJJAR.gold_inchikey_column].shift(1).fillna("X")
    mapped = corrupted.copy()
    mapped["chosen_kg_id"] = ["CHEBI:1", "CHEBI:2", "CHEBI:3", "CHEBI:4", "CHEBI:5"]
    oracle = fake_oracle_factory({f"CHEBI:{i}": None for i in range(1, 6)})
    results = {"structure": score_structure_oracle(mapped, HAJJAR, oracle)}
    report = validate_all(
        input_df=corrupted,
        source_df=raw_hajjar_df,
        mapped_df=mapped,
        results=results,
        config=HAJJAR,
        oracle=oracle,
        competitors=HAJJAR_COMPETITORS,
        protocol_parity=(0.95, 0.95, 0.02),
    )
    assert not report.passed  # the swapped gold column is caught
    assert any(f["check"] == "gold_column_spotcheck" for f in report.failures)
