"""metLinkR ManualMappings adapter transform (offline; fixture in, input_df + card out)."""

from __future__ import annotations

import io
import zipfile

import pandas as pd
import pytest

from studies.external_benchmarks.adapters import metlinkr as ml
from studies.external_benchmarks.adapters.metlinkr import (
    INPUT_ROW_ID_COL,
    MappingsNotResolvedError,
    NoManualMappingsError,
    build_card,
    build_input_df,
    fetch_manual_mappings,
    load_metlinkr,
    sha256_bytes,
)
from studies.external_benchmarks.config import (
    METLINKR,
    NEEDS_FETCHING_SENTINEL_METLINKR,
    MetLinkRDatasetConfig,
)


@pytest.fixture
def raw_mm_df():
    """A tiny stand-in for ManualMappings.csv (raw column names) across 2 COMETS datasets.

    - group 1: glucose in fileA + fileB (a curator CROSS-DATASET link).
    - group 2: caffeine only in fileA (a single-member group — no cross pair).
    - Row 4 has a blank name (a curator row with no queryable name) -> dropped.
    - Provided ids use R ``NA`` and blanks (normalized to empty); one bare HMDB, one bare PubChem.
    """
    return pd.DataFrame(
        {
            "SOURCE_FILE": ["fileA.xlsx", "fileB.xlsx", "fileA.xlsx", "fileB.xlsx"],
            "IPT_METABID": ["m1", "m2", "m3", "m4"],
            "IPT_METABOLITE_NAME": ["glucose", "D-glucose", "caffeine", ""],
            "IPT_HMDB_ID": ["HMDB0000122", "NA", "", "HMDB0000201"],
            "IPT_PUBCHEM": ["", "5793", "2519", ""],
            "Manual_Metabolite_Group_Label": ["1", "1", "2", "3"],
        }
    )


def test_input_df_has_name_query_and_held_out_gold(raw_mm_df):
    df = build_input_df(raw_mm_df, METLINKR)
    assert METLINKR.name_column in df.columns
    # blank-name row dropped: 4 raw rows -> 3 queryable names
    assert len(df) == 3
    assert "glucose" in set(df[METLINKR.name_column])
    assert "" not in set(df[METLINKR.name_column])
    # curator grouping held out verbatim
    assert set(df[METLINKR.group_label_column]) == {"1", "2"}
    # NA / blank provided ids normalized to empty; real ids kept
    glu = df[df[METLINKR.name_column] == "glucose"].iloc[0]
    assert glu[METLINKR.gold_hmdb_column] == "HMDB0000122"
    dglu = df[df[METLINKR.name_column] == "D-glucose"].iloc[0]
    assert dglu[METLINKR.gold_hmdb_column] == ""  # "NA" normalized away
    assert dglu[METLINKR.gold_pubchem_column] == "5793"


def test_input_row_id_is_stable_and_source_scoped(raw_mm_df):
    df = build_input_df(raw_mm_df, METLINKR)
    ids = list(df[INPUT_ROW_ID_COL])
    assert len(set(ids)) == len(ids)  # unique per surviving row
    # source-file-scoped: fileA glucose and fileB D-glucose get distinct ids even at same group
    assert ids[0].startswith("fileA.xlsx:")
    assert ids[1].startswith("fileB.xlsx:")


def test_card_reports_cross_dataset_link_stats_and_coverage(raw_mm_df):
    card = build_card(raw_mm_df, source_sha="deadbeef", config=METLINKR)
    assert card["input_type"] == "name"
    assert card["input_mode"] == "name_only"
    assert card["n_names"] == 3
    stats = card["curator_link_stats"]
    # group 1 spans fileA+fileB -> 1 cross-dataset group, 1 cross-dataset pair; group 2 is singleton
    assert stats["n_cross_dataset_groups"] == 1
    assert stats["cross_dataset_pairs"] == 1
    # provided-id coverage: glucose(HMDB), D-glucose(PubChem), caffeine(PubChem) -> 3 of 3 have any
    assert card["provided_id_coverage"]["any"]["n"] == 3
    assert card["source_doi"] == METLINKR.source_doi


def test_load_from_dataframe_sha_is_deterministic(raw_mm_df):
    bundle = load_metlinkr(raw_mm_df, METLINKR)
    expected = sha256_bytes(raw_mm_df.to_csv(index=False).encode("utf-8"))
    assert bundle.card["source_sha256"] == expected
    assert bundle.card["n_names"] == 3


def test_anti_trivial_config_rejects_grouping_as_query():
    # A config whose held-out grouping IS the query would leak the curator link into the input.
    with pytest.raises(ValueError, match="anti-trivial"):
        MetLinkRDatasetConfig(name_column="curator_group_label")


def test_fetch_fails_loud_on_placeholder():
    placeholder = MetLinkRDatasetConfig(fetch_url=f"{NEEDS_FETCHING_SENTINEL_METLINKR}mirror")
    with pytest.raises(MappingsNotResolvedError, match="needs-fetching"):
        fetch_manual_mappings(placeholder)


def _nested_bundle(inner_csv: bytes) -> bytes:
    """Build a EuropePMC-style bundle: outer zip containing si_003.zip containing ManualMappings.csv."""
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("ManualMappings.csv", inner_csv)
        z.writestr("__MACOSX/._ManualMappings.csv", b"resource-fork-junk")
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as z:
        z.writestr("pr4c01051_si_003.zip", inner.getvalue())
        z.writestr("pr4c01051_si_002.pdf", b"%PDF-not-the-mappings")
    return outer.getvalue()


def test_extract_manual_mappings_from_nested_bundle(raw_mm_df):
    csv_bytes = raw_mm_df.to_csv(index=False).encode("utf-8")
    bundle = _nested_bundle(csv_bytes)
    got = ml._extract_manual_mappings_bytes(bundle, METLINKR)
    assert b"Manual_Metabolite_Group_Label" in got  # the mappings, not the pdf/resource fork


def test_fetch_is_isolated_and_extracts(monkeypatch, raw_mm_df):
    # load_metlinkr("fetch") must route through fetch_manual_mappings (stubbed; no network).
    csv_bytes = raw_mm_df.to_csv(index=False).encode("utf-8")
    monkeypatch.setattr(ml, "fetch_manual_mappings", lambda config, **kw: csv_bytes)
    bundle = load_metlinkr("fetch", METLINKR)
    assert bundle.card["n_names"] == 3


def test_extract_fails_loud_when_no_mappings():
    empty = io.BytesIO()
    with zipfile.ZipFile(empty, "w") as z:
        z.writestr("pr4c01051_si_003.zip", b"not-a-zip")
    with pytest.raises((NoManualMappingsError, zipfile.BadZipFile)):
        ml._extract_manual_mappings_bytes(empty.getvalue(), METLINKR)


class _FakeResp:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        return None


def test_fetch_raises_on_sha_mismatch(monkeypatch, raw_mm_df):
    # EuropePMC serves a bundle whose ManualMappings.csv bytes do NOT match the config's pinned SHA
    # (the fixture differs from the real curator oracle) -> fail LOUD before any scoring.
    bundle = _nested_bundle(raw_mm_df.to_csv(index=False).encode("utf-8"))
    import requests

    monkeypatch.setattr(requests, "get", lambda url, timeout=90.0: _FakeResp(bundle))
    with pytest.raises(RuntimeError, match="SHA256 mismatch"):
        fetch_manual_mappings(METLINKR)  # METLINKR pins the real SHA; the fixture won't match


def test_fetch_returns_bytes_when_sha_matches(monkeypatch, raw_mm_df):
    # A config whose expected SHA equals the fetched ManualMappings bytes' SHA passes verification.
    csv_bytes = raw_mm_df.to_csv(index=False).encode("utf-8")
    bundle = _nested_bundle(csv_bytes)
    cfg = MetLinkRDatasetConfig(expected_manual_mappings_sha256=sha256_bytes(csv_bytes))
    import requests

    monkeypatch.setattr(requests, "get", lambda url, timeout=90.0: _FakeResp(bundle))
    got = fetch_manual_mappings(cfg)
    assert sha256_bytes(got) == cfg.expected_manual_mappings_sha256
    assert b"Manual_Metabolite_Group_Label" in got
