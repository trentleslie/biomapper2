from __future__ import annotations

from dataclasses import replace

import pytest

from studies.external_benchmarks.adapters import swisslipids as sl
from studies.external_benchmarks.config import SWISSLIPIDS

HEADER = "\t".join(
    ["Lipid ID", "Name", "Abbreviation*", "InChI key (pH7.3)", "SMILES (pH7.3)", "HMDB", "PubChem CID"]
)


def _row(*, sl_id, name="", abbrev="", inchikey="", smiles="", hmdb="", pubchem=""):
    return "\t".join([sl_id, name, abbrev, inchikey, smiles, hmdb, pubchem])


ROWS = [
    _row(
        sl_id="SLM:000000510",
        name="phosphatidylcholine (34:1)",
        abbrev="PC(34:1)",
        inchikey="KILNVBDSWZSGLL-KXQOOQHDSA-N",
        smiles="[C@](COC(=O)CCC)(OC(=O)CCC)([H])COP([O-])(=O)OCC[N+](C)(C)C",
        hmdb="HMDB0007972",
        pubchem="452110",
    ),
    _row(  # abbreviation only -> abbreviation query source
        sl_id="SLM:000000511",
        abbrev="PE(36:2)",
        inchikey="AAAAAAAAAAAAAA-BBBBBBBBBB-N",
        pubchem="9547069",
    ),
    _row(  # NO pubchem -> dropped when require_pubchem
        sl_id="SLM:000000512",
        name="mystery lipid",
        inchikey="CCCCCCCCCCCCCC-DDDDDDDDDD-N",
    ),
]


def lines():
    return iter("\n".join([HEADER, *ROWS]).split("\n"))


def test_swisslipids_config_is_accuracy_role_and_not_kraken_ingest():
    assert SWISSLIPIDS.role == "accuracy"
    assert SWISSLIPIDS.key == "swisslipids"


def test_tsv_records_parses_headered_rows():
    recs = list(sl.tsv_records(lines()))
    assert len(recs) == 3
    assert recs[0]["Lipid ID"] == "SLM:000000510"
    assert recs[0]["PubChem CID"] == "452110"


def test_records_prefer_name_then_abbreviation():
    recs = list(sl.swisslipids_records(lines(), require_pubchem=True))
    assert recs[0][SWISSLIPIDS.name_column] == "phosphatidylcholine (34:1)"
    assert recs[0][sl.QUERY_SOURCE_COL] == "name"
    assert recs[1][SWISSLIPIDS.name_column] == "PE(36:2)"
    assert recs[1][sl.QUERY_SOURCE_COL] == "abbreviation"


def test_records_require_pubchem_drops_rows_without_gold_source():
    recs = list(sl.swisslipids_records(lines(), require_pubchem=True))
    ids = [r[sl.HELD_OUT_PUBCHEM_COL] for r in recs]
    assert "" not in ids  # the pubchem-less row is dropped
    assert len(recs) == 2


def test_held_out_pubchem_and_own_inchikey_carried():
    rec = next(sl.swisslipids_records(lines(), require_pubchem=True))
    assert rec[sl.HELD_OUT_PUBCHEM_COL] == "452110"
    assert rec[sl.SL_OWN_INCHIKEY_COL] == "KILNVBDSWZSGLL-KXQOOQHDSA-N"
    assert rec["gold_smiles"] == ROWS[0].split("\t")[4]


def test_build_input_df_has_expected_columns():
    df = sl.build_input_df(list(sl.swisslipids_records(lines(), require_pubchem=True)), SWISSLIPIDS)
    assert SWISSLIPIDS.name_column in df.columns
    assert sl.HELD_OUT_PUBCHEM_COL in df.columns
    assert sl.SL_OWN_INCHIKEY_COL in df.columns
    assert sl.HAS_PUBCHEM_COL in df.columns
    assert df[sl.HAS_PUBCHEM_COL].all()


def test_subsample_deterministic_and_persisted_roundtrip(tmp_path):
    cfg = replace(SWISSLIPIDS, subsample_n=2, subsample_seed=42)
    b1 = sl.load_swisslipids(lines(), cfg)
    b2 = sl.load_swisslipids(lines(), cfg)
    assert b1.input_df.equals(b2.input_df)
    assert b1.card["subsample_sha256"] == b2.card["subsample_sha256"]
    path = sl.persist_subsample(b1, tmp_path)
    reloaded = sl.load_persisted_subsample(path)
    assert sl.sha256_bytes(sl.subsample_csv_bytes(reloaded)) == b1.card["subsample_sha256"]


def test_card_records_role_gold_source_and_name_mix():
    cfg = replace(SWISSLIPIDS, subsample_n=2, subsample_seed=42)
    card = sl.load_swisslipids(lines(), cfg).card
    assert card["dataset"] == "swisslipids"
    assert card["role"] == "accuracy"
    assert card["gold_structure_source"] == "PubChem"  # resolved from held-out PubChem CID (external)
    assert card["gold_is_kraken_ingest_source"] is False
    assert set(card["name_source_breakdown"]) <= {"name", "abbreviation"}


def test_stream_is_isolated(monkeypatch):
    monkeypatch.setattr(sl, "stream_tsv_lines", lambda url, **kw: lines())
    cfg = replace(SWISSLIPIDS, subsample_n=2, subsample_seed=42)
    bundle = sl.load_swisslipids("https://www.swisslipids.org/api/file.php?cast=tsv&file=lipids", cfg)
    assert len(bundle.input_df) == 2


def test_subsample_n_required():
    cfg = replace(SWISSLIPIDS, subsample_n=None)
    with pytest.raises(ValueError, match="subsample_n"):
        sl.load_swisslipids(lines(), cfg)
