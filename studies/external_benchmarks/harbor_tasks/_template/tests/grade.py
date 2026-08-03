"""CANDIDATE glue: bind the shared driver to this candidate's neutral grader.
Vendor score.py + harbor_grade.py (from ../_lib and the spike) into this tests/ dir, and
provide reference_<candidate>.py exposing the four adapter methods."""
from __future__ import annotations
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harbor_grade
import reference_candidate as R   # <-- rename to your reference_<candidate>.py

class Adapter:
    def parse_reference(self, name): return R.parse(name)            # -> obj w/ .parsed/.formula/.lipid_class/.total_carbons/.total_double_bonds
    def formula_from_answer(self, a): return R.formula(a) if a else None
    def inchikey_from_answer(self, a): return R.inchikey(a) if a else None
    def class_check(self, a, cls): return R.class_ok(a, cls) if a else None

GOLD_PATH = Path(os.environ.get("CAND_GOLD_PATH", "/tests/gold.jsonl"))
PRED_PATH = Path(os.environ.get("CAND_PRED_PATH", "/app/results/predictions.tsv"))
VERIFIER_DIR = Path(os.environ.get("CAND_VERIFIER_DIR", "/logs/verifier"))
PASS_THRESHOLD = float(os.environ.get("CAND_PASS_THRESHOLD", "0.40"))

def compute():
    gold = harbor_grade.load_gold(GOLD_PATH)
    preds = harbor_grade.read_predictions(PRED_PATH)
    return harbor_grade.grade(gold=gold, predictions=preds, adapter=Adapter(), pass_threshold=PASS_THRESHOLD)

def main():
    harbor_grade.write_outputs(compute(), VERIFIER_DIR)

if __name__ == "__main__":
    main()
