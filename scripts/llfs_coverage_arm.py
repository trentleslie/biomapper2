"""The one surviving claim: what does BioMapper recover from the names RefMet silently discards?

Monti et al.'s cross-vendor harmonization standardizes every name through RefMet and then calls
``drop_na(refmet_name)``. Anything RefMet cannot standardize is discarded BEFORE the join, so it can
never enter a cross-cohort analysis at all. On NECS that is 429 of 1,495 names.

This measures what BioMapper does with them. Two guards make the number honest:

  1. 282 of the 429 are unnamed ``x-NNNNN`` Metabolon feature codes. Nobody can map those, and
     counting them as an opportunity would inflate the denominator. The real target is the 147
     NAMED metabolites RefMet fails on.

  2. ``chosen_kg_id`` is non-empty on ALL 1,495 NECS rows, so it is useless as a coverage measure:
     BioMapper returns a best guess for garbage input too. 172 rows collapse onto the single node
     CHEBI:223492. A resolution counts here only if the chosen node CARRIES STRUCTURE (an InChIKey
     in its equivalence set) and is not part of a degenerate many-to-one collapse.

Reuses the existing mapped output rather than re-running the mapper: the compute is already paid for
and the input is byte-identical.
"""

from __future__ import annotations

import ast
import csv
import json
import os
import re
from collections import Counter
from pathlib import Path

RUNS = Path(os.path.expanduser("~/external_benchmark_runs"))
MAPPED = RUNS / "necs_hybrid_panel_v2_20260804" / "necs-metabolon_CHEBI_MAPPED.tsv"
REFMET_CACHE = RUNS / "cohort_panels_20260804" / "necs_refmet_convert_cache.tsv"
OUT = RUNS / "cohort_panels_20260804"

XCODE = re.compile(r"^\s*x\s*-\s*\d+", re.I)
# A node shared by more than this many distinct input names is a degenerate catch-all, not a
# resolution. CHEBI:223492 absorbs 172 rows; a real metabolite node should attract a handful at most.
COLLAPSE_THRESHOLD = 5


def clean(v) -> str:
    s = "" if v is None else str(v).strip()
    return "" if s.lower() in ("", "-", "na", "nan", "none", "null") else s


def equiv_inchikeys(cell: str) -> list[str]:
    try:
        d = ast.literal_eval(cell) if cell and cell.strip() else {}
    except Exception:
        return []
    return list(d.get("INCHIKEY") or []) if isinstance(d, dict) else []


def block(ik: str) -> str:
    return ik.split("-")[0] if ik else ""


def main() -> None:
    rows = list(csv.DictReader(open(MAPPED, encoding="utf-8"), delimiter="\t"))
    conv = {r["input"]: clean(r["refmet"]) for r in csv.DictReader(open(REFMET_CACHE, encoding="utf-8"),
                                                                   delimiter="\t")}
    # degenerate-collapse detection over the whole panel
    node_load = Counter(r["chosen_kg_id"].strip() for r in rows if r["chosen_kg_id"].strip())
    degenerate = {n for n, c in node_load.items() if c > COLLAPSE_THRESHOLD}
    print(f"nodes absorbing >{COLLAPSE_THRESHOLD} distinct input names (degenerate): {len(degenerate)}")
    for n, c in node_load.most_common(5):
        mark = "  <-- degenerate" if n in degenerate else ""
        print(f"    {n:22s} {c:4d} rows{mark}")
    print()

    def resolved_well(r) -> bool:
        node = r["chosen_kg_id"].strip()
        return bool(node) and node not in degenerate and bool(equiv_inchikeys(r["kg_equivalent_ids"]))

    def has_gold(r) -> bool:
        v = r["gold_inchikey"].strip().split("-")
        return len(v) == 2 and len(v[0]) == 14

    unstd = [r for r in rows if r["chemical_name"].strip() and not conv.get(r["chemical_name"].strip())]
    named = [r for r in unstd if not XCODE.match(r["chemical_name"])]
    xcodes = [r for r in unstd if XCODE.match(r["chemical_name"])]
    std = [r for r in rows if r["chemical_name"].strip() and conv.get(r["chemical_name"].strip())]

    print("What RefMet discards before Monti's join can run:")
    print(f"  NECS names RefMet cannot standardize : {len(unstd):5d} of {len(rows)}")
    print(f"     unnamed x-NNNNN feature codes     : {len(xcodes):5d}  (not a real opportunity)")
    print(f"     NAMED metabolites, the real target: {len(named):5d}")
    print()

    print("What BioMapper recovers from them:")
    for label, grp in (("named RefMet-discards", named), ("RefMet-standardizable (control)", std),
                       ("x-code discards", xcodes)):
        ok = sum(1 for r in grp if resolved_well(r))
        naive = sum(1 for r in grp if r["chosen_kg_id"].strip())
        print(f"  {label:34s} n={len(grp):5d}  naive non-empty={naive:5d} ({naive/len(grp):4.0%})"
              f"   STRUCTURE-BEARING={ok:5d} ({ok/len(grp):4.0%})")
    print()
    print("  The naive column is why this needed a filter: non-empty says 100% for garbage input.")
    print()

    # verifiable subset: named discards that carry a gold structure
    ver = [r for r in named if has_gold(r)]
    correct = 0
    detail = []
    for r in ver:
        gb = block(r["gold_inchikey"].strip())
        pb = {block(k) for k in equiv_inchikeys(r["kg_equivalent_ids"])}
        hit = gb in pb
        correct += hit
        detail.append({"name": r["chemical_name"], "gold_block": gb,
                       "predicted_blocks": "|".join(sorted(pb)), "correct": hit,
                       "resolved_well": resolved_well(r)})
    print(f"Independently verifiable subset (named discards carrying a gold structure): {len(ver)}")
    if ver:
        print(f"  BioMapper structurally correct: {correct}/{len(ver)} = {correct/len(ver):.0%}")
    print()
    for d in detail[:15]:
        print(f"    {'OK ' if d['correct'] else 'MISS'}  {d['name'][:40]:42s} gold={d['gold_block']}")

    recovered = sum(1 for r in named if resolved_well(r))
    (OUT / "llfs_coverage_arm.json").write_text(json.dumps({
        "necs_rows": len(rows),
        "refmet_discards_total": len(unstd), "refmet_discards_xcode": len(xcodes),
        "refmet_discards_named": len(named),
        "biomapper_structure_bearing_on_named_discards": recovered,
        "biomapper_structure_bearing_on_standardizable": sum(1 for r in std if resolved_well(r)),
        "verifiable_subset": len(ver), "verifiable_correct": correct,
        "degenerate_nodes": sorted(degenerate), "collapse_threshold": COLLAPSE_THRESHOLD,
        "source_mapped": str(MAPPED),
    }, indent=2))
    with open(OUT / "llfs_coverage_arm_verifiable.csv", "w", newline="") as fh:
        if detail:
            w = csv.DictWriter(fh, fieldnames=list(detail[0]))
            w.writeheader()
            w.writerows(detail)
    print(f"\nsaved -> {OUT}")


if __name__ == "__main__":
    main()
