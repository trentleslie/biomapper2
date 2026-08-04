from studies.northstar_e2e.interpret import Interpretation
from studies.northstar_e2e.scorers import pathway_overlap as po

GOLD = ("map00280", "map00250", "map00260", "map00020", "map00010")


def test_perfect_ranking():
    interp = Interpretation(GOLD, "type 2 diabetes")
    s = po.score_pathways(interp, gold_pathways=GOLD)
    assert s["recall"] == 1.0
    assert s["precision"] == 1.0
    assert s["f1"] == 1.0
    assert s["hits_at_k"][5] == 1.0
    assert s["first_gold_rank"] == 1
    assert s["disease_match"] is True


def test_partial_with_noise():
    interp = Interpretation(("map99999", "map00280", "map00020"), "diabetes")
    s = po.score_pathways(interp, gold_pathways=GOLD)
    assert s["recall"] == 2 / 5
    assert s["precision"] == 2 / 3
    assert s["hits_at_k"][1] == 0.0  # top-1 is noise
    assert s["rank_of_gold"]["map00280"] == 2
    assert s["rank_of_gold"]["map00250"] is None
    assert s["first_gold_rank"] == 2


def test_disease_label_normalized_match():
    interp = Interpretation(GOLD, "Type 2 Diabetes Mellitus")
    s = po.score_pathways(interp, gold_pathways=GOLD, disease_label="type 2 diabetes")
    assert s["disease_match"] is True


def test_primary_metric_is_f1():
    interp = Interpretation(("map00280",), "t2d")
    s = po.score_pathways(interp, gold_pathways=GOLD)
    assert po.primary_metric(s) == s["f1"]
