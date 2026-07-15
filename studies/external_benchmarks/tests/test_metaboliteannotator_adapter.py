"""MetaboliteAnnotator MAF adapter transform (offline; fixture in, input_df + card out)."""

from __future__ import annotations

import pandas as pd
import pytest

from studies.external_benchmarks.adapters import metaboliteannotator as maf
from studies.external_benchmarks.adapters.metaboliteannotator import (
    SOURCE_ACCESSION_COL,
    AccessionNotResolvedError,
    NoMafError,
    build_card,
    build_input_df,
    fetch_maf_set,
    load_metaboliteannotator,
    select_maf_filename,
    sha256_bytes,
)
from studies.external_benchmarks.config import (
    METABOLITEANNOTATOR_NEG,
    METABOLITEANNOTATOR_POS,
    NEEDS_FETCHING_SENTINEL,
)

# A realistic MetaboLights ISA-Tab study file listing: investigation/sample/assay descriptors, raw
# data, and TWO MAF tables (one per ion mode). The adapter must select the m_*.tsv MAF, never the
# study bundle or a descriptor.
STUDY_FILES = [
    "i_Investigation.txt",
    "s_MTBLS111.txt",
    "a_MTBLS111_POS_mass_spectrometry.txt",
    "a_MTBLS111_NEG_mass_spectrometry.txt",
    "m_MTBLS111_POS_mass_spectrometry_v2_maf.tsv",
    "m_MTBLS111_NEG_mass_spectrometry_v2_maf.tsv",
    "FILES/raw_pos.raw",
]


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


def test_duplicate_names_collapse_to_unique_per_accession_with_unioned_gold():
    # The paper's denominator is UNIQUE names per study: duplicate MAF features sharing a name collapse
    # to one input row, unioning their held-out gold CURIEs so no reference identifier is lost.
    raw = pd.DataFrame(
        {
            "database_identifier": ["CHEBI:17234", "CHEBI:4167", "HMDB:HMDB0000122", "CHEBI:30769"],
            "metabolite_identification": ["glucose", "glucose", "glucose", "citrate"],
            "smiles": ["", "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O", "", "OC(=O)CC(O)(CC(=O)O)C(=O)O"],
            "chemical_formula": ["C6H12O6", "C6H12O6", "C6H12O6", "C6H8O7"],
            "source_accession": ["MTBLSx", "MTBLSx", "MTBLSx", "MTBLSx"],
        }
    )
    df = build_input_df(raw, METABOLITEANNOTATOR_POS)
    assert len(df) == 2  # 3x glucose + 1x citrate -> 2 unique names
    glu = df[df[METABOLITEANNOTATOR_POS.name_column] == "glucose"].iloc[0]
    # gold CURIEs unioned across the 3 glucose features (order-preserving, deduped)
    assert glu[METABOLITEANNOTATOR_POS.gold_id_column] == "CHEBI:17234|CHEBI:4167|HMDB:HMDB0000122"
    # first non-blank SMILES kept
    assert glu[METABOLITEANNOTATOR_POS.gold_smiles_column] == "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O"


def test_same_name_in_two_studies_counts_once_per_study():
    # Dedup is PER study, not global: a name shared across two MetaboLights sets stays two input rows
    # (the paper's per-study totals sum across sets).
    raw = pd.DataFrame(
        {
            "database_identifier": ["CHEBI:17234", "CHEBI:17234"],
            "metabolite_identification": ["glucose", "glucose"],
            "smiles": ["", ""],
            "chemical_formula": ["C6H12O6", "C6H12O6"],
            "source_accession": ["MTBLSa", "MTBLSb"],
        }
    )
    df = build_input_df(raw, METABOLITEANNOTATOR_POS)
    assert len(df) == 2
    assert set(df[SOURCE_ACCESSION_COL]) == {"MTBLSa", "MTBLSb"}


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
    assert card["accessions_status"] == "resolved"
    assert card["source_doi"] == METABOLITEANNOTATOR_POS.source_doi


def test_load_from_dataframe_sha_is_deterministic(raw_maf_df):
    bundle = load_metaboliteannotator(raw_maf_df, METABOLITEANNOTATOR_POS)
    expected = sha256_bytes(raw_maf_df.to_csv(index=False).encode("utf-8"))
    assert bundle.card["source_sha256"] == expected
    assert bundle.card["n_names"] == 4


def test_fetch_fails_loud_on_placeholder_accession():
    # The config's accessions are now resolved, but the fail-loud guard must still refuse any future
    # unresolved placeholder rather than silently produce nothing.
    with pytest.raises(AccessionNotResolvedError, match="needs-fetching"):
        fetch_maf_set(f"{NEEDS_FETCHING_SENTINEL}1", METABOLITEANNOTATOR_POS)


def test_load_over_accessions_fails_loud_when_unresolved():
    # Passing a placeholder accession tuple must fail loud before any scoring (the guard still bites).
    with pytest.raises(AccessionNotResolvedError):
        load_metaboliteannotator(
            (f"{NEEDS_FETCHING_SENTINEL}1", f"{NEEDS_FETCHING_SENTINEL}2"), METABOLITEANNOTATOR_POS
        )


def test_fetch_is_isolated(monkeypatch, raw_maf_df):
    # load_metaboliteannotator(accessions) must route through fetch_maf_set (stubbed; no network).
    monkeypatch.setattr(maf, "fetch_maf_set", lambda acc, config, **kw: raw_maf_df.assign(source_accession=acc))
    bundle = load_metaboliteannotator(("MTBLS111", "MTBLS222"), METABOLITEANNOTATOR_POS)
    # two stubbed sets concatenated -> 8 raw rows, blank names dropped per set (2 blanks) -> ...
    assert bundle.card["n_names"] == 8  # 4 queryable names per set * 2 sets
    assert set(bundle.card["per_accession"]) == {"MTBLS111", "MTBLS222"}


# --- MAF resolution (Greptile PR#22): fetch the m_*.tsv MAF, never the study bundle ---------------


def test_select_maf_filename_disambiguates_by_mode():
    # Two MAFs (pos + neg) -> ion mode picks exactly one; descriptors/raw files are never MAFs.
    assert select_maf_filename(STUDY_FILES, "positive") == "m_MTBLS111_POS_mass_spectrometry_v2_maf.tsv"
    assert select_maf_filename(STUDY_FILES, "negative") == "m_MTBLS111_NEG_mass_spectrometry_v2_maf.tsv"


def test_select_maf_filename_single_maf_used_regardless_of_mode():
    files = ["i_Investigation.txt", "s_x.txt", "a_x.txt", "m_MTBLS999_maf.tsv"]
    assert select_maf_filename(files, "positive") == "m_MTBLS999_maf.tsv"


def test_select_maf_filename_no_maf_fails_loud():
    # A study with no m_*.tsv (only the bundle / descriptors) must fail loud, never parse a non-MAF.
    with pytest.raises(NoMafError, match="no m_.*MAF"):
        select_maf_filename(["i_Investigation.txt", "s_x.txt", "a_x.txt", "MTBLS999.zip"], "positive")


def test_select_maf_filename_ambiguous_fails_loud():
    # Two MAFs neither of which carries the mode token -> refuse to guess.
    with pytest.raises(NoMafError, match="does not select exactly one"):
        select_maf_filename(["m_run1_maf.tsv", "m_run2_maf.tsv"], "positive")


def test_fetch_maf_set_selects_maf_not_study_bundle(monkeypatch, raw_maf_df):
    # End-to-end selection: list files (mocked), pick the m_*.tsv, download+parse THAT file. The
    # downloader refuses anything that is not the selected MAF, proving the bundle is never fetched.
    monkeypatch.setattr(maf, "list_study_files", lambda acc, config, **kw: STUDY_FILES)

    def fake_download(accession, filename, config, **kw):
        assert maf._is_maf_filename(filename), f"adapter fetched a non-MAF file: {filename!r}"
        assert "POS" in filename  # positive-mode config must select the POS MAF
        return raw_maf_df.to_csv(sep="\t", index=False).encode("utf-8")

    monkeypatch.setattr(maf, "_download_study_file", fake_download)
    df = fetch_maf_set("MTBLS111", METABOLITEANNOTATOR_POS)
    # records parsed from the MAF table (not the study payload), tagged with the accession
    assert METABOLITEANNOTATOR_POS.name_column in df.columns
    assert "glucose" in set(df[METABOLITEANNOTATOR_POS.name_column])
    assert set(df[SOURCE_ACCESSION_COL]) == {"MTBLS111"}


def test_fetch_maf_set_negative_mode_selects_neg_maf(monkeypatch, raw_maf_df):
    monkeypatch.setattr(maf, "list_study_files", lambda acc, config, **kw: STUDY_FILES)

    def fake_download(accession, filename, config, **kw):
        assert "NEG" in filename
        return raw_maf_df.to_csv(sep="\t", index=False).encode("utf-8")

    monkeypatch.setattr(maf, "_download_study_file", fake_download)
    df = fetch_maf_set("MTBLS111", METABOLITEANNOTATOR_NEG)
    assert set(df[SOURCE_ACCESSION_COL]) == {"MTBLS111"}


def test_fetch_maf_set_no_maf_in_study_fails_loud(monkeypatch):
    # A resolved accession whose study ships no MAF must fail loud before any download/parse.
    monkeypatch.setattr(maf, "list_study_files", lambda acc, config, **kw: ["i_Investigation.txt", "MTBLS999.zip"])

    def boom(*a, **k):  # the downloader must never be reached
        raise AssertionError("download attempted despite no MAF")

    monkeypatch.setattr(maf, "_download_study_file", boom)
    with pytest.raises(NoMafError):
        fetch_maf_set("MTBLS999", METABOLITEANNOTATOR_POS)


def test_build_input_df_emits_unique_input_row_id_per_unique_name():
    # A name repeated WITHIN a study collapses to one row (unique-name denominator); the same name in
    # a DIFFERENT study stays a separate row. Each surviving row gets a distinct, accession-scoped,
    # stable input_row_id so the vocab-union merge keys cleanly.
    from studies.external_benchmarks.adapters.metaboliteannotator import INPUT_ROW_ID_COL

    raw = pd.DataFrame(
        {
            "database_identifier": ["CHEBI:17234", "CHEBI:17234", "CHEBI:17234"],
            "metabolite_identification": ["glucose", "glucose", "glucose"],
            "smiles": ["", "", ""],
            "source_accession": ["MTBLS111", "MTBLS111", "MTBLS222"],
        }
    )
    df = build_input_df(raw, METABOLITEANNOTATOR_POS)
    ids = list(df[INPUT_ROW_ID_COL])
    # two MTBLS111 glucose features collapse to one; MTBLS222 glucose stays separate -> 2 rows
    assert len(df) == 2
    assert len(set(ids)) == 2
    assert ids == ["MTBLS111:0", "MTBLS222:0"]
