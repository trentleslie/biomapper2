"""MetaboliteAnnotator MAF adapter transform (offline; fixture in, input_df + card out)."""

from __future__ import annotations

import pandas as pd
import pytest

from studies.external_benchmarks.adapters import metaboliteannotator as maf
from studies.external_benchmarks.adapters.metaboliteannotator import (
    AccessionNotResolvedError,
    build_card,
    build_input_df,
    fetch_maf_set,
    load_metaboliteannotator,
    sha256_bytes,
)
from studies.external_benchmarks.config import METABOLITEANNOTATOR_POS


@pytest.fixture
def raw_maf_df():
    """A tiny stand-in for a MetaboLights MAF (m_*.tsv) concatenated across 2 of the 6 sets.

    ``source_accession`` marks which set each row came from (per-accession coverage). Row 3 has a
    blank name (a MAF feature with no identification) -> dropped, not a queryable input name. Row 5
    ships no database_identifier (unmatched in the source) -> retained as a name but 0 gold coverage.
    """
    return pd.DataFrame(
        {
            "database_identifier": ["CHEBI:17234", "CHEBI:16977|CHEBI:57972", "CHEBI:15422", "", "CHEBI:27732"],
            "metabolite_identification": ["glucose", "L-alanine", "", "ATP", "caffeine"],
            "smiles": ["OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O", "C[C@@H](C(=O)O)N", "x", "", ""],
            "chemical_formula": ["C6H12O6", "C3H7NO2", "C10H16N5O13P3", "", "C8H10N4O2"],
            "source_accession": ["MTBLS111", "MTBLS111", "MTBLS111", "MTBLS222", "MTBLS222"],
        }
    )


def test_input_df_has_name_query_and_held_out_gold(raw_maf_df):
    df = build_input_df(raw_maf_df, METABOLITEANNOTATOR_POS)
    assert METABOLITEANNOTATOR_POS.name_column in df.columns
    # blank-name feature dropped: 5 raw rows -> 4 queryable names
    assert len(df) == 4
    assert "glucose" in set(df[METABOLITEANNOTATOR_POS.name_column])
    assert "" not in set(df[METABOLITEANNOTATOR_POS.name_column])
    # gold database_identifier held out verbatim (|-multi preserved for split_gold_curies)
    ala = df[df[METABOLITEANNOTATOR_POS.name_column] == "L-alanine"].iloc[0]
    assert ala[METABOLITEANNOTATOR_POS.gold_id_column] == "CHEBI:16977|CHEBI:57972"
    # a name present in the source but with no database_identifier is kept with empty gold
    atp = df[df[METABOLITEANNOTATOR_POS.name_column] == "ATP"].iloc[0]
    assert atp[METABOLITEANNOTATOR_POS.gold_id_column] == ""


def test_card_reports_mode_and_per_accession_coverage(raw_maf_df):
    card = build_card(raw_maf_df, source_sha="deadbeef", config=METABOLITEANNOTATOR_POS)
    assert card["mode"] == "positive"
    assert card["input_type"] == "name"
    assert card["n_names"] == 4
    # per-accession name counts (traceability): MTBLS111 contributes glucose+L-alanine (2),
    # MTBLS222 contributes ATP+caffeine (2) after the blank-name drop
    assert card["per_accession"]["MTBLS111"]["n_names"] == 2
    assert card["per_accession"]["MTBLS222"]["n_names"] == 2
    # gold-ID coverage: 3 of 4 names carry a database_identifier (ATP does not)
    assert card["gold_id_coverage"]["n"] == 3
    assert card["accessions_status"] == "needs-fetching"
    assert card["source_doi"] == METABOLITEANNOTATOR_POS.source_doi


def test_load_from_dataframe_sha_is_deterministic(raw_maf_df):
    bundle = load_metaboliteannotator(raw_maf_df, METABOLITEANNOTATOR_POS)
    expected = sha256_bytes(raw_maf_df.to_csv(index=False).encode("utf-8"))
    assert bundle.card["source_sha256"] == expected
    assert bundle.card["n_names"] == 4


def test_fetch_fails_loud_on_placeholder_accession():
    # A live fetch against an unresolved placeholder must refuse, not silently produce nothing.
    with pytest.raises(AccessionNotResolvedError, match="needs-fetching"):
        fetch_maf_set(METABOLITEANNOTATOR_POS.accessions[0], METABOLITEANNOTATOR_POS)


def test_load_over_accessions_fails_loud_when_unresolved():
    # Passing the config's accessions tuple (all placeholders) must fail loud before any scoring.
    with pytest.raises(AccessionNotResolvedError):
        load_metaboliteannotator(METABOLITEANNOTATOR_POS.accessions, METABOLITEANNOTATOR_POS)


def test_fetch_is_isolated(monkeypatch, raw_maf_df):
    # load_metaboliteannotator(accessions) must route through fetch_maf_set (stubbed; no network).
    monkeypatch.setattr(maf, "fetch_maf_set", lambda acc, config, **kw: raw_maf_df.assign(source_accession=acc))
    bundle = load_metaboliteannotator(("MTBLS111", "MTBLS222"), METABOLITEANNOTATOR_POS)
    # two stubbed sets concatenated -> 8 raw rows, blank names dropped per set (2 blanks) -> ...
    assert bundle.card["n_names"] == 8  # 4 queryable names per set * 2 sets
    assert set(bundle.card["per_accession"]) == {"MTBLS111", "MTBLS222"}
