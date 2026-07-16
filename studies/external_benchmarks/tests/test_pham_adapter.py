"""Pham name-disambiguation adapter tests (offline).

Two layers, both network-free:
  1. The MetaNetX RECONSTRUCTION (parse chem_prop/chem_xref, group names -> distinct InChIKey
     first-blocks) driven on tiny in-memory chem_* fixtures written to tmp files — proves the real
     reconstruction logic without the 1.4 GB bulk files.
  2. The transform (raw candidate table -> input_df + card) driven on a hand-written Table 9-style
     fixture. The InChIKey values there are SYNTHETIC but distinct per compound (documented): the
     transform is structure-value-agnostic, so the fixture exercises grouping/dedup/drops/counts
     without asserting real chemistry.
"""

from __future__ import annotations

import pandas as pd
import pytest

from studies.external_benchmarks.adapters.pham import (
    MetaNetXFiles,
    SourceNotReconstructedError,
    build_card,
    build_input_df,
    build_referent_population,
    load_pham,
    normalize_name,
    parse_chem_prop,
    population_to_raw_table,
    reconstruct_from_metanetx,
    sha256_bytes,
)
from studies.external_benchmarks.config import (
    PHAM_DISAMBIGUATION,
    PHAM_NEEDS_RECONSTRUCTION_SENTINEL,
    PhamDisambiguationDatasetConfig,
)

# ==================================================================================================
# Layer 1 — MetaNetX reconstruction on tiny chem_prop/chem_xref fixtures.
# ==================================================================================================

_CHEM_PROP = """\
### MetaNetX/MNXref reconciliation ###
#VERSION:	4.5
#DATE:	2025/08/13
#ID	name	reference	formula	charge	mass	InChI	InChIKey	SMILES
MNXM1	succinate	chebi:30031	C4H4O4	-2	116.0	InChI=x	SUCCINATEBLOCK-AAAAAAAAAA-N	C
MNXM2	sucrose	chebi:17992	C12H22O11	0	342.0	InChI=y	SUCROSEBLOCKXX-BBBBBBBBBB-N	C
MNXM3	D-glucose	chebi:4167	C6H12O6	0	180.0	InChI=z	GLUCOSEBLOCKXX-IIIIIIIIII-N	C
MNXM4	succinate-variant	chebi:99	C4H4O4	-1	117.0	InChI=w	SUCCINATEBLOCK-ZZZZZZZZZZ-M	C
MNXM9	no-structure	seed:0	C	0	0.0
"""

_CHEM_XREF = """\
### MetaNetX/MNXref reconciliation ###
#RESOURCE:	MetaNetX/MNXref
#source	ID	description
chebi:30031	MNXM1	suc||succinate
kegg.compound:C00089	MNXM2	SUC||sucrose
seed:cpd00027	MNXM3	glucose||D-glucose
metacyc.compound:SUCC	MNXM4	suc||succinic acid
chebi:1	MNXM9	mystery-name
chebi:2	MNXM1	secondary/obsolete/fantasy identifier
"""


@pytest.fixture
def metanetx_files(tmp_path) -> MetaNetXFiles:
    prop = tmp_path / "chem_prop.tsv"
    xref = tmp_path / "chem_xref.tsv"
    prop.write_text(_CHEM_PROP)
    xref.write_text(_CHEM_XREF)
    return MetaNetXFiles(
        chem_prop_path=str(prop),
        chem_xref_path=str(xref),
        release="4.5",
        version="4.5",
        version_date="2025/08/13",
        chem_prop_sha256="deadprop",
        chem_xref_sha256="deadxref",
        chem_prop_md5="m1",
        chem_xref_md5="m2",
    )


def test_normalize_name_casefolds_and_collapses_whitespace():
    assert normalize_name("  TMP ") == "tmp"
    assert normalize_name("L-Alanine") == "l-alanine"
    assert normalize_name("SUC") == normalize_name("suc")
    assert normalize_name("") == ""


def test_parse_chem_prop_keeps_only_inchikey_rows(metanetx_files):
    prop = parse_chem_prop(metanetx_files.chem_prop_path)
    # MNXM9 ships no InChIKey -> excluded (cannot anchor a referent); the four structured ids remain.
    assert set(prop) == {"MNXM1", "MNXM2", "MNXM3", "MNXM4"}
    assert prop["MNXM1"] == ("SUCCINATEBLOCK-AAAAAAAAAA-N", "succinate")


def test_build_referent_population_groups_names_to_distinct_blocks(metanetx_files):
    prop = parse_chem_prop(metanetx_files.chem_prop_path)
    pop = build_referent_population(prop, metanetx_files.chem_xref_path, PHAM_DISAMBIGUATION)
    # "suc"/"SUC" collapse (casefold): succinate (MNXM1) + sucrose (MNXM2) + succinic-acid (MNXM4).
    # MNXM4 shares succinate's FIRST-BLOCK (charge variant) -> collapses to succinate's referent, so
    # "suc" has TWO distinct structural referents (succinate skeleton, sucrose skeleton) -> ambiguous.
    # "suc"/"SUC" (chebi:MNXM1, kegg:MNXM2, metacyc:MNXM4) collapse; "succinic acid" is MNXM4's other
    # synonym (1 referent). MNXM4 shares MNXM1's first-block (charge variant) -> collapses in "suc".
    assert set(pop.groups) == {"suc", "succinate", "sucrose", "glucose", "d-glucose", "succinic acid"}
    assert len(pop.groups["suc"].block_ik) == 2  # succinate + sucrose skeletons (MNXM4 variant collapsed)
    assert len(pop.groups["succinate"].block_ik) == 1
    assert len(pop.groups["succinic acid"].block_ik) == 1
    # "mystery-name" mapped only to MNXM9 (no structure) -> not a group at all.
    assert "mystery-name" not in pop.groups
    assert pop.n_names_total == 6
    assert pop.n_ambiguous == 1  # only "suc" has >= 2 distinct referents
    assert pop.ambiguous_names(2) == ["suc"]


def test_reconstruct_from_metanetx_builds_raw_table(metanetx_files):
    raw = reconstruct_from_metanetx(metanetx_files, PHAM_DISAMBIGUATION)
    # One row per (name, distinct referent). "suc" contributes 2 rows; each single-referent name 1.
    suc_rows = raw[raw["metabolite_name"].str.casefold() == "suc"]
    assert len(suc_rows) == 2
    assert set(suc_rows["metanetx_id"]) == {"MNXM1", "MNXM2"}  # variant MNXM4 collapsed into MNXM1 block
    assert set(suc_rows["inchikey"]) == {"SUCCINATEBLOCK-AAAAAAAAAA-N", "SUCROSEBLOCKXX-BBBBBBBBBB-N"}


def test_load_pham_from_metanetx_files_pins_provenance(metanetx_files):
    bundle = load_pham(metanetx_files, PHAM_DISAMBIGUATION)
    card = bundle.card
    assert card["source_status"] == "resolved"
    assert card["metanetx"]["release"] == "4.5"
    assert card["metanetx"]["chem_prop"]["sha256"] == "deadprop"
    assert card["metanetx"]["chem_xref"]["md5"] == "m2"
    # Combined-SHA pin is deterministic over the two file SHAs (not a giant reconstructed CSV).
    assert card["source_sha256"] == sha256_bytes(b"deadprop:deadxref")
    # Full population = 6 names (incl. "succinic acid"); ambiguous subset = 1 ("suc").
    assert card["n_names"] == 6
    assert card["n_ambiguous"] == 1
    names = list(bundle.input_df[PHAM_DISAMBIGUATION.name_column])
    assert "suc" in [n.casefold() for n in names]


# ==================================================================================================
# Layer 2 — transform on a Table 9-style raw fixture (full population retained, ambiguous broken out).
# ==================================================================================================


@pytest.fixture
def raw_pham_df() -> pd.DataFrame:
    """Table 9 ambiguous cases + one unambiguous name (glucose) + a blank name.

    - ``suc`` -> {succinate, sucrose} (2 referents), ``H`` -> {proton, L-histidine} (2),
      ``tmp`` -> {TMP, thymidine-MP, thiamine-MP, cyclo-triphosphate} (4): the disambiguation cases.
    - ``glucose`` -> {D-glucose} (1 referent): NOT ambiguous but RETAINED in the full population.
    - blank name: dropped (nothing to query).
    - a duplicate ``suc``/succinate candidate with a different InChIKey suffix but the SAME first-block
      must collapse to one referent (skeleton dedup), not inflate the count.
    """
    return pd.DataFrame(
        {
            "metabolite_name": ["suc", "suc", "suc", "H", "H", "tmp", "tmp", "tmp", "tmp", "glucose", ""],
            "source_database": [
                "MetaCyc", "Reactome", "SEED", "MetaCyc", "MetaCyc", "BiGG", "ChEBI", "KEGG",
                "MetaCyc", "ChEBI", "ChEBI",
            ],
            "candidate_id": [
                "SUC", "188980", "cpd00036", "PROTON", "HIS", "tmp", "10529", "C01081", "CPD-610",
                "4167", "0000",
            ],
            "metanetx_id": [
                "MNXM25", "MNXM167", "MNXM25", "MNXM1", "MNXM134", "MNXM87343", "MNXM257", "MNXM662",
                "MNXM88031", "MNXM41", "MNXMx",
            ],
            "compound_name": [
                "succinate", "sucrose", "succinate", "proton", "L-histidine", "TMP",
                "Thymidine monophosphate", "Thiamine monophosphate", "cyclo-triphosphoric acid",
                "D-glucose", "blank",
            ],
            "inchikey": [
                "SUCCINATEBLOCK-AAAAAAAAAA-N", "SUCROSEBLOCKXX-BBBBBBBBBB-N", "SUCCINATEBLOCK-ZZZZZZZZZZ-M",
                "PROTONBLOCKXXX-CCCCCCCCCC-N", "HISTIDINEBLOCK-DDDDDDDDDD-N", "TMPBLOCKXXXXXX-EEEEEEEEEE-N",
                "THYMIDINEMPXXX-FFFFFFFFFF-N", "THIAMINEMPXXXX-GGGGGGGGGG-N", "CYCLOTRIPHOSXX-HHHHHHHHHH-N",
                "GLUCOSEBLOCKXX-IIIIIIIIII-N", "",
            ],
        }
    )


def test_input_df_keeps_full_population_drops_blank(raw_pham_df):
    df = build_input_df(raw_pham_df, PHAM_DISAMBIGUATION)
    names = list(df[PHAM_DISAMBIGUATION.name_column])
    # The blank name is dropped; the unambiguous glucose is RETAINED (full population, not ambiguous-only).
    assert names == ["suc", "H", "tmp", "glucose"]


def test_referent_count_and_skeleton_dedup(raw_pham_df):
    df = build_input_df(raw_pham_df, PHAM_DISAMBIGUATION)
    counts = dict(zip(df[PHAM_DISAMBIGUATION.name_column], df[PHAM_DISAMBIGUATION.referent_count_column]))
    # two ``suc`` succinate rows share a first-block -> one referent; +sucrose -> 2 distinct referents.
    assert counts["suc"] == 2
    assert counts["H"] == 2
    assert counts["tmp"] == 4
    assert counts["glucose"] == 1  # retained, single referent


def test_held_out_referent_gold_is_delimited_and_deduped(raw_pham_df):
    df = build_input_df(raw_pham_df, PHAM_DISAMBIGUATION)
    suc = df[df[PHAM_DISAMBIGUATION.name_column] == "suc"].iloc[0]
    iks = suc[PHAM_DISAMBIGUATION.gold_referent_inchikey_column].split("|")
    assert iks == ["SUCCINATEBLOCK-AAAAAAAAAA-N", "SUCROSEBLOCKXX-BBBBBBBBBB-N"]
    assert suc[PHAM_DISAMBIGUATION.gold_referent_id_column] == "MetaCyc:SUC|Reactome:188980|SEED:cpd00036"
    assert suc[PHAM_DISAMBIGUATION.gold_metanetx_column] == "MNXM25|MNXM167"


def test_candidate_curie_keeps_existing_prefix(raw_pham_df):
    df = build_input_df(raw_pham_df, PHAM_DISAMBIGUATION)
    tmp = df[df[PHAM_DISAMBIGUATION.name_column] == "tmp"].iloc[0]
    ids = tmp[PHAM_DISAMBIGUATION.gold_referent_id_column].split("|")
    assert ids == ["BiGG:tmp", "ChEBI:10529", "KEGG:C01081", "MetaCyc:CPD-610"]


def test_card_reports_full_and_ambiguous_sizes(raw_pham_df):
    card = build_card(raw_pham_df, source_sha="deadbeef", config=PHAM_DISAMBIGUATION)
    assert card["n_names"] == 4  # suc, H, tmp, glucose (full population)
    assert card["n_ambiguous"] == 3  # suc, H, tmp (>= 2 referents); glucose excluded
    assert card["input_type"] == "name"
    assert card["ambiguity_degree"]["max_referents"] == 4
    assert card["ambiguity_degree"]["mean_referents"] == pytest.approx((2 + 2 + 4 + 1) / 4)
    assert card["ambiguity_degree"]["mean_ambiguous_referents"] == pytest.approx((2 + 2 + 4) / 3)
    assert card["source_status"] == "needs-reconstruction"  # default (no MetaNetX files supplied)
    assert card["source_doi"] == PHAM_DISAMBIGUATION.source_doi
    assert card["referent_oracle_column"] == PHAM_DISAMBIGUATION.gold_referent_inchikey_column
    assert card["per_source_candidate_coverage"]["MetaCyc"] >= 1
    assert card["per_source_candidate_coverage"]["KEGG"] == 1


def test_load_from_dataframe_sha_is_deterministic(raw_pham_df):
    bundle = load_pham(raw_pham_df, PHAM_DISAMBIGUATION)
    expected = sha256_bytes(raw_pham_df.to_csv(index=False).encode("utf-8"))
    assert bundle.card["source_sha256"] == expected
    assert bundle.card["n_names"] == 4


def test_load_string_source_fails_loud_on_reconstruction_sentinel():
    # No downloadable SI exists: a placeholder source must fail loud before any scoring.
    with pytest.raises(SourceNotReconstructedError, match="needs-reconstruction"):
        load_pham(f"{PHAM_NEEDS_RECONSTRUCTION_SENTINEL}-v1", PHAM_DISAMBIGUATION)


def test_load_bytes_roundtrip(raw_pham_df):
    raw_bytes = raw_pham_df.to_csv(index=False).encode("utf-8")
    bundle = load_pham(raw_bytes, PHAM_DISAMBIGUATION)
    assert bundle.card["n_names"] == 4
    assert bundle.card["source_sha256"] == sha256_bytes(raw_bytes)


def test_missing_inchikey_column_fails_loud():
    df = pd.DataFrame({"metabolite_name": ["suc"], "candidate_id": ["MetaCyc:SUC"]})
    with pytest.raises(KeyError, match="InChIKey"):
        build_input_df(df, PHAM_DISAMBIGUATION)


def test_population_to_raw_table_restricts_to_named_subset(metanetx_files):
    prop = parse_chem_prop(metanetx_files.chem_prop_path)
    pop = build_referent_population(prop, metanetx_files.chem_xref_path, PHAM_DISAMBIGUATION)
    raw = population_to_raw_table(pop, PHAM_DISAMBIGUATION, names=["suc"])
    assert set(raw["metabolite_name"].str.casefold()) == {"suc"}
    assert len(raw) == 2  # only the 2 referents of "suc"


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
