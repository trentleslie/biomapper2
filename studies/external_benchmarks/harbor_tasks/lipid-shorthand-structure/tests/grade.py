"""Lipid-shorthand verifier entrypoint (candidate-SPECIFIC glue).

Reuses the validated spike grader verbatim:
  * ``reference_lipid`` = spike ``reference.py`` (pygoslin name->sum-formula + RDKit
    SMILES->formula/InChIKey) — the neutral, third-party grader (NEVER BioMapper).
  * ``score``           = spike ``score.py`` (gold-quality gate + species/strict metrics
    + failure taxonomy), imported by the shared ``harbor_grade`` driver.

The ONLY lipid-specific code here is ``LipidAdapter`` (four thin methods) and the paths.
A different benchmark candidate swaps ``LipidAdapter`` + ``gold.jsonl`` and reuses the
rest untouched. Computes the species-match rate over gradeable cases, then writes the
Harbor reward: binary 1.0 iff rate >= ``LIPID_PASS_THRESHOLD``, with the fractional score
and full breakdown retained for review / ``harbor analyze``.

Paths default to the in-container Harbor layout but are env-overridable for local
authoring self-tests.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # vendored modules alongside

import harbor_grade  # noqa: E402
import reference_lipid as R  # noqa: E402


class LipidAdapter:
    """Bind the shared driver to the lipid neutral grader (pygoslin + RDKit)."""

    def parse_reference(self, name: str):
        return R.default_goslin_parse(name)

    def formula_from_answer(self, answer: str | None) -> str | None:
        return R.default_formula_from_smiles(answer) if answer else None

    def inchikey_from_answer(self, answer: str | None) -> str | None:
        # the agent emits a SMILES; derive the strict key offline via RDKit
        return R.default_inchikey_from_smiles(answer) if answer else None

    def class_check(self, answer: str | None, cls: str | None):
        return R.class_backbone_ok(answer, cls) if answer else None


GOLD_PATH = Path(os.environ.get("LIPID_GOLD_PATH", "/tests/gold.jsonl"))
PRED_PATH = Path(os.environ.get("LIPID_PRED_PATH", "/app/results/predictions.tsv"))
VERIFIER_DIR = Path(os.environ.get("LIPID_VERIFIER_DIR", "/logs/verifier"))
PASS_THRESHOLD = float(os.environ.get("LIPID_PASS_THRESHOLD", "0.40"))


def compute():
    gold = harbor_grade.load_gold(GOLD_PATH)
    preds = harbor_grade.read_predictions(PRED_PATH)
    return harbor_grade.grade(
        gold=gold, predictions=preds, adapter=LipidAdapter(), pass_threshold=PASS_THRESHOLD
    )


def main() -> None:
    result = compute()
    harbor_grade.write_outputs(result, VERIFIER_DIR)
    agg = result.aggregate
    print(
        f"[lipid-verifier] species_match={result.fractional_score} "
        f"(threshold {PASS_THRESHOLD}) -> reward {result.reward}; "
        f"gradeable {agg.n_gradeable}/{agg.n_drawn}; taxonomy {agg.failure_taxonomy}"
    )


if __name__ == "__main__":
    main()
