"""Candidate-AGNOSTIC Harbor verifier core (the reusable pipeline).

This module is the heart of the reusable benchmark-candidate pipeline. It knows
NOTHING about lipids. It knows only:

  * the agent output contract  -> ``/app/results/predictions.tsv``  (``name<TAB>answer``)
  * the bundled gold contract   -> ``gold.jsonl``  (one JSON row per case)
  * a pluggable ``ReferenceAdapter`` that turns a case name + the agent's answer
    into the normalised quantities the (shared) scorer compares.

A new benchmark candidate plugs in by supplying:
  1. a ``gold.jsonl`` (list of cases), and
  2. a ``ReferenceAdapter`` implementation (see ``AdapterProtocol`` below).

Everything else — the gate, the two-metric species/strict scoring, the failure
taxonomy, aggregation, and the reward.json/score_breakdown.json emission — is shared
and lives here + in the vendored ``score.py`` (both copied verbatim from the validated
lipid spike, so the numbers match the spike run exactly).

Reward model (mirrors the terminal-bench-science ``ont-tn-qc`` reference task):
  * a fractional diagnostic score is computed (here: species-match rate over gradeable
    cases) and retained in ``score_breakdown.json``;
  * the official binary reward = 1.0 iff the fractional score >= ``pass_threshold``,
    else 0.0. ``pass_threshold`` is the difficulty dial that must be calibrated by the
    real Harbor run + ``harbor analyze`` to land the task in the 10-20% solve band.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

# ``score`` is vendored verbatim from the lipid spike (studies/.../spike_lipid/score.py).
# It is pure (no rdkit/pygoslin) and fully unit-tested there.
from score import (  # type: ignore
    aggregate,
    gold_quality_gate,
    score_name,
)


class AdapterProtocol(Protocol):
    """What a candidate-specific reference adapter must provide.

    The lipid adapter (``reference_lipid.py``) wraps pygoslin (name -> sum formula +
    components) and RDKit (SMILES -> formula / InChIKey). A different candidate supplies
    its own neutral, third-party grader here — never the tool under test.
    """

    def parse_reference(self, name: str): ...          # -> ShorthandParse-like
    def formula_from_answer(self, answer: str | None) -> str | None: ...
    def inchikey_from_answer(self, answer: str | None) -> str | None: ...
    def class_check(self, answer: str | None, cls: str | None) -> bool | None: ...


@dataclass(frozen=True)
class GradeResult:
    aggregate: object            # score.Aggregate
    fractional_score: float | None
    reward: float
    pass_threshold: float
    per_case: list[dict]


def read_predictions(path: Path) -> dict[str, str]:
    """Parse the agent output contract: TSV of ``name<TAB>answer`` (header optional).

    Robust to a header row, blank lines, and duplicate names (last wins). Missing file
    -> empty dict (every case then scores as ``no_structure_emitted``).
    """
    preds: dict[str, str] = {}
    if not path.exists():
        return preds
    for raw in path.read_text().splitlines():
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        name, answer = parts[0].strip(), parts[1].strip()
        if name.lower() in ("name", "lipid_name", "shorthand"):  # header
            continue
        preds[name] = answer
    return preds


def load_gold(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def grade(
    *,
    gold: list[dict],
    predictions: dict[str, str],
    adapter: AdapterProtocol,
    pass_threshold: float,
) -> GradeResult:
    scores = []
    per_case: list[dict] = []
    for case in gold:
        name = case["name"]
        gold_inchikey = case.get("gold_inchikey", "")
        gold_smiles = case.get("gold_smiles", "")

        ref = adapter.parse_reference(name)
        gold_formula = adapter.formula_from_answer(gold_smiles)
        gradeable = gold_quality_gate(
            parsed=ref.parsed, ref_formula=ref.formula, gold_formula=gold_formula
        )

        answer = predictions.get(name)
        model_formula = adapter.formula_from_answer(answer) if answer else None
        model_ik = adapter.inchikey_from_answer(answer) if answer else None
        class_ok = adapter.class_check(answer, ref.lipid_class) if answer else None

        s = score_name(
            name=name,
            gradeable=gradeable,
            model_smiles=answer,
            model_formula=model_formula,
            model_inchikey=model_ik,
            ref_formula=ref.formula,
            gold_inchikey=gold_inchikey,
            class_ok=class_ok,
            ref_total_carbons=ref.total_carbons,
            ref_total_db=ref.total_double_bonds,
            ref_class=ref.lipid_class,
        )
        scores.append(s)
        per_case.append(
            {
                "name": name,
                "gradeable": gradeable,
                "species_pass": s.species_pass,
                "strict_block_pass": s.strict_block_pass,
                "failure_bucket": s.failure_bucket,
                "ref_formula": ref.formula,
                "model_formula": model_formula,
                "answered": bool(answer),
            }
        )

    agg = aggregate(scores)
    frac = agg.species_match_rate
    reward = 1.0 if (frac is not None and frac >= pass_threshold) else 0.0
    return GradeResult(
        aggregate=agg,
        fractional_score=frac,
        reward=reward,
        pass_threshold=pass_threshold,
        per_case=per_case,
    )


def write_outputs(result: GradeResult, verifier_dir: Path) -> None:
    """Emit the Harbor reward + a human-readable breakdown."""
    verifier_dir.mkdir(parents=True, exist_ok=True)
    agg = result.aggregate
    breakdown = {
        "fractional_score": result.fractional_score,
        "pass_threshold": result.pass_threshold,
        "reward": result.reward,
        "scores": agg.as_dict(),  # type: ignore[attr-defined]
        "per_case": result.per_case,
    }
    (verifier_dir / "score_breakdown.json").write_text(json.dumps(breakdown, indent=2))
    reward_json = {
        "reward": result.reward,
        "species_match_rate": result.fractional_score,
        "strict_block_rate": agg.strict_block_rate,      # type: ignore[attr-defined]
        "n_gradeable": agg.n_gradeable,                  # type: ignore[attr-defined]
        "n_drawn": agg.n_drawn,                          # type: ignore[attr-defined]
    }
    (verifier_dir / "reward.json").write_text(json.dumps(reward_json, indent=2))
    (verifier_dir / "reward.txt").write_text(f"{result.reward}\n")
