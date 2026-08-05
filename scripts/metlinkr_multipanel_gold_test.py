"""FIELD TEST, third attempt: cross-panel gold disagreement across metLinkR's raw input panels.

Prior attempts and why they were insufficient:
  SRM1950  one independent path, so "gold disagrees" was not separable from convention.
  COMETS   two paths, but ManualMappings.csv is the CURATORS' FINISHED PRODUCT, so identifiers they
           reconciled while building the cross-links were removed before they could be counted.

metLinkR's SI ``pr4c01051_si_001.zip`` ships the RAW INPUT panels, pre-curation. Four of them carry
an InChIKey column outright, so two panels can be compared with no resolution step at all:

  Broad_2022Aug_annotations.csv               Broad     (independent curation)
  2019_Metabolon_Metadata.csv                 Metabolon
  LEOCC_Metabolon_Annotations.csv             Metabolon
  Metabolon_Annotations_Serum_hmdbformatted   Metabolon

The Broad-vs-Metabolon comparison is the real test: different curators, different vendors, structure
on both sides, nothing reconciled between them. Metabolon-vs-Metabolon pairs act as a CONTROL: they
share an annotation lineage, so they should agree, and a high disagreement rate there would indicate
a bug in this script rather than a finding.

Adjudication key is block 1 plus the 8-character stereo hash, the same key used throughout, so
legacy two-block and standard three-block InChIKeys compare correctly.
"""

from __future__ import annotations

import csv
import itertools
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

SRC = Path("/tmp/mlk")
OUT = Path(os.path.expanduser("~/external_benchmark_runs/cohort_panels_20260804"))

# panel file -> (name column, inchikey column, curating party)
PANELS = {
    "Broad_2022Aug_annotations.csv": ("name", "inChIKey", "Broad"),
    "2019_Metabolon_Metadata.csv": ("BIOCHEMICAL NAME", "INCHIKEY", "Metabolon"),
    "LEOCC_Metabolon_Annotations.csv": ("CHEMICAL_NAME", "INCHIKEY", "Metabolon"),
    "Metabolon_Annotations_Serum_hmdbformatted.csv": ("CHEMICAL_NAME", "INCHIKEY", "Metabolon"),
}
_NULL = frozenset({"", "na", "nan", "none", "null", "-"})


def clean(v) -> str:
    s = "" if v is None else str(v).strip()
    return "" if s.lower() in _NULL else s


def key(ik: str) -> str | None:
    """block1 + '-' + first 8 chars of block2. Handles legacy 14-10 and standard 14-10-1."""
    ik = clean(ik).upper()
    p = ik.split("-")
    if len(p) < 2 or len(p[0]) != 14 or not p[0].isalpha():
        return None
    return f"{p[0]}-{p[1][:8]}"


def norm_name(n: str) -> str:
    n = clean(n).lower().rstrip("*").strip()
    return re.sub(r"\s+", " ", n)


def load(fn: str) -> dict[str, set[str]]:
    ncol, kcol, _ = PANELS[fn]
    out: dict[str, set[str]] = defaultdict(set)
    with open(SRC / fn, encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            n, k = norm_name(row.get(ncol, "")), key(row.get(kcol, ""))
            if n and k:
                out[n].add(k)
    return dict(out)


def main() -> None:
    panels = {}
    for fn in PANELS:
        if not (SRC / fn).exists():
            sys.exit(f"missing {SRC / fn}; extract pr4c01051_si_001.zip to {SRC} first")
        panels[fn] = load(fn)
        print(f"{fn[:44]:46s} {len(panels[fn]):5d} names with a usable InChIKey  ({PANELS[fn][2]})")
    print()

    results = []
    for a, b in itertools.combinations(PANELS, 2):
        pa, pb = PANELS[a][2], PANELS[b][2]
        shared = sorted(set(panels[a]) & set(panels[b]))
        if not shared:
            continue
        agree = [n for n in shared if panels[a][n] & panels[b][n]]
        disagree = [n for n in shared if not (panels[a][n] & panels[b][n])]
        kind = "CROSS-VENDOR" if pa != pb else "control (same vendor)"
        results.append({"a": a, "b": b, "pair": f"{pa} vs {pb}", "kind": kind,
                        "shared": len(shared), "agree": len(agree), "disagree": len(disagree),
                        "rate": len(disagree) / len(shared) if shared else None,
                        "examples": [{"name": n, "a_keys": sorted(panels[a][n]),
                                      "b_keys": sorted(panels[b][n])} for n in disagree[:40]]})

    results.sort(key=lambda r: (r["kind"] != "CROSS-VENDOR", -r["shared"]))
    print(f"{'panel pair':30s} {'kind':22s} {'shared':>7s} {'agree':>7s} {'disagree':>9s} {'rate':>7s}")
    print("-" * 88)
    for r in results:
        print(f"{r['pair']:30s} {r['kind']:22s} {r['shared']:7d} {r['agree']:7d} "
              f"{r['disagree']:9d} {r['rate']:6.1%}")

    cross = [r for r in results if r["kind"] == "CROSS-VENDOR"]
    ctrl = [r for r in results if r["kind"] != "CROSS-VENDOR"]
    print()
    for label, grp in (("CROSS-VENDOR", cross), ("CONTROL (same vendor)", ctrl)):
        s = sum(r["shared"] for r in grp)
        d = sum(r["disagree"] for r in grp)
        if s:
            print(f"  {label:24s} shared={s:5d}  disagree={d:4d}  = {d/s:.1%}")
    print("\n  A high control rate would mean a bug in this script, not a finding.")

    if cross:
        print("\n  cross-vendor disagreements (same name, different structure):")
        for ex in cross[0]["examples"][:25]:
            print(f"    {ex['name'][:38]:40s} {ex['a_keys'][0]:24s} vs {ex['b_keys'][0]}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "metlinkr_multipanel_gold_test.json").write_text(json.dumps(results, indent=2))
    print(f"\nsaved -> {OUT / 'metlinkr_multipanel_gold_test.json'}")


if __name__ == "__main__":
    main()
