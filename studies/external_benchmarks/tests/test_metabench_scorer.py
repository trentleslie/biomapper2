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
