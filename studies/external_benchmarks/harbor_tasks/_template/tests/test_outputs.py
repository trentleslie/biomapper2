"""Verifier-integrity pytest. Must hold regardless of agent performance."""
import json
import grade, harbor_grade
_R = grade.compute(); harbor_grade.write_outputs(_R, grade.VERIFIER_DIR)

def test_gate_reasonable():
    agg = _R.aggregate
    assert agg.n_drawn > 0 and 0.30 <= agg.gate_pass_rate <= 1.0 and agg.n_gradeable >= 10

def test_reward_consistent():
    vd = grade.VERIFIER_DIR
    rj = json.loads((vd / "reward.json").read_text())
    assert float((vd / "reward.txt").read_text().strip()) == rj["reward"] and rj["reward"] in (0.0, 1.0)

def test_oracle_floor():
    gold = harbor_grade.load_gold(grade.GOLD_PATH)
    oracle = {c["name"]: c["gold_smiles"] for c in gold}   # rename gold_* key per candidate
    res = harbor_grade.grade(gold=gold, predictions=oracle, adapter=grade.Adapter(), pass_threshold=grade.PASS_THRESHOLD)
    assert res.aggregate.species_match_rate == 1.0
