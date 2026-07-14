"""MetaBench adapter — parse the QA grounding CSV into normalized long form + subgroups (offline)."""

from __future__ import annotations

import pandas as pd
import pytest

from studies.external_benchmarks.adapters import metabench
from studies.external_benchmarks.config import METABENCH

# A tiny stand-in for the 1,000-row Grounding CSV: one row per template (all five regimes),
# plus KEGG-DRUG (D-number) and bare-ChEBI answers.
_RAW = (
    b"question,answer\n"
    b"What is the KEGG ID of HMDB ID HMDB0010090?,C00626\n"
    b"What is the HMDB ID of KEGG ID C07251?,HMDB0014982\n"
    b"What is the KEGG ID of metabolite Glyceric acid?,C00258\n"
    b"What is the HMDB ID of metabolite Tramadol?,HMDB0014435\n"
    b"What is the ChEBI ID of metabolite Rolapitant hydrochloride?,90911\n"
    b"What is the KEGG ID of metabolite Some Drug?,D01211\n"
)


def _raw_bytes() -> bytes:
    return _RAW


def test_parse_grounding_normalizes_all_five_templates():
    long_df = metabench.parse_grounding(_raw_bytes(), METABENCH)
    assert len(long_df) == 6
    # id2id rows: source id + source namespace populated, name empty
    id_rows = long_df[long_df[METABENCH.pair_type_column] == "id2id"]
    assert len(id_rows) == 2
    hmdb_src = id_rows[id_rows[METABENCH.source_namespace_column] == "HMDB"].iloc[0]
    assert hmdb_src[METABENCH.source_id_column] == "HMDB0010090"
    assert hmdb_src[METABENCH.target_namespace_column] == "KEGG"
    assert hmdb_src[METABENCH.gold_target_column] == "C00626"
    assert hmdb_src[METABENCH.name_column] == ""
    # name2id rows: name populated, source id empty
    name_rows = long_df[long_df[METABENCH.pair_type_column] == "name2id"]
    assert len(name_rows) == 4
    chebi_row = name_rows[name_rows[METABENCH.target_namespace_column] == "CHEBI"].iloc[0]
    assert chebi_row[METABENCH.name_column] == "Rolapitant hydrochloride"
    assert chebi_row[METABENCH.gold_target_column] == "90911"
    assert chebi_row[METABENCH.source_id_column] == ""


def test_chebi_target_namespace_is_canonicalized():
    long_df = metabench.parse_grounding(_raw_bytes(), METABENCH)
    # question text says "ChEBI"; canonical namespace is "CHEBI" (matches the CURIE prefix)
    assert set(long_df[METABENCH.target_namespace_column]) == {"KEGG", "HMDB", "CHEBI"}


def test_kegg_drug_answer_preserved():
    long_df = metabench.parse_grounding(_raw_bytes(), METABENCH)
    drug = long_df[long_df[METABENCH.gold_target_column] == "D01211"]
    assert len(drug) == 1
    assert drug.iloc[0][METABENCH.target_namespace_column] == "KEGG"


def test_parse_is_fail_loud_on_unknown_template():
    bad = b"question,answer\nWhat is the color of metabolite Foo?,blue\n"
    with pytest.raises(metabench.MetaBenchParseError):
        metabench.parse_grounding(bad, METABENCH)


def test_parse_fail_loud_on_missing_columns():
    with pytest.raises(metabench.MetaBenchParseError):
        metabench.parse_grounding(b"q,a\nfoo,bar\n", METABENCH)


def test_build_subgroups_splits_by_regime_and_namespace():
    long_df = metabench.parse_grounding(_raw_bytes(), METABENCH)
    subgroups = metabench.build_subgroups(long_df, METABENCH)
    keys = {s.key for s in subgroups}
    assert keys == {
        "metabench-grounding-hmdb2kegg",
        "metabench-grounding-kegg2hmdb",
        "metabench-grounding-name2kegg",
        "metabench-grounding-name2hmdb",
        "metabench-grounding-name2chebi",
    }
    by_key = {s.key: s for s in subgroups}
    # ID->ID subgroup: provided-ID mode, source column named for the normalizer, gold held out
    hk = by_key["metabench-grounding-hmdb2kegg"]
    assert hk.pair_type == "id2id"
    assert hk.source_id_column == "hmdb"
    assert "hmdb" in hk.input_df.columns
    assert hk.input_df["hmdb"].iloc[0] == "HMDB0010090"
    assert METABENCH.gold_target_column in hk.input_df.columns  # held out, carried through
    assert METABENCH.target_namespace_column in hk.input_df.columns
    # name->ID subgroup: name-input mode, no provided source column
    nc = by_key["metabench-grounding-name2chebi"]
    assert nc.pair_type == "name2id"
    assert nc.source_id_column is None
    assert nc.vocab == "CHEBI"
    assert nc.input_df[METABENCH.name_column].iloc[0] == "Rolapitant hydrochloride"


def test_input_df_never_carries_source_id_as_a_provided_target():
    # anti-trivial: the gold TARGET column must not equal the provided source column in any subgroup
    long_df = metabench.parse_grounding(_raw_bytes(), METABENCH)
    for s in metabench.build_subgroups(long_df, METABENCH):
        if s.source_id_column is not None:
            assert s.source_id_column != METABENCH.gold_target_column
            assert s.source_namespace.upper() != s.target_namespace.upper()


def test_load_metabench_card_records_counts_sha_and_license():
    bundle = metabench.load_metabench(_raw_bytes(), METABENCH)
    card = bundle.card
    assert card["dataset"] == "metabench-grounding"
    assert card["n_rows"] == 6
    assert card["n_id2id"] == 2
    assert card["n_name2id"] == 4
    assert card["license"].startswith("Apache-2.0")
    assert len(card["source_sha256"]) == 64
    assert card["held_out_columns"] == [METABENCH.gold_target_column, METABENCH.target_namespace_column]
    assert card["n_baseline_competitors"] == len(METABENCH.baseline_competitors)


def test_load_metabench_accepts_dataframe_source():
    raw_df = pd.read_csv(pd.io.common.BytesIO(_raw_bytes()), dtype=str)
    bundle = metabench.load_metabench(raw_df, METABENCH)
    assert bundle.card["n_rows"] == 6
    assert len(bundle.subgroups) == 5
