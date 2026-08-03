"""Oracle: emit the third-party gold answer per input (allowed to know the key)."""
import json
from pathlib import Path
SD = Path(__file__).resolve().parent
GOLD = SD / "gold_solution.jsonl"   # {"name":..,"smiles":..} per row (rename per candidate)
INP = Path("/app/lipids.txt"); OUT = Path("/app/results/predictions.tsv")
def main():
    ans = {r["name"]: r["smiles"] for r in (json.loads(l) for l in GOLD.read_text().splitlines() if l.strip())}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w") as f:
        for n in (x for x in INP.read_text().splitlines() if x.strip()):
            f.write(f"{n}\t{ans.get(n,'')}\n")
if __name__ == "__main__":
    main()
