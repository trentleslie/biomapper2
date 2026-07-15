"""Pham name-disambiguation scorer (offline; mapped_df + FakeOracle in, metrics out).

Only BioMapper's PREDICTION (``chosen_kg_id``) is resolved through the (fake) oracle; the referent
gold set is read from the held-out column. Structure blocks are synthetic + distinct (documented) —
the scorer is structure-value-agnostic, it only tests membership/precision/collapse logic.
"""

from __future__ import annotations

import pandas as pd
import pytest

from studies.external_benchmarks.config import PHAM_DISAMBIGUATION
from studies.external_benchmarks.scorers.pham_scorer import UnscorableRunError, score_pham_disambiguation
from studies.external_benchmarks.tests.conftest import FakeOracle

C = PHAM_DISAMBIGUATION


def _mapped_df() -> pd.DataFrame:
    """A post-run mapped frame: chosen_kg_id + the held-out referent gold columns (rides along)."""
    return pd.DataFrame(
        {
            C.name_column: ["suc", "H", "tmp", "PPP"],
            C.gold_referent_inchikey_column: [
                "SUCCINATEBLOCK-AAAAAAAAAA-N|SUCROSEBLOCKXX-BBBBBBBBBB-N",
                "PROTONBLOCKXXX-CCCCCCCCCC-N|HISTIDINEBLOCK-DDDDDDDDDD-N",
                "TMPBLOCKXXXXXX-EEEEEEEEEE-N|THYMIDINEMPXXX-FFFFFFFFFF-N|THIAMINEMPXXXX-GGGGGGGGGG-N",
                "TRIPHOSPHATEXX-JJJJJJJJJJ-N|PHENYLPIPERXX-KKKKKKKKKK-N",
            ],
            C.gold_referent_id_column: [
                "MetaCyc:SUC|Reactome:188980",
                "MetaCyc:PROTON|MetaCyc:HIS",
                "BiGG:tmp|ChEBI:10529|KEGG:C01081",
                "Reactome:1475054|MetaCyc:X",
            ],
            C.referent_count_column: [2, 2, 3, 2],
            # BioMapper's Top-1 choice per name (empty for PPP = no prediction / a miss).
            "chosen_kg_id": ["CHEBI:30031", "CHEBI:15378", "CHEBI:9999", ""],
        }
    )


def _oracle() -> FakeOracle:
    # chosen node -> resolved InChIKey first-block. suc/H land ON a legitimate referent; tmp resolves
    # to an OFF-TARGET block (predicted but not a member -> hallucination-guard case).
    return FakeOracle(
        kg_blocks={
            "CHEBI:30031": "SUCCINATEBLOCK",  # member of suc's referent set
            "CHEBI:15378": "PROTONBLOCKXXX",  # member of H's referent set
            "CHEBI:9999": "WRONGBLOCKXXXX",  # NOT in tmp's referent set
        }
    )


def test_membership_rate_counts_only_referent_members():
    result = score_pham_disambiguation(_mapped_df(), C, _oracle(), vocab="CHEBI")
    core = result["comparable_core"]
    # suc + H are members; tmp off-target; PPP no prediction -> 2 of 4 scored names.
    assert core["metric"] == "referent_membership_rate"
    assert core["member"] == 2
    assert core["scored_denominator"] == 4
    assert core["referent_membership_rate"] == pytest.approx(0.5)


def test_structural_precision_is_over_predicted_names():
    result = score_pham_disambiguation(_mapped_df(), C, _oracle(), vocab="CHEBI")
    prec = result["structural_precision"]
    # 3 names predicted (suc/H/tmp); 2 of those are legitimate referents.
    assert prec["predicted_denominator"] == 3
    assert prec["member"] == 2
    assert prec["precision"] == pytest.approx(2 / 3)


def test_coverage_and_ambiguity_collapse_diagnostic():
    result = score_pham_disambiguation(_mapped_df(), C, _oracle(), vocab="CHEBI")
    assert result["coverage"]["n_predicted"] == 3
    assert result["coverage"]["total"] == 4
    amb = result["ambiguity"]
    # every scored name is genuinely ambiguous (>=2 referents) while a Top-1 mapper surfaces <=1 ->
    # full collapse (the paper's silent-collapse concern, reported as context not gated).
    assert amb["collapse_rate"] == pytest.approx(1.0)
    assert amb["collapsed"] == 4
    assert amb["mean_gold_referents"] == pytest.approx((2 + 2 + 3 + 2) / 4)
    assert amb["mean_predicted_referents"] == pytest.approx(3 / 4)  # suc/H/tmp surfaced 1, PPP 0


def test_off_target_prediction_is_not_a_member():
    result = score_pham_disambiguation(_mapped_df(), C, _oracle(), vocab="CHEBI")
    tmp_row = next(r for r in result["per_row"] if r["name"] == "tmp")
    assert tmp_row["predicted_block"] == "WRONGBLOCKXXXX"
    assert tmp_row["member"] is False
    assert tmp_row["scored"] is True


def test_no_prediction_is_a_miss():
    result = score_pham_disambiguation(_mapped_df(), C, _oracle(), vocab="CHEBI")
    ppp_row = next(r for r in result["per_row"] if r["name"] == "PPP")
    assert ppp_row["chosen_kg_id"] is None
    assert ppp_row["member"] is False
    assert ppp_row["n_predicted_referents"] == 0


def test_empty_frame_fails_loud():
    empty = pd.DataFrame({C.name_column: [], C.gold_referent_inchikey_column: [], "chosen_kg_id": []})
    with pytest.raises(UnscorableRunError, match="nothing to score"):
        score_pham_disambiguation(empty, C, _oracle())
