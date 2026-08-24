"""Score NECS predictions against BOTH the original and the repaired gold (Unit 6, offline core).

Decision #2 makes Unit 6 a LIVE re-derive: current-dev BioMapper runs fresh over the NECS panel
(a supervised operator step, not fired here), and its per-row predictions are scored against both
golds by ``score_both_golds`` below. That function is pure and offline-tested; only ``load_and_score``
reads a run directory.

Guarantees baked in as controls (the project's history is that guards report clean via a blind spot):
  * Reproduction: scoring with the ORIGINAL gold re-derives the run's own numerator AND denominator.
  * Identity: a repaired map equal to the original golds reproduces the baseline exactly — this
    exercises the repaired-path join, not just the original path.
  * Abstention is costly: every rate is emitted as (numerator, denominator, abstained), with a
    pessimistic figure (abstained = misses) alongside, so refusing rows cannot silently inflate.
  * The primary delta is on the FIXED intersection population; rows newly covered by the repair are
    a separate ``newly_covered`` bucket, never folded into the correction delta.

NOTE (from review): the persisted ``predicted_block`` is block-1 only, so scoring is at connectivity.
State this in any report; do not claim block1+block2[:8] scoring off a block-1 prediction side.
"""

from __future__ import annotations

from collections import Counter
from typing import Any


def _b1(key: str | None) -> str:
    return (key or "").strip().split("-")[0].upper() if key else ""


def score_both_golds(per_row: list[dict[str, Any]], repaired_map: dict[str, str]) -> dict[str, Any]:
    """Score predictions against original and repaired gold (block-1).

    ``per_row``: [{name, predicted_block, gold_block}, ...] from the fresh/persisted run.
    ``repaired_map``: name -> repaired InChIKey (from build_repaired_gold); a name ABSENT or mapped
    to "" is an abstention under the repaired gold (undecidable / pending anchor).
    """
    orig_num = orig_den = 0
    rep_num = rep_den = rep_abstain = 0
    changed: Counter[str] = Counter()
    newly_covered_num = newly_covered_den = 0

    for r in per_row:
        name = str(r.get("name", ""))
        pred = _b1(r.get("predicted_block"))
        gold_o = _b1(r.get("gold_block"))

        has_orig = bool(gold_o)
        if has_orig:
            orig_den += 1
            orig_correct = pred == gold_o
            orig_num += int(orig_correct)

        repaired_key = repaired_map.get(name, "")
        gold_r = _b1(repaired_key)
        if not gold_r:
            if has_orig:
                rep_abstain += 1  # had an original gold, repaired says undecidable -> abstain
            continue

        rep_den += 1
        rep_correct = pred == gold_r
        rep_num += int(rep_correct)

        if not has_orig:
            newly_covered_den += 1
            newly_covered_num += int(rep_correct)
        elif gold_r != gold_o:  # the gold row actually changed
            changed[
                (
                    "fixed"
                    if rep_correct and not orig_correct
                    else (
                        "broke"
                        if orig_correct and not rep_correct
                        else "still_correct" if rep_correct else "still_wrong"
                    )
                )
            ] += 1

    # intersection population: rows scored under BOTH golds (exclude newly-covered)
    inter_rep_num = rep_num - newly_covered_num
    inter_rep_den = rep_den - newly_covered_den
    return {
        "original": {"numerator": orig_num, "denominator": orig_den},
        "repaired": {"numerator": rep_num, "denominator": rep_den, "abstained": rep_abstain},
        "repaired_pessimistic": {
            "numerator": rep_num,
            "denominator": rep_den + rep_abstain,
        },
        "intersection": {"numerator": inter_rep_num, "denominator": inter_rep_den},
        "newly_covered": {"numerator": newly_covered_num, "denominator": newly_covered_den},
        "changed_rows": dict(changed),
        "scoring_layer": "block1 (predicted_block is connectivity-only)",
    }
