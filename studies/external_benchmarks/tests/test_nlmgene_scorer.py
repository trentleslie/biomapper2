"""NLM-Gene ambiguous-partition scorer (offline)."""

from __future__ import annotations

import pandas as pd
import pytest

from studies.external_benchmarks.config import NLMGENE
from studies.external_benchmarks.scorers.nlmgene_scorer import (
    UnscorableRunError,
    score_nlmgene_ambiguity,
)


def _row(mention, gold, chosen, equiv="{}"):
    return {
        "mention": mention,
        "gold_ncbigene": gold,
        "chosen_kg_id": chosen,
        "kg_equivalent_ids": equiv,
    }


def test_flag_rate_over_commit_and_membership():
    df = pd.DataFrame(
        [
            # abstained (no chosen_kg_id) -> flagged (correct behavior for an ambiguous form)
            _row("IL", "NCBIGene:3552|NCBIGene:3553", ""),
            # committed to a legitimate referent -> member, NOT a silent over-commit
            _row("chemokine receptor", "NCBIGene:12458|NCBIGene:12772", "NCBIGene:12458"),
            # committed to a WRONG gene (not in the referent set) -> silent over-commit (the danger)
            _row("IL", "NCBIGene:3552|NCBIGene:3553", "NCBIGene:9999"),
            # committed via an equivalent id that IS a referent -> member
            _row("H", "NCBIGene:3064|NCBIGene:3065", "HGNC:4851", equiv="{'NCBIGene': ['3064']}"),
        ]
    )
    r = score_nlmgene_ambiguity(df, NLMGENE)
    assert r["comparable_core"]["metric"] == "flag_rate"
    assert r["comparable_core"]["n_ambiguous"] == 4
    assert r["comparable_core"]["flagged"] == 1
    assert r["comparable_core"]["flag_rate"] == 0.25  # 1/4 abstained
    assert r["committed"] == 3
    assert r["silent_over_commit_rate"] == pytest.approx(1 / 4)  # one wrong-confident of 4
    assert r["member_when_committed"] == pytest.approx(2 / 3)  # 2 of 3 committed landed on a referent


def test_empty_partition_raises():
    with pytest.raises(UnscorableRunError):
        score_nlmgene_ambiguity(pd.DataFrame(columns=["mention", "gold_ncbigene", "chosen_kg_id"]), NLMGENE)
