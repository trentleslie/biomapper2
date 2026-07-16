"""LMSD adapter transform (offline; in-memory SDF lines in, subsample + card out).

LMSD (LIPID MAPS Structure Database) ships a bulk SDF (~50k curated records). The adapter STREAMS
the SDF, filters to the InChIKey-bearing population (the structure oracle needs a held-out
structure), reservoir-subsamples deterministically (seed pinned), and PERSISTS the exact subsample
beside the card. The query is a lipid NAME (shorthand/common/systematic); the LM_ID is held out
(contamination control — the KG recognizes the LIPIDMAPS namespace). These tests exercise every
transform on an in-memory SDF line iterator so the suite never touches the network.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from studies.external_benchmarks.adapters import lmsd as lm
from studies.external_benchmarks.config import LMSD


def _record(
    *,
    lm_id: str,
    name: str = "",
    systematic: str = "",
    abbreviation: str = "",
    inchikey: str = "",
    smiles: str = "",
    chebi: str = "",
    hmdb: str = "",
    pubchem: str = "",
    kegg: str = "",
    swisslipids: str = "",
) -> str:
    """One SDF record: a minimal molblock stub + the tag section + the ``$$$$`` delimiter."""
    lines = [
        "",
        "  Fixture molblock (ignored)",
        "",
        "  0  0  0  0  0  0  0  0  0  0999 V2000",
        "M  END",
    ]

    def _tag(tag: str, value: str) -> None:
        if value:
            lines.extend([f"> <{tag}>", value, ""])

    _tag("LM_ID", lm_id)
    _tag("NAME", name)
    _tag("SYSTEMATIC_NAME", systematic)
    _tag("ABBREVIATION", abbreviation)
    _tag("INCHI_KEY", inchikey)
    _tag("SMILES", smiles)
    _tag("PUBCHEM_CID", pubchem)
    _tag("CHEBI_ID", chebi)
    _tag("HMDB_ID", hmdb)
    _tag("KEGG_ID", kegg)
    _tag("SWISSLIPIDS_ID", swisslipids)
    lines.append("$$$$")
    return "\n".join(lines)


# A tiny stand-in for the LMSD SDF: an abbreviation-first record, a common-name-only record, a
# structureless record (filtered out), and a systematic-name-only record.
RECORDS = [
    _record(
        lm_id="LMFA01010001",
        name="Palmitic acid",
        systematic="hexadecanoic acid",
        abbreviation="FA 16:0",
        inchikey="IPCSVZSSVZVIGE-UHFFFAOYSA-N",
        smiles="CCCCCCCCCCCCCCCC(O)=O",
        chebi="15756",
        hmdb="HMDB0000220",
        pubchem="985",
        kegg="C00249",
        swisslipids="SLM:000000510",
    ),
    _record(
        lm_id="LMFA00000006",
        name="Lysine-containing siolipin",
        systematic="2-((2S)-6-amino-...hexanoyloxy)ethyl ...tetradecanoate",
        # no abbreviation -> falls back to common NAME
        inchikey="RAKAWZJMWJKWRH-QRMJXLNNSA-N",
        smiles="N([C@@]([H])(CCCCN)C(=O)OCCOC(=O)C(O)CCCCCCCCCCC(C)C)C(CC(O)CCCCCCCCCCC(C)C)=O",
        pubchem="178328009",
    ),
    _record(
        lm_id="LMFA99999999",
        name="Structureless lipid",
        abbreviation="FA 99:9",
        # NO InChIKey -> filtered out of the structure-bearing subsample
    ),
    _record(
        lm_id="LMGP01010001",
        systematic="1,2-dihexadecanoyl-sn-glycero-3-phosphocholine",
        # no abbreviation, no common name -> falls back to SYSTEMATIC_NAME
        inchikey="KILNVBDSWZSGLL-KXQOOQHDSA-N",
        smiles="[C@](COC(=O)CCCCCCCCCCCCCCC)(OC(=O)CCCCCCCCCCCCCCC)([H])COP([O-])(=O)OCC[N+](C)(C)C",
        chebi="72998",
    ),
]


def lines():
    return iter("\n".join(RECORDS).split("\n"))


def test_sdf_records_parses_tag_sections():
    recs = list(lm.sdf_records(lines()))
    assert len(recs) == 4
    assert recs[0]["LM_ID"] == "LMFA01010001"
    assert recs[0]["ABBREVIATION"] == "FA 16:0"
    assert recs[0]["INCHI_KEY"] == "IPCSVZSSVZVIGE-UHFFFAOYSA-N"
    # the molblock connection table is skipped — only tag fields survive
    assert "M  END" not in recs[0].values()


def test_records_filter_structure_bearing_by_default():
    recs = list(lm.lmsd_records(lines(), require_structure=True))
    names = [r[LMSD.name_column] for r in recs]
    # structureless "FA 99:9" is dropped; the other three are retained
    assert names == ["FA 16:0", "Lysine-containing siolipin", "1,2-dihexadecanoyl-sn-glycero-3-phosphocholine"]


def test_records_can_retain_all_when_not_filtering():
    recs = list(lm.lmsd_records(lines(), require_structure=False))
    assert len(recs) == 4  # all rows, including the structureless one


def test_query_preference_shorthand_then_common_then_systematic():
    recs = list(lm.lmsd_records(lines(), require_structure=True))
    # record 1 has an abbreviation -> shorthand chosen
    assert recs[0][LMSD.name_column] == "FA 16:0"
    assert recs[0][lm.QUERY_SOURCE_COL] == "abbreviation"
    # record 2 has no abbreviation -> common NAME chosen
    assert recs[1][LMSD.name_column] == "Lysine-containing siolipin"
    assert recs[1][lm.QUERY_SOURCE_COL] == "common_name"
    # record 4 has only a systematic name -> systematic chosen
    assert recs[2][lm.QUERY_SOURCE_COL] == "systematic_name"


def test_record_columns_and_gold_verbatim():
    rec = next(lm.lmsd_records(lines(), require_structure=True))
    assert rec[LMSD.name_column] == "FA 16:0"
    # gold InChIKey preserved verbatim (the structure oracle — identity is load-bearing)
    assert rec["gold_inchikey"] == "IPCSVZSSVZVIGE-UHFFFAOYSA-N"
    assert rec["gold_smiles"] == "CCCCCCCCCCCCCCCC(O)=O"
    assert rec["gold_chebi"] == "15756"
    assert rec["gold_hmdb"] == "HMDB0000220"
    assert rec["gold_pubchem"] == "985"
    assert rec["gold_kegg"] == "C00249"
    assert rec["gold_swisslipids"] == "SLM:000000510"
    # LM_ID carried as HELD-OUT provenance only (never a query, never the oracle)
    assert rec[lm.HELD_OUT_LM_ID_COL] == "LMFA01010001"


def test_lm_id_is_held_out_never_the_query():
    df = lm.build_input_df(list(lm.lmsd_records(lines(), require_structure=True)), LMSD)
    # no query value is ever an LM_ID (contamination control)
    assert not (df[LMSD.name_column] == df[lm.HELD_OUT_LM_ID_COL]).any()
    # the LM_IDs are all present in the held-out column
    assert set(df[lm.HELD_OUT_LM_ID_COL]) == {"LMFA01010001", "LMFA00000006", "LMGP01010001"}


def test_contamination_guard_raises_when_lm_id_leaks_as_query():
    # a hand-forged record whose name == its LM_ID must be refused by the guard
    leaked = [{LMSD.name_column: "LMFA01010001", lm.HELD_OUT_LM_ID_COL: "LMFA01010001", "gold_inchikey": "X"}]
    with pytest.raises(ValueError, match="contamination guard"):
        lm.build_input_df(leaked, LMSD)


def test_subsample_deterministic_and_persisted_roundtrip(tmp_path):
    cfg = replace(LMSD, subsample_n=2, subsample_seed=42)
    b1 = lm.load_lmsd(lines(), cfg)
    b2 = lm.load_lmsd(lines(), cfg)
    assert b1.input_df.equals(b2.input_df)
    assert b1.card["subsample_sha256"] == b2.card["subsample_sha256"]
    path = lm.persist_subsample(b1, tmp_path)
    reloaded = lm.load_persisted_subsample(path)
    assert lm.sha256_bytes(lm.subsample_csv_bytes(reloaded)) == b1.card["subsample_sha256"]


def test_card_records_subsample_coverage_name_mix_and_contamination():
    cfg = replace(LMSD, subsample_n=3, subsample_seed=42)
    card = lm.load_lmsd(lines(), cfg).card
    assert card["dataset"] == "lmsd"
    assert card["input_type"] == "name"
    assert card["subsample"] == {"n": 3, "seed": 42, "method": "reservoir"}
    assert card["require_gold_structure"] is True
    # only structure-bearing rows are eligible (3 of 4), so n_scanned == 3
    assert card["n_scanned"] == 3
    # every sampled row carries the oracle InChIKey by construction -> 100% INCHIKEY coverage
    assert card["coverage"]["INCHIKEY"]["fraction"] == pytest.approx(1.0)
    assert card["structure_oracle_column"] == LMSD.gold_inchikey_column
    # contamination control recorded on the card
    assert card["held_out_id_column"] == lm.HELD_OUT_LM_ID_COL
    # name-mix composition recorded (one query per source in this fixture)
    assert card["name_source_breakdown"] == {"abbreviation": 1, "common_name": 1, "systematic_name": 1}
    assert card["source_doi"] == LMSD.source_doi
    assert card["license"].startswith("LMSD")


def test_input_df_has_name_and_all_coverage_columns():
    cfg = replace(LMSD, subsample_n=3, subsample_seed=42)
    df = lm.load_lmsd(lines(), cfg).input_df
    for _, col in LMSD.gold_coverage_columns:
        assert col in df.columns
    assert LMSD.name_column in df.columns
    assert lm.QUERY_SOURCE_COL in df.columns
    assert lm.HELD_OUT_LM_ID_COL in df.columns
    assert lm.HAS_STRUCTURE_COL in df.columns
    assert df[lm.HAS_STRUCTURE_COL].all()  # all sampled rows are structure-bearing


def test_stream_is_isolated(monkeypatch):
    # load_lmsd(url) must route through stream_sdf_lines (stubbed) — never the network.
    monkeypatch.setattr(lm, "stream_sdf_lines", lambda url, **kw: lines())
    cfg = replace(LMSD, subsample_n=2, subsample_seed=42)
    bundle = lm.load_lmsd("https://www.lipidmaps.org/files/?file=LMSD&ext=sdf.zip", cfg)
    assert bundle.card["n_scanned"] == 3
    assert len(bundle.input_df) == 2


def test_subsample_n_required():
    cfg = replace(LMSD, subsample_n=None)
    with pytest.raises(ValueError, match="subsample_n"):
        lm.load_lmsd(lines(), cfg)


def test_sdf_record_without_trailing_delimiter_still_emitted():
    # an SDF that does not end with $$$$ must still yield its last record
    single = _record(lm_id="LMFA01010001", abbreviation="FA 16:0", inchikey="IPCSVZSSVZVIGE-UHFFFAOYSA-N")
    no_delim = "\n".join(single.split("\n")[:-1])  # drop the $$$$ line
    recs = list(lm.sdf_records(iter(no_delim.split("\n"))))
    assert len(recs) == 1
    assert recs[0]["ABBREVIATION"] == "FA 16:0"
