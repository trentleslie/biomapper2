"""Pham name-disambiguation scorer (offline; mapped_df + FakeOracle in, metrics out).

Only BioMapper's PREDICTION (``chosen_kg_id``) is resolved through the (fake) oracle; the referent
gold set is read from the held-out column. Structure blocks are synthetic + distinct (documented) —
the scorer is structure-value-agnostic, it only tests full-population + ambiguous-subset membership,
the Part-1-fixed precision, and the collapse diagnostic.
"""

from __future__ import annotations

import pandas as pd
import pytest

from studies.external_benchmarks.config import PHAM_DISAMBIGUATION
from studies.external_benchmarks.scorers.pham_scorer import UnscorableRunError, score_pham_disambiguation
from studies.external_benchmarks.tests.conftest import FakeOracle

C = PHAM_DISAMBIGUATION


def _mapped_df() -> pd.DataFrame:
    """A post-run mapped frame: chosen_kg_id + the held-out referent gold columns (rides along).

    Six rows exercising every case:
      - suc, H     : ambiguous (2 referents), predicted ON a legitimate referent -> members
      - tmp        : ambiguous (3), predicted OFF-target -> predicted-but-not-member (hallucination)
      - PPP        : ambiguous (2), NO prediction -> a miss
      - gluc       : UNAMBIGUOUS (1 referent), predicted correctly -> full-pop member, NOT in subset
      - cov        : coverage-only (EMPTY referent set) WITH a prediction -> excluded from BOTH the
                     scored denominator AND the precision denominator (the Part-1 fix)
    """
    return pd.DataFrame(
        {
            C.name_column: ["suc", "H", "tmp", "PPP", "gluc", "cov"],
            C.gold_referent_inchikey_column: [
                "SUCCINATEBLOCK-AAAAAAAAAA-N|SUCROSEBLOCKXX-BBBBBBBBBB-N",
                "PROTONBLOCKXXX-CCCCCCCCCC-N|HISTIDINEBLOCK-DDDDDDDDDD-N",
                "TMPBLOCKXXXXXX-EEEEEEEEEE-N|THYMIDINEMPXXX-FFFFFFFFFF-N|THIAMINEMPXXXX-GGGGGGGGGG-N",
                "TRIPHOSPHATEXX-JJJJJJJJJJ-N|PHENYLPIPERXX-KKKKKKKKKK-N",
                "GLUCOSEBLOCKXX-IIIIIIIIII-N",
                "",  # coverage-only: no referent set to score against
            ],
            C.referent_count_column: [2, 2, 3, 2, 1, 0],
            "chosen_kg_id": ["CHEBI:30031", "CHEBI:15378", "CHEBI:9999", "", "CHEBI:4167", "CHEBI:12345"],
        }
    )


def _oracle() -> FakeOracle:
    return FakeOracle(
        kg_blocks={
            "CHEBI:30031": "SUCCINATEBLOCK",  # member of suc's referent set
            "CHEBI:15378": "PROTONBLOCKXXX",  # member of H's referent set
            "CHEBI:9999": "WRONGBLOCKXXXX",  # NOT in tmp's referent set (off-target)
            "CHEBI:4167": "GLUCOSEBLOCKXX",  # member of gluc's single referent
            "CHEBI:12345": "ANYBLOCKXXXXXX",  # cov row — but gold is empty, so never scored
        }
    )


def test_full_population_membership_counts_all_scored_names():
    result = score_pham_disambiguation(_mapped_df(), C, _oracle(), vocab="CHEBI")
    core = result["comparable_core"]
    # Scored full population = suc,H,tmp,PPP,gluc (cov excluded, empty gold). Members = suc,H,gluc.
    assert core["metric"] == "referent_membership_rate"
    assert core["scored_denominator"] == 5
    assert core["member"] == 3
    assert core["referent_membership_rate"] == pytest.approx(3 / 5)


def test_ambiguous_subset_is_broken_out():
    result = score_pham_disambiguation(_mapped_df(), C, _oracle(), vocab="CHEBI")
    amb = result["ambiguous_subset"]
    # Ambiguous (>=2 referents) = suc,H,tmp,PPP (gluc has 1, excluded). Members = suc,H.
    assert amb["ambiguous_min_referents"] == 2
    assert amb["scored_denominator"] == 4
    assert amb["member"] == 2
    assert amb["referent_membership_rate"] == pytest.approx(0.5)


def test_structural_precision_excludes_coverage_only_row():
    result = score_pham_disambiguation(_mapped_df(), C, _oracle(), vocab="CHEBI")
    prec = result["structural_precision"]
    # Predictions with a non-empty referent set = suc,H,tmp,gluc (4). cov predicted but has empty gold,
    # so it must NOT dilute the precision denominator (Part-1 fix). Members = suc,H,gluc = 3.
    assert prec["predicted_denominator"] == 4
    assert prec["member"] == 3
    assert prec["precision"] == pytest.approx(3 / 4)


def test_coverage_counts_all_predictions():
    result = score_pham_disambiguation(_mapped_df(), C, _oracle(), vocab="CHEBI")
    cov = result["coverage"]
    # All predictions (incl. the coverage-only row) = suc,H,tmp,gluc,cov = 5 of 6 total.
    assert cov["n_predicted"] == 5
    assert cov["total"] == 6


def test_ambiguity_collapse_diagnostic_over_ambiguous_subset():
    result = score_pham_disambiguation(_mapped_df(), C, _oracle(), vocab="CHEBI")
    amb = result["ambiguity"]
    assert amb["ambiguous_scored"] == 4
    assert amb["collapse_rate"] == pytest.approx(1.0)  # a Top-1 mapper surfaces <=1 of >=2 referents
    assert amb["collapsed"] == 4
    assert amb["mean_gold_referents"] == pytest.approx((2 + 2 + 3 + 2) / 4)
    assert amb["mean_predicted_referents"] == pytest.approx(3 / 4)  # suc/H/tmp surfaced 1, PPP 0


def test_off_target_prediction_is_not_a_member():
    result = score_pham_disambiguation(_mapped_df(), C, _oracle(), vocab="CHEBI")
    tmp_row = next(r for r in result["per_row"] if r["name"] == "tmp")
    assert tmp_row["predicted_block"] == "WRONGBLOCKXXXX"
    assert tmp_row["member"] is False
    assert tmp_row["scored"] is True
    assert tmp_row["is_ambiguous"] is True


def test_unambiguous_row_scored_but_not_in_subset():
    result = score_pham_disambiguation(_mapped_df(), C, _oracle(), vocab="CHEBI")
    gluc_row = next(r for r in result["per_row"] if r["name"] == "gluc")
    assert gluc_row["scored"] is True
    assert gluc_row["member"] is True
    assert gluc_row["is_ambiguous"] is False


def test_no_prediction_is_a_miss():
    result = score_pham_disambiguation(_mapped_df(), C, _oracle(), vocab="CHEBI")
    ppp_row = next(r for r in result["per_row"] if r["name"] == "PPP")
    assert ppp_row["chosen_kg_id"] is None
    assert ppp_row["member"] is False
    assert ppp_row["n_predicted_referents"] == 0


def test_coverage_only_row_is_not_scored():
    result = score_pham_disambiguation(_mapped_df(), C, _oracle(), vocab="CHEBI")
    cov_row = next(r for r in result["per_row"] if r["name"] == "cov")
    assert cov_row["scored"] is False
    assert cov_row["is_ambiguous"] is False


def test_empty_frame_fails_loud():
    empty = pd.DataFrame({C.name_column: [], C.gold_referent_inchikey_column: [], "chosen_kg_id": []})
    with pytest.raises(UnscorableRunError, match="nothing to score"):
        score_pham_disambiguation(empty, C, _oracle())
