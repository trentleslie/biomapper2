"""MetaBench scorer — one uniform accuracy, bare-gold prefixing, anti-trivial guard (offline)."""

from __future__ import annotations

import pandas as pd
import pytest

from studies.external_benchmarks.config import METABENCH
from studies.external_benchmarks.scorers.metabench_scorer import (
    MetaBenchNotHeldOutError,
    assert_metabench_held_out,
    score_metabench,
)


def _mapped_df() -> pd.DataFrame:
    """Concatenated mapper output across regimes. Bare gold targets (as MetaBench ships them).

    Rows:
      0 id2id HMDB->KEGG: prediction reaches gold KEGG   -> correct
      1 id2id KEGG->HMDB: prediction wrong               -> predicted-but-incorrect
      2 name2id ->KEGG:   annotation reaches gold KEGG   -> correct
      3 name2id ->CHEBI:  bare ChEBI gold, prediction reaches it -> correct
      4 name2id ->HMDB:   no prediction                 -> no prediction
    """
    return pd.DataFrame(
        {
            METABENCH.name_column: ["", "", "Glyceric acid", "Rolapitant hydrochloride", "Mystery"],
            METABENCH.source_id_column: ["HMDB0010090", "C07251", "", "", ""],
            METABENCH.source_namespace_column: ["HMDB", "KEGG", "", "", ""],
            METABENCH.pair_type_column: ["id2id", "id2id", "name2id", "name2id", "name2id"],
            # BioMapper's resolved node + equivalence expansion (the prediction)
            "chosen_kg_id": ["CHEBI:17234", "CHEBI:00001", "CHEBI:17015", "CHEBI:90911", None],
            "kg_equivalent_ids": [
                "{'KEGG': ['C00626']}",  # reaches gold KEGG -> correct
                "{'HMDB': ['HMDB9999999']}",  # wrong HMDB -> incorrect
                "{'KEGG': ['C00258']}",  # reaches gold KEGG -> correct
                "{}",  # chosen_kg_id CHEBI:90911 already equals the (prefixed) bare gold -> correct
                "{}",  # no expansion, no useful chosen -> no prediction toward gold
            ],
            # HELD OUT: bare target ids + per-row target namespace
            METABENCH.gold_target_column: ["C00626", "HMDB0014982", "C00258", "90911", "HMDB0000001"],
            METABENCH.target_namespace_column: ["KEGG", "HMDB", "KEGG", "CHEBI", "HMDB"],
        }
    )


def test_one_accuracy_over_all_pairs_bare_gold_prefixed():
    result = score_metabench(_mapped_df(), METABENCH)
    core = result["comparable_core"]
    # rows 0, 2, 3 correct; row 1 wrong; row 4 has a gold but no reaching prediction
    assert core["correct"] == 3
    assert core["scored_denominator"] == 5  # every row carries a held-out gold
    assert core["top1_accuracy"] == pytest.approx(3 / 5)
    assert result["mode"] == "metabench_grounding"


def test_bare_chebi_gold_matches_prefixed_prediction():
    # row 3: bare gold "90911" (target ns CHEBI) must be prefixed to CHEBI:90911 to match chosen_kg_id
    result = score_metabench(_mapped_df(), METABENCH)
    row3 = result["per_row"][3]
    assert row3["correct"] is True
    assert "CHEBI:90911" in row3["gold"]


def test_per_namespace_breakdown_retained_but_single_headline():
    result = score_metabench(_mapped_df(), METABENCH)
    pn = result["per_namespace"]
    assert pn["KEGG"]["scored"] == 2 and pn["KEGG"]["correct"] == 2
    assert pn["CHEBI"]["scored"] == 1 and pn["CHEBI"]["correct"] == 1
    assert pn["HMDB"]["scored"] == 2 and pn["HMDB"]["correct"] == 0
    # headline is a single number, not per-namespace
    assert isinstance(result["comparable_core"]["top1_accuracy"], float)


def test_coverage_and_precision_recall():
    result = score_metabench(_mapped_df(), METABENCH)
    cov = result["coverage"]
    assert cov["n_predicted"] == 4  # rows 0-3 predicted; row 4 did not
    stats = result["curie_stats"]
    assert stats["precision"] == pytest.approx(3 / 4)  # correct / (predicted AND gold)
    assert stats["recall"] == pytest.approx(3 / 5)  # correct / scored


def test_anti_trivial_guard_rejects_same_namespace_roundtrip():
    df = _mapped_df()
    df.loc[0, METABENCH.target_namespace_column] = "HMDB"  # HMDB source -> HMDB target (round-trip)
    with pytest.raises(MetaBenchNotHeldOutError):
        assert_metabench_held_out(df, METABENCH)


def test_fail_loud_when_held_out_column_missing():
    df = _mapped_df().drop(columns=[METABENCH.gold_target_column])
    with pytest.raises(MetaBenchNotHeldOutError):
        score_metabench(df, METABENCH)


def test_top1_none_when_no_scorable_gold():
    df = _mapped_df()
    df[METABENCH.gold_target_column] = ""  # no gold anywhere -> unscorable
    result = score_metabench(df, METABENCH)
    assert result["comparable_core"]["top1_accuracy"] is None
    assert result["comparable_core"]["scored_denominator"] == 0


def _kegg_prefix_variant_df() -> pd.DataFrame:
    """Every row: a KEGG-target gold that must match a differently-prefixed KEGG prediction.

    The live run's KG/equivalence expansion emits the Biolink ``KEGG.COMPOUND`` prefix while the
    MetaBench gold ships a bare ``C``-number under target namespace ``KEGG``. Rows exercise every
    variant that must be treated as the SAME entity:
      0 predicted ``KEGG.COMPOUND:C00626`` vs bare gold ``C00626``     -> correct
      1 predicted ``kegg.compound:C00093`` (lowercased) vs gold        -> correct (case-insensitive)
      2 gold already prefixed ``KEGG:C00025`` vs predicted KEGG.COMPOUND -> correct
      3 predicted ``KEGG.COMPOUND:C99999`` vs gold C00157              -> incorrect (real miss)
    """
    return pd.DataFrame(
        {
            METABENCH.name_column: ["", "", "", ""],
            METABENCH.source_id_column: ["HMDB0000001", "HMDB0000002", "HMDB0000003", "HMDB0000004"],
            METABENCH.source_namespace_column: ["HMDB", "HMDB", "HMDB", "HMDB"],
            METABENCH.pair_type_column: ["id2id", "id2id", "id2id", "id2id"],
            "chosen_kg_id": [
                "PUBCHEM.COMPOUND:1",
                "PUBCHEM.COMPOUND:2",
                "PUBCHEM.COMPOUND:3",
                "PUBCHEM.COMPOUND:4",
            ],
            "kg_equivalent_ids": [
                "{'KEGG.COMPOUND': ['C00626']}",  # database-section prefix vs bare gold
                "{'kegg.compound': ['C00093']}",  # lowercased database-section prefix
                "{'KEGG.COMPOUND': ['C00025']}",  # gold itself is prefixed KEGG:
                "{'KEGG.COMPOUND': ['C99999']}",  # genuinely different id -> miss
            ],
            METABENCH.gold_target_column: ["C00626", "C00093", "KEGG:C00025", "C00157"],
            METABENCH.target_namespace_column: ["KEGG", "KEGG", "KEGG", "KEGG"],
        }
    )


def test_kegg_compound_prefix_matches_bare_and_prefixed_gold():
    """KEGG.COMPOUND:Cxxxx (prediction) must match bare/prefixed KEGG gold — the 24.3->54.5 fix."""
    result = score_metabench(_kegg_prefix_variant_df(), METABENCH)
    core = result["comparable_core"]
    # rows 0,1,2 match despite prefix/case differences; row 3 is a real miss
    assert core["correct"] == 3
    assert core["scored_denominator"] == 4
    assert result["per_namespace"]["KEGG"]["correct"] == 3
    assert result["per_row"][0]["correct"] is True
    assert result["per_row"][3]["correct"] is False
