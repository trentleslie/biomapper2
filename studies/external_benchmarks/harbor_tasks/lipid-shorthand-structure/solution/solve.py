"""Oracle: emit the LMSD reference structure (gold SMILES) for each shorthand.

The oracle is allowed to know the answer key. It reads the bundled name -> gold-SMILES
map (shipped in solution/, copied into the agent container by the Oracle agent) and writes
one predictions row per input lipid. Because the gold-quality gate guarantees the gold's
formula equals the neutral name formula, every gradeable case species-matches -> the
oracle scores the fair metric at 1.0.
"""

from __future__ import annotations

import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
GOLD = SCRIPT_DIR / "gold_solution.jsonl"
LIPIDS = Path("/app/lipids.txt")
OUT = Path("/app/results/predictions.tsv")


def main() -> None:
    answers = {
        r["name"]: r["smiles"]
        for r in (json.loads(l) for l in GOLD.read_text().splitlines() if l.strip())
    }
    names = [n for n in LIPIDS.read_text().splitlines() if n.strip()]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w") as f:
        for name in names:
            f.write(f"{name}\t{answers.get(name, '')}\n")
    print(f"[oracle] wrote {len(names)} predictions to {OUT}")


if __name__ == "__main__":
    main()
