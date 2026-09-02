"""Unit 4 driver — the one pure helper (provided-id kwarg selection); the live loop is operator-gated."""

from __future__ import annotations

from studies.external_benchmarks.ab_lipid_oracle_run import provided_id_kwargs


def test_prefers_gold_inchikey_then_hmdb_then_pubchem():
    row = {"gold_inchikey": "FHQVHHIBKUMWTI-OTMQOFQ-N", "gold_hmdb": "HMDB0005320", "gold_pubchem": "5283496"}
    assert provided_id_kwargs(row) == {
        "inchikey": "FHQVHHIBKUMWTI-OTMQOFQ-N",
        "hmdb": "HMDB0005320",
        "pubchem": "5283496",
    }


def test_reads_arivale_style_columns_and_blanks_to_none():
    row = {"HMDB_ID": "HMDB0009784", "PubChem_ID": "", "gold_inchikey": ""}
    out = provided_id_kwargs(row)
    assert out["hmdb"] == "HMDB0009784" and out["pubchem"] is None and out["inchikey"] is None
