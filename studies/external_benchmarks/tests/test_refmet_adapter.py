"""RefMet adapter transform (offline; in-memory CSV lines in, subsample + card out).

RefMet (Metabolomics Workbench) is LARGE (>200k analytes) and only ~17% InChIKey-annotated, so
the adapter STREAMS the bulk CSV, filters to the InChIKey-bearing population (the structure oracle
needs a held-out structure), reservoir-subsamples deterministically (seed pinned), and PERSISTS the
exact subsample beside the card. These tests exercise every transform on an in-memory line iterator
so the suite never touches the network.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from studies.external_benchmarks.adapters import refmet as rm
from studies.external_benchmarks.config import REFMET

# A tiny stand-in for the RefMet bulk CSV. Note: the real header ships with a leading space
# (" refmet_id,..."), quoted names may contain commas, and most rows carry NO inchi_key.
HEADER = (
    " refmet_id,refmet_name,super_class,main_class,sub_class,formula,exactmass,"
    "pubchem_cid,chebi_id,hmdb_id,lipidmaps_id,kegg_id,inchi_key"
)
ROWS = [
    # clean row, full crosswalk + InChIKey (structure-bearing)
    (
        "RM0000001,Cholesterol,Sterol Lipids,Sterols,Cholesterols,C27H46O,386.35,"
        '5997,"16113",HMDB0000067,LMST01010001,C00187,HVYWMOMLDIMFJA-DPAQBDIFSA-N'
    ),
    # quoted name WITH a comma; InChIKey present, sparse crosswalk (structure-bearing)
    (
        'RM0000002,"6H-Thieno[2,3-b]pyrrole-5-carboxylic acid",Alkaloids,Alkaloids,'
        'Other,C7H5NO2S,167.0,11622394,"",,,,SEPXFZLYPWFMSY-UHFFFAOYSA-N'
    ),
    # NO InChIKey -> filtered out of the structure-bearing subsample
    "RM0000003,Unknown analyte,,,,,,,,,,,",
    # InChIKey present (structure-bearing)
    (
        "RM0000004,Glucose,Carbohydrates,Monosaccharides,Hexoses,C6H12O6,180.06,"
        "5793,4167,HMDB0000122,,C00031,WQZGKKKJIJFFOK-GASJEMHNSA-N"
    ),
]


def lines():
    return iter([HEADER, *ROWS])


def test_records_filter_structure_bearing_by_default():
    recs = list(rm.refmet_records(lines(), require_structure=True))
    names = [r[REFMET.name_column] for r in recs]
    assert names == ["Cholesterol", "6H-Thieno[2,3-b]pyrrole-5-carboxylic acid", "Glucose"]
    # the no-InChIKey row ("Unknown analyte") is excluded
    assert "Unknown analyte" not in names


def test_records_can_retain_all_when_not_filtering():
    recs = list(rm.refmet_records(lines(), require_structure=False))
    assert len(recs) == 4  # all rows, including the structureless one


def test_record_columns_and_gold_verbatim():
    rec = next(rm.refmet_records(lines(), require_structure=True))
    assert rec[REFMET.name_column] == "Cholesterol"
    # gold InChIKey preserved verbatim (the structure oracle — identity is load-bearing)
    assert rec["gold_inchikey"] == "HVYWMOMLDIMFJA-DPAQBDIFSA-N"
    assert rec["gold_chebi"] == "16113"
    assert rec["gold_hmdb"] == "HMDB0000067"
    assert rec["gold_pubchem"] == "5997"
    assert rec["gold_kegg"] == "C00187"
    assert rec["gold_lipidmaps"] == "LMST01010001"


def test_quoted_name_with_comma_parsed_as_one_field():
    recs = list(rm.refmet_records(lines(), require_structure=True))
    assert recs[1][REFMET.name_column] == "6H-Thieno[2,3-b]pyrrole-5-carboxylic acid"


def test_missing_query_column_raises():
    bad = iter(["colA,colB", "1,2"])
    with pytest.raises(KeyError, match="refmet_name"):
        list(rm.refmet_records(bad, require_structure=True))


def test_subsample_deterministic_and_persisted_roundtrip(tmp_path):
    cfg = replace(REFMET, subsample_n=2, subsample_seed=42)
    b1 = rm.load_refmet(lines(), cfg)
    b2 = rm.load_refmet(lines(), cfg)
    # deterministic given seed + item order
    assert b1.input_df.equals(b2.input_df)
    assert b1.card["subsample_sha256"] == b2.card["subsample_sha256"]
    # persist -> reload reproduces the exact scored subsample (byte-identical, same SHA)
    path = rm.persist_subsample(b1, tmp_path)
    reloaded = rm.load_persisted_subsample(path)
    assert rm.sha256_bytes(rm.subsample_csv_bytes(reloaded)) == b1.card["subsample_sha256"]


def test_card_records_subsample_coverage_and_provenance():
    cfg = replace(REFMET, subsample_n=3, subsample_seed=42)
    bundle = rm.load_refmet(lines(), cfg)
    card = bundle.card
    assert card["dataset"] == "refmet"
    assert card["input_type"] == "name"
    assert card["subsample"] == {"n": 3, "seed": 42, "method": "reservoir"}
    assert card["require_gold_structure"] is True
    # only structure-bearing rows are eligible (3 of 4), so n_scanned == 3
    assert card["n_scanned"] == 3
    # every sampled row carries the oracle InChIKey by construction -> 100% INCHIKEY coverage
    assert card["coverage"]["INCHIKEY"]["fraction"] == pytest.approx(1.0)
    assert card["structure_oracle_column"] == REFMET.gold_inchikey_column
    assert card["source_doi"] == REFMET.source_doi
    assert card["source_url"] == REFMET.source_url


def test_input_df_has_name_and_all_coverage_columns():
    cfg = replace(REFMET, subsample_n=3, subsample_seed=42)
    df = rm.load_refmet(lines(), cfg).input_df
    for _, col in REFMET.gold_coverage_columns:
        assert col in df.columns
    assert REFMET.name_column in df.columns
    assert rm.HAS_STRUCTURE_COL in df.columns
    assert df[rm.HAS_STRUCTURE_COL].all()  # all sampled rows are structure-bearing


def test_fetch_is_isolated(monkeypatch):
    # load_refmet(url) must route through stream_source_lines (stubbed) — never the network.
    monkeypatch.setattr(rm, "stream_source_lines", lambda url, **kw: lines())
    cfg = replace(REFMET, subsample_n=2, subsample_seed=42)
    bundle = rm.load_refmet("https://example.invalid/refmet_download.php", cfg)
    assert bundle.card["n_scanned"] == 3
    assert len(bundle.input_df) == 2


def test_subsample_n_required():
    cfg = replace(REFMET, subsample_n=None)
    with pytest.raises(ValueError, match="subsample_n"):
        rm.load_refmet(lines(), cfg)


def test_load_refmet_url_charsetless_fetch_decodes_end_to_end(monkeypatch):
    """The live RefMet URL fetch (charset-less ``application/x-download``) must run clean.

    Regression for the run failure ``_csv.Error: iterator should return strings, not bytes``:
    ``load_refmet(url)`` routes through the REAL ``stream_source_lines`` against a server that
    declares no charset. The encoding fallback must yield ``str`` so the CSV parse + subsample
    complete without the bytes error.
    """
    import types

    class _CharsetlessResponse:
        def __init__(self, payload):
            self._payload = payload
            self.encoding = None  # no charset declared

        def raise_for_status(self):
            return None

        def iter_lines(self, decode_unicode=False):
            for line in self._payload:
                raw = line.encode("utf-8")
                yield raw.decode(self.encoding) if (decode_unicode and self.encoding) else raw

    payload = [HEADER, *ROWS]
    fake_requests = types.SimpleNamespace(get=lambda url, **kw: _CharsetlessResponse(payload))
    monkeypatch.setitem(__import__("sys").modules, "requests", fake_requests)

    cfg = replace(REFMET, subsample_n=2, subsample_seed=42)
    bundle = rm.load_refmet("https://www.metabolomicsworkbench.org/databases/refmet/refmet_download.php", cfg)
    assert bundle.card["n_scanned"] == 3  # three structure-bearing rows parsed, no bytes error
    assert len(bundle.input_df) == 2
