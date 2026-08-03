"""Deterministic pytest verifier for the lipid-shorthand task.

Run inside the SEPARATE verifier container (pygoslin + RDKit + pytest installed; the
agent never sees this code). It:

  1. computes the grade from the agent's ``/app/results/predictions.tsv`` and writes the
     Harbor reward files (side effect, via ``grade.compute`` + ``harbor_grade.write_outputs``);
  2. asserts VERIFIER INTEGRITY invariants that must hold regardless of how well the
     agent did — so a weak agent yields reward 0.0 but never a *broken verifier*.

The authoritative reward is ``/logs/verifier/reward.json`` (written here). These pytest
assertions are the "is the grader itself sound" gate that reviewers / ``harbor analyze``
rely on; they intentionally do NOT assert the agent passed.
"""

from __future__ import annotations

import os
from pathlib import Path

import grade
import harbor_grade

_RESULT = grade.compute()
harbor_grade.write_outputs(_RESULT, grade.VERIFIER_DIR)


def test_gold_loaded_and_gate_reasonable():
    """The bundled gold parses and the neutral gate keeps a sizeable, non-trivial slice."""
    agg = _RESULT.aggregate
    assert agg.n_drawn > 0, "gold.jsonl produced no cases"
    # gate must keep a meaningful fraction (spike measured 73/100); guard against a
    # pygoslin/RDKit regression that would silently drop everything.
    assert 0.30 <= agg.gate_pass_rate <= 1.0, f"gate pass-rate off: {agg.gate_pass_rate}"
    assert agg.n_gradeable >= 10


def test_reward_files_written_and_consistent():
    vd = grade.VERIFIER_DIR
    import json

    reward_txt = (vd / "reward.txt").read_text().strip()
    reward_json = json.loads((vd / "reward.json").read_text())
    breakdown = json.loads((vd / "score_breakdown.json").read_text())
    assert float(reward_txt) == reward_json["reward"]
    assert reward_json["reward"] in (0.0, 1.0)
    assert breakdown["pass_threshold"] == _RESULT.pass_threshold
    # binary reward is exactly the threshold rule on the fractional score
    frac = reward_json["species_match_rate"]
    expected = 1.0 if (frac is not None and frac >= _RESULT.pass_threshold) else 0.0
    assert reward_json["reward"] == expected


def test_scoring_is_species_composition_not_exact_inchikey():
    """Guard the core design choice: grading is at sum-composition, not isomer identity.

    The strict full-InChIKey rate is the published 5.4% isomer lottery and must never be
    what the reward keys on. This pins that species-match (fair) is the graded metric.
    """
    agg = _RESULT.aggregate.as_dict()
    # species-match denominator is the gradeable set (not all drawn)
    assert agg["species_match"]["denominator"] == agg["n_gradeable"]
    # strict metrics are reported but are a *contrast*, not the reward basis
    assert "first_block_rate" in agg["strict_match"]
    assert "full_key_rate" in agg["strict_match"]


def test_oracle_gold_smiles_would_pass_species_match():
    """Sanity: feeding the gold SMILES as predictions species-matches on every gradeable
    case (gate guarantees gold formula == neutral name formula). This is the oracle floor
    the ``solution/`` reproduces and is the strongest check the grader isn't miscalibrated."""
    gold = harbor_grade.load_gold(grade.GOLD_PATH)
    oracle_preds = {c["name"]: c["gold_smiles"] for c in gold}
    res = harbor_grade.grade(
        gold=gold,
        predictions=oracle_preds,
        adapter=grade.LipidAdapter(),
        pass_threshold=grade.PASS_THRESHOLD,
    )
    # every gradeable case must species-match under the oracle
    assert res.aggregate.species_match_rate == 1.0, (
        f"oracle did not fully pass: {res.aggregate.species_match_rate}"
    )
