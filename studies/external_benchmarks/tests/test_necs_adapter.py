"""NECS Metabolon adapter transform (offline; fixture in, input_df + card out)."""

from __future__ import annotations

import pandas as pd
import pytest

from studies.external_benchmarks.adapters import necs_metabolon as necs
from studies.external_benchmarks.adapters.necs_metabolon import (
    HAS_STRUCTURE_COL,
    build_card,
    build_input_df,
    load_necs,
    sha256_bytes,
)
from studies.external_benchmarks.config import NECS


@pytest.fixture
def raw_necs_df():
    """Tiny stand-in for the NECS MOESM5 table (Metabolon-style headers).

    Row 3 ("Unknown X") has no gold InChIKey/SMILES -> retained, coverage-only. Partial external
    annotation (only some rows carry HMDB/KEGG) mirrors NECS's real partial coverage.
    """
    return pd.DataFrame(
        {
            "CHEMICAL_NAME": ["glucose", "L-alanine", "Unknown X", "caffeine"],
            "INCHIKEY": [
                "WQZGKKKJIJFFOK-GASJEMHNSA-N",
                "QNAYBMKLOCPYGJ-REOHCLBHSA-N",
                "",
                "RYYVLZVUVIJVGH-UHFFFAOYSA-N",
            ],
            "SMILES": ["OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O", "C[C@@H](C(=O)O)N", "", "Cn1cnc2c1c(=O)n(C)c(=O)n2C"],
            "HMDB": ["HMDB0000122", "HMDB0000161", "", ""],
            "KEGG": ["C00031", "", "", "C07481"],
            "PUBCHEM": ["5793", "5950", "", "2519"],
            "CAS": ["50-99-7", "56-41-7", "", "58-08-2"],
            "REFMET": ["Glucose", "Alanine", "", "Caffeine"],
        }
    )


def test_input_df_has_name_query_and_held_out_gold(raw_necs_df):
    df = build_input_df(raw_necs_df, NECS)
    assert NECS.name_column in df.columns
    assert df[NECS.name_column].iloc[0] == "glucose"
    # gold InChIKey preserved verbatim (the structure oracle — identity is load-bearing)
    assert df[NECS.gold_inchikey_column].iloc[0] == "WQZGKKKJIJFFOK-GASJEMHNSA-N"
    assert df[NECS.gold_smiles_column].iloc[3].startswith("Cn1cnc2")
    # external-id gold columns resolved
    assert df["gold_hmdb"].iloc[0] == "HMDB0000122"
    assert df["gold_kegg"].iloc[3] == "C07481"


def test_missing_inchikey_row_retained_and_flagged(raw_necs_df):
    df = build_input_df(raw_necs_df, NECS)
    assert len(df) == len(raw_necs_df)  # coverage-only rows retained
    unknown = df[df[NECS.name_column] == "Unknown X"].iloc[0]
    assert bool(unknown[HAS_STRUCTURE_COL]) is False
    assert bool(df[df[NECS.name_column] == "glucose"].iloc[0][HAS_STRUCTURE_COL]) is True


def test_card_per_column_coverage(raw_necs_df):
    card = build_card(raw_necs_df, source_sha="deadbeef", config=NECS)
    assert card["n_rows"] == 4
    assert card["input_type"] == "name"
    # 3/4 rows carry a gold InChIKey (Unknown X does not)
    assert card["coverage"]["INCHIKEY"]["n"] == 3
    assert card["coverage"]["INCHIKEY"]["fraction"] == pytest.approx(0.75)
    # partial external annotation reflected per-column (2/4 HMDB, 2/4 KEGG)
    assert card["coverage"]["HMDB"]["n"] == 2
    assert card["coverage"]["KEGG"]["n"] == 2
    assert card["structure_oracle_column"] == NECS.gold_inchikey_column
    assert card["source_doi"] == NECS.source_doi


def test_missing_optional_column_yields_empty_zero_coverage():
    # A delivery lacking ChemSpider entirely -> empty column, 0 coverage (honest, not fabricated).
    raw = pd.DataFrame({"CHEMICAL_NAME": ["x"], "INCHIKEY": ["AAAAAAAAAAAAAA-BBBBBBBBFV-N"], "SMILES": ["CCO"]})
    card = build_card(raw, source_sha="s", config=NECS)
    assert card["coverage"]["CHEMSPIDER"]["n"] == 0
    df = build_input_df(raw, NECS)
    assert "gold_chemspider" in df.columns
    assert df["gold_chemspider"].iloc[0] == ""


def test_load_necs_sha_matches_bytes(raw_necs_df):
    # DataFrame source: SHA is over its canonical CSV bytes (deterministic pin for tests).
    bundle = load_necs(raw_necs_df, NECS)
    expected = sha256_bytes(raw_necs_df.to_csv(index=False).encode("utf-8"))
    assert bundle.card["source_sha256"] == expected
    assert bundle.input_df[NECS.name_column].iloc[0] == "glucose"


def test_fetch_is_isolated(monkeypatch, raw_necs_df):
    # load_necs(url) must route through fetch_supplement + parse_xlsx, both stubbed (no network).
    monkeypatch.setattr(necs, "fetch_supplement", lambda url, **kw: b"FAKE-XLSX-BYTES")
    monkeypatch.setattr(necs, "parse_xlsx", lambda raw, **kw: raw_necs_df)
    bundle = load_necs("https://example.invalid/moesm5.xlsx", NECS)
    assert bundle.card["source_sha256"] == necs.sha256_bytes(b"FAKE-XLSX-BYTES")
    assert bundle.card["n_rows"] == 4
