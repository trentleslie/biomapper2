"""NIST SRM 1950 / SRM1950-DB adapter transform (offline; fixture in, input_df + card out).

The SRM1950-DB CSV delivery ships HMDB_ID + NAME + SMILES but the INCHIKEY column is EMPTY, so the
independent structure-oracle InChIKey is DERIVED from the certified SMILES (RDKit, deterministic).
These tests pin that behaviour on an in-memory fixture and never touch the network.
"""

from __future__ import annotations

import pandas as pd
import pytest

from studies.external_benchmarks.adapters import srm1950 as srm
from studies.external_benchmarks.adapters.srm1950 import (
    HAS_STRUCTURE_COL,
    build_card,
    build_input_df,
    inchikey_from_smiles,
    load_srm1950,
    sha256_bytes,
)
from studies.external_benchmarks.config import SRM1950


@pytest.fixture
def raw_srm_df():
    """Tiny stand-in for the SRM1950-DB metabolites.csv (delivery headers).

    Mirrors the real delivery: INCHIKEY column present but EMPTY, structure carried in SMILES.
    Row 3 has an unparseable SMILES -> no derivable structure -> coverage-only. Row 4 ships an
    explicit INCHIKEY (defensive: a future delivery may populate it) which must be preferred.
    """
    return pd.DataFrame(
        {
            "HMDB_ID": ["HMDB0000001", "HMDB0000122", "HMDB0099999", "HMDB0000042"],
            "NAME": ["Cholic acid", "Glucose", "Mystery analyte", "Ethanol"],
            "SMILES": [
                "C[C@H](CCC(O)=O)[C@H]1CC[C@H]2[C@@H]3[C@H](O)C[C@@H]4C[C@H](O)CC[C@]4(C)[C@H]3C[C@H](O)[C@]12C",
                "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
                "not_a_valid_smiles",
                "CCO",
            ],
            "INCHIKEY": ["", "", "", "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"],
            "CHEMICAL_FORMULA": ["", "", "", ""],
            "AVERAGE_MASS": ["408.57", "180.16", "", "46.07"],
            "MONO_MASS": ["408.29", "180.06", "", "46.04"],
        }
    )


def test_inchikey_derived_from_smiles():
    # cholic acid SMILES -> its InChIKey (dataset's own structure, RDKit deterministic)
    ik = inchikey_from_smiles(
        "C[C@H](CCC(O)=O)[C@H]1CC[C@H]2[C@@H]3[C@H](O)C[C@@H]4C[C@H](O)CC[C@]4(C)[C@H]3C[C@H](O)[C@]12C"
    )
    assert ik == "BHQCQFFYRZLCQQ-OELDTZBJSA-N"
    assert inchikey_from_smiles("not_a_valid_smiles") == ""
    assert inchikey_from_smiles("") == ""


def test_input_df_derives_gold_inchikey_when_column_empty(raw_srm_df):
    df = build_input_df(raw_srm_df, SRM1950)
    assert SRM1950.name_column in df.columns
    assert df[SRM1950.name_column].iloc[0] == "Cholic acid"
    # empty INCHIKEY column -> derived from certified SMILES
    assert df[SRM1950.gold_inchikey_column].iloc[0] == "BHQCQFFYRZLCQQ-OELDTZBJSA-N"
    assert df[SRM1950.gold_inchikey_column].iloc[1] == "WQZGKKKJIJFFOK-GASJEMHNSA-N"
    # gold SMILES preserved for the charge-normalized variant
    assert df[SRM1950.gold_smiles_column].iloc[3] == "CCO"
    # The delivery's identifier column is dropped at acquisition, not carried as coverage: it was a
    # row index in accession clothing. See tests/test_row_index_gold_guard.py.
    assert "gold_hmdb" not in df.columns


def test_explicit_inchikey_column_preferred_over_derivation(raw_srm_df):
    df = build_input_df(raw_srm_df, SRM1950)
    # Ethanol row ships an explicit INCHIKEY -> taken verbatim (not re-derived)
    assert df[SRM1950.gold_inchikey_column].iloc[3] == "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"


def test_unparseable_smiles_row_is_coverage_only(raw_srm_df):
    df = build_input_df(raw_srm_df, SRM1950)
    assert len(df) == len(raw_srm_df)  # coverage-only rows retained
    mystery = df[df[SRM1950.name_column] == "Mystery analyte"].iloc[0]
    assert mystery[SRM1950.gold_inchikey_column] == ""
    assert bool(mystery[HAS_STRUCTURE_COL]) is False
    assert bool(df[df[SRM1950.name_column] == "Glucose"].iloc[0][HAS_STRUCTURE_COL]) is True


def test_card_per_column_coverage(raw_srm_df):
    card = build_card(raw_srm_df, source_sha="deadbeef", config=SRM1950)
    assert card["n_rows"] == 4
    assert card["input_type"] == "name"
    # 3/4 rows yield a gold InChIKey (Mystery analyte's SMILES doesn't parse)
    assert card["coverage"]["INCHIKEY"]["n"] == 3
    assert card["coverage"]["INCHIKEY"]["fraction"] == pytest.approx(0.75)
    # SMILES present on 4/4 (even the unparseable one is a present string)
    assert card["coverage"]["SMILES"]["n"] == 4
    assert "HMDB" not in card["coverage"]  # dropped: the delivery's identifier column was a row index
    assert card["structure_oracle_column"] == SRM1950.gold_inchikey_column
    assert card["structure_oracle_source"] == "derived_from_certified_smiles"
    assert card["source_doi"] == SRM1950.source_doi


def test_load_srm1950_sha_matches_bytes(raw_srm_df):
    bundle = load_srm1950(raw_srm_df, SRM1950)
    expected = sha256_bytes(raw_srm_df.to_csv(index=False).encode("utf-8"))
    assert bundle.card["source_sha256"] == expected
    assert bundle.input_df[SRM1950.name_column].iloc[0] == "Cholic acid"


def test_parse_csv_bytes(raw_srm_df):
    raw = raw_srm_df.to_csv(index=False).encode("utf-8")
    df = srm.parse_csv(raw)
    assert list(df.columns) == list(raw_srm_df.columns)
    assert df["NAME"].iloc[1] == "Glucose"


def test_fetch_is_isolated(monkeypatch, raw_srm_df):
    # load_srm1950(url) must route through fetch_supplement + parse_csv (both stubbed; no network).
    monkeypatch.setattr(srm, "fetch_supplement", lambda url, **kw: b"FAKE-CSV-BYTES")
    monkeypatch.setattr(srm, "parse_csv", lambda raw, **kw: raw_srm_df)
    bundle = load_srm1950("https://srm1950-data.wishartlab.com/metabolites.csv", SRM1950)
    assert bundle.card["source_sha256"] == srm.sha256_bytes(b"FAKE-CSV-BYTES")
    assert bundle.card["n_rows"] == 4
