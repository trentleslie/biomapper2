"""Pham name-disambiguation adapter transform (offline; Table 9 fixture in, input_df + card out).

The fixture encodes the paper's Table 9 ("Examples of mapping inconsistencies") — REAL ambiguous
names/abbreviations, source databases, DB ids, MetaNetX bridge ids, and canonical compounds. The
InChIKey values are SYNTHETIC but distinct per compound (documented): they stand in for the MetaNetX
``chem_prop`` structures the needs-reconstruction path supplies. The transform is structure-value-
agnostic, so the fixture exercises grouping/dedup/drops without asserting real chemistry.
"""

from __future__ import annotations

import pandas as pd
import pytest

from studies.external_benchmarks.adapters.pham import (
    SourceNotReconstructedError,
    build_card,
    build_input_df,
    load_pham,
    sha256_bytes,
)
from studies.external_benchmarks.config import (
    PHAM_DISAMBIGUATION,
    PHAM_NEEDS_RECONSTRUCTION_SENTINEL,
    PhamDisambiguationDatasetConfig,
)


@pytest.fixture
def raw_pham_df() -> pd.DataFrame:
    """Table 9 ambiguous cases (real metadata) + one unambiguous name + a blank name.

    - ``suc`` -> {succinate, sucrose} (2 referents), ``H`` -> {proton, L-histidine} (2),
      ``tmp`` -> {TMP, thymidine-MP, thiamine-MP, cyclo-triphosphate} (4): the disambiguation cases.
    - ``glucose`` -> {D-glucose} (1 referent): NOT ambiguous, must be dropped (min_referents=2).
    - blank name: dropped (nothing to query).
    - a duplicate ``suc``/succinate candidate with a different InChIKey suffix but the SAME first-block
      must collapse to one referent (skeleton dedup), not inflate the count.
    """
    return pd.DataFrame(
        {
            "metabolite_name": ["suc", "suc", "suc", "H", "H", "tmp", "tmp", "tmp", "tmp", "glucose", ""],
            "source_database": [
                "MetaCyc",
                "Reactome",
                "SEED",
                "MetaCyc",
                "MetaCyc",
                "BiGG",
                "ChEBI",
                "KEGG",
                "MetaCyc",
                "ChEBI",
                "ChEBI",
            ],
            "candidate_id": [
                "SUC",
                "188980",
                "cpd00036",
                "PROTON",
                "HIS",
                "tmp",
                "10529",
                "C01081",
                "CPD-610",
                "4167",
                "0000",
            ],
            "metanetx_id": [
                "MNXM25",
                "MNXM167",
                "MNXM25",
                "MNXM1",
                "MNXM134",
                "MNXM87343",
                "MNXM257",
                "MNXM662",
                "MNXM88031",
                "MNXM41",
                "MNXMx",
            ],
            "compound_name": [
                "succinate",
                "sucrose",
                "succinate",
                "proton",
                "L-histidine",
                "TMP",
                "Thymidine monophosphate",
                "Thiamine monophosphate",
                "cyclo-triphosphoric acid",
                "D-glucose",
                "blank",
            ],
            # SYNTHETIC distinct 14-char first-blocks (documented); the third ``suc`` row shares
            # succinate's skeleton via a different suffix to exercise skeleton dedup.
            "inchikey": [
                "SUCCINATEBLOCK-AAAAAAAAAA-N",
                "SUCROSEBLOCKXX-BBBBBBBBBB-N",
                "SUCCINATEBLOCK-ZZZZZZZZZZ-M",
                "PROTONBLOCKXXX-CCCCCCCCCC-N",
                "HISTIDINEBLOCK-DDDDDDDDDD-N",
                "TMPBLOCKXXXXXX-EEEEEEEEEE-N",
                "THYMIDINEMPXXX-FFFFFFFFFF-N",
                "THIAMINEMPXXXX-GGGGGGGGGG-N",
                "CYCLOTRIPHOSXX-HHHHHHHHHH-N",
                "GLUCOSEBLOCKXX-IIIIIIIIII-N",
                "",
            ],
        }
    )


def test_input_df_keeps_only_ambiguous_names(raw_pham_df):
    df = build_input_df(raw_pham_df, PHAM_DISAMBIGUATION)
    names = list(df[PHAM_DISAMBIGUATION.name_column])
    # glucose (1 referent) and the blank name are dropped; suc/H/tmp remain, first-appearance order.
    assert names == ["suc", "H", "tmp"]


def test_referent_count_and_skeleton_dedup(raw_pham_df):
    df = build_input_df(raw_pham_df, PHAM_DISAMBIGUATION)
    counts = dict(zip(df[PHAM_DISAMBIGUATION.name_column], df[PHAM_DISAMBIGUATION.referent_count_column]))
    # two ``suc`` succinate rows share a first-block -> one referent; +sucrose -> 2 distinct referents.
    assert counts["suc"] == 2
    assert counts["H"] == 2
    assert counts["tmp"] == 4


def test_held_out_referent_gold_is_delimited_and_deduped(raw_pham_df):
    df = build_input_df(raw_pham_df, PHAM_DISAMBIGUATION)
    suc = df[df[PHAM_DISAMBIGUATION.name_column] == "suc"].iloc[0]
    # distinct-skeleton dedup keeps the FIRST full InChIKey per skeleton (2 referents, not 3).
    iks = suc[PHAM_DISAMBIGUATION.gold_referent_inchikey_column].split("|")
    assert iks == ["SUCCINATEBLOCK-AAAAAAAAAA-N", "SUCROSEBLOCKXX-BBBBBBBBBB-N"]
    # candidate CURIEs across DBs (coverage/traceability), bare ids prefixed by their database.
    assert suc[PHAM_DISAMBIGUATION.gold_referent_id_column] == "MetaCyc:SUC|Reactome:188980|SEED:cpd00036"
    assert suc[PHAM_DISAMBIGUATION.gold_metanetx_column] == "MNXM25|MNXM167"


def test_candidate_curie_keeps_existing_prefix(raw_pham_df):
    df = build_input_df(raw_pham_df, PHAM_DISAMBIGUATION)
    tmp = df[df[PHAM_DISAMBIGUATION.name_column] == "tmp"].iloc[0]
    ids = tmp[PHAM_DISAMBIGUATION.gold_referent_id_column].split("|")
    assert ids == ["BiGG:tmp", "ChEBI:10529", "KEGG:C01081", "MetaCyc:CPD-610"]


def test_card_reports_ambiguity_and_status(raw_pham_df):
    card = build_card(raw_pham_df, source_sha="deadbeef", config=PHAM_DISAMBIGUATION)
    assert card["n_ambiguous_names"] == 3
    assert card["input_type"] == "name"
    assert card["ambiguity_degree"]["max_referents"] == 4
    assert card["ambiguity_degree"]["mean_referents"] == pytest.approx((2 + 2 + 4) / 3)
    assert card["source_status"] == "needs-reconstruction"
    assert card["source_doi"] == PHAM_DISAMBIGUATION.source_doi
    assert card["referent_oracle_column"] == PHAM_DISAMBIGUATION.gold_referent_inchikey_column
    # per-database candidate coverage tallies real surveyed DBs (MetaCyc appears across suc/H/tmp).
    assert card["per_database_candidate_coverage"]["MetaCyc"] >= 1
    assert card["per_database_candidate_coverage"]["KEGG"] == 1


def test_load_from_dataframe_sha_is_deterministic(raw_pham_df):
    bundle = load_pham(raw_pham_df, PHAM_DISAMBIGUATION)
    expected = sha256_bytes(raw_pham_df.to_csv(index=False).encode("utf-8"))
    assert bundle.card["source_sha256"] == expected
    assert bundle.card["n_ambiguous_names"] == 3


def test_load_string_source_fails_loud_on_reconstruction_sentinel():
    # No downloadable SI exists: a placeholder source must fail loud before any scoring.
    with pytest.raises(SourceNotReconstructedError, match="needs-reconstruction"):
        load_pham(f"{PHAM_NEEDS_RECONSTRUCTION_SENTINEL}-v1", PHAM_DISAMBIGUATION)


def test_load_bytes_roundtrip(raw_pham_df):
    raw_bytes = raw_pham_df.to_csv(index=False).encode("utf-8")
    bundle = load_pham(raw_bytes, PHAM_DISAMBIGUATION)
    assert bundle.card["n_ambiguous_names"] == 3
    assert bundle.card["source_sha256"] == sha256_bytes(raw_bytes)


def test_missing_inchikey_column_fails_loud():
    df = pd.DataFrame({"metabolite_name": ["suc"], "candidate_id": ["MetaCyc:SUC"]})
    with pytest.raises(KeyError, match="InChIKey"):
        build_input_df(df, PHAM_DISAMBIGUATION)


def test_config_anti_trivial_guard_rejects_gold_equals_query():
    with pytest.raises(ValueError, match="anti-trivial"):
        PhamDisambiguationDatasetConfig(
            key="bad",
            arm="metabolite",
            entity_type="metabolite",
            name_column="metabolite_name",
            gold_referent_inchikey_column="metabolite_name",  # gold == query -> trivial 100%
            gold_referent_id_column="gold_ids",
            gold_metanetx_column="gold_mnx",
            referent_count_column="referent_count",
            target_vocabs=("CHEBI",),
            source_url="x",
            license="x",
        )
