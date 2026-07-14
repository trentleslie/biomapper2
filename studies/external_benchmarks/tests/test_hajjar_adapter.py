"""Unit 1 — Hajjar adapter transform (offline; fixture in, input_df + card out)."""

from __future__ import annotations

from studies.external_benchmarks.adapters import hajjar
from studies.external_benchmarks.adapters.hajjar import (
    HAS_STRUCTURE_COL,
    build_card,
    build_input_df,
    load_hajjar,
    sha256_bytes,
)


def test_input_df_has_name_query_and_held_out_gold(raw_hajjar_df, hajjar_config):
    input_df = build_input_df(raw_hajjar_df, hajjar_config)
    # name query present
    assert hajjar_config.name_column in input_df.columns
    assert input_df[hajjar_config.name_column].iloc[0] == "D-Glucose"
    # held-out gold columns present and verbatim
    assert hajjar_config.gold_chebi_column in input_df.columns
    assert hajjar_config.gold_inchikey_column in input_df.columns
    assert input_df[hajjar_config.gold_inchikey_column].iloc[0] == "WQZGKKKJIJFFOK-GASJEMHNSA-N"


def test_gold_inchikey_preserved_verbatim(raw_hajjar_df, hajjar_config):
    input_df = build_input_df(raw_hajjar_df, hajjar_config)
    src = raw_hajjar_df["InChIKey"].tolist()
    got = input_df[hajjar_config.gold_inchikey_column].tolist()
    # identity is load-bearing: the oracle must equal the source column exactly
    assert got == [s.strip() for s in src]


def test_missing_gold_inchikey_row_retained_and_flagged(raw_hajjar_df, hajjar_config):
    input_df = build_input_df(raw_hajjar_df, hajjar_config)
    # "Mystery lipid" has empty InChIKey -> retained but marked no-structure
    assert len(input_df) == len(raw_hajjar_df)
    mystery = input_df[input_df[hajjar_config.name_column] == "Mystery lipid"].iloc[0]
    assert mystery[HAS_STRUCTURE_COL] is False or mystery[HAS_STRUCTURE_COL] == False  # noqa: E712
    glucose = input_df[input_df[hajjar_config.name_column] == "D-Glucose"].iloc[0]
    assert bool(glucose[HAS_STRUCTURE_COL]) is True


def test_card_coverage_matches_fixture(raw_hajjar_df, hajjar_config):
    card = build_card(raw_hajjar_df, source_sha="deadbeef", config=hajjar_config)
    assert card["n_rows"] == 5
    assert card["input_type"] == "name"
    # 4 of 5 rows carry a gold InChIKey (Mystery lipid does not)
    assert card["coverage"]["gold_inchikey"]["n"] == 4
    assert card["coverage"]["gold_chebi"]["n"] == 5
    assert card["source_doi"] == hajjar_config.source_doi


def test_card_sha_matches_fetched_bytes(hajjar_config):
    raw_bytes = b"Metabolite name,ChEBI ID,InChIKey,SMILES\nEthanol,CHEBI:16236,LFQSCWFLJHTTHZ-UHFFFAOYSA-N,CCO\n"
    bundle = load_hajjar(raw_bytes, hajjar_config)
    assert bundle.card["source_sha256"] == sha256_bytes(raw_bytes)
    assert bundle.card["n_rows"] == 1
    assert bundle.input_df[hajjar_config.name_column].iloc[0] == "Ethanol"


def test_fetch_supplement_is_isolated(monkeypatch, hajjar_config):
    # load_hajjar(url) must route through fetch_supplement, which we stub — no real network.
    raw_bytes = (
        b"Metabolite name,ChEBI ID,InChIKey,SMILES\n"
        b"Caffeine,CHEBI:27732,RYYVLZVUVIJVGH-UHFFFAOYSA-N,Cn1cnc2c1c(=O)n(C)c(=O)n2C\n"
    )
    monkeypatch.setattr(hajjar, "fetch_supplement", lambda url, **kw: raw_bytes)
    bundle = load_hajjar("https://example.invalid/supplement.csv", hajjar_config)
    assert bundle.card["source_sha256"] == sha256_bytes(raw_bytes)
    assert bundle.input_df[hajjar_config.name_column].iloc[0] == "Caffeine"
