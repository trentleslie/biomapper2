"""Can an unrecorded annotation vintage be RECOVERED by fingerprinting?

No Metabolon deliverable carries a release/version field (LIB_ID is the 4 chromatography methods;
CHRO_LIB_ENTRY_ID is per-compound), Monti's paper records none, and the supplement schema has none.
So a study's annotation vintage is unrecorded.

But annotation vintages differ from each other, and those differences are a signature. If NECS's gold
agrees overwhelmingly with one dated panel and disagrees with the others, the vintage is recoverable
even though it was never written down.

Tested over ALL shared compound names, not the 8 known defects, so the answer is not circular.
"""
import csv, os, re
from collections import defaultdict

NECS = os.path.expanduser(
    "~/external_benchmark_runs/scorer_rerun_20260723/necs/necs-metabolon_CHEBI_MAPPED.tsv")
PANELS = {
    "2019_Metabolon_Metadata.csv": ("BIOCHEMICAL NAME", "INCHIKEY", "Metabolon 2019"),
    "LEOCC_Metabolon_Annotations.csv": ("CHEMICAL_NAME", "INCHIKEY", "Metabolon LEOCC"),
    "Metabolon_Annotations_Serum_hmdbformatted.csv": ("CHEMICAL_NAME", "INCHIKEY", "Metabolon Serum"),
    "Broad_2022Aug_annotations.csv": ("name", "inChIKey", "Broad 2022"),
}
NULL = {"", "na", "nan", "none", "null", "-"}


def cl(v):
    s = "" if v is None else str(v).strip()
    return "" if s.lower() in NULL else s


def b1(ik):
    p = cl(ik).upper().split("-")
    return p[0] if len(p) >= 2 and len(p[0]) == 14 and p[0].isalpha() else None


def nn(n):
    return re.sub(r"\s+", " ", cl(n).lower().rstrip("*").strip())


necs = {}
for r in csv.DictReader(open(NECS, encoding="utf-8"), delimiter="\t"):
    n, k = nn(r["chemical_name"]), b1(r["gold_inchikey"])
    if n and k:
        necs[n] = k
print(f"NECS names with a usable gold InChIKey: {len(necs)}\n")

print(f"{'panel':20s} {'shared':>8s} {'agree':>8s} {'disagree':>9s} {'agreement':>10s}")
print("-" * 60)
for fn, (nc, kc, label) in PANELS.items():
    p = {}
    for r in csv.DictReader(open("/tmp/mlk/" + fn, encoding="utf-8", errors="replace")):
        n, k = nn(r.get(nc, "")), b1(r.get(kc, ""))
        if n and k:
            p.setdefault(n, set()).add(k)
    shared = [n for n in necs if n in p]
    agree = [n for n in shared if necs[n] in p[n]]
    dis = [n for n in shared if necs[n] not in p[n]]
    if shared:
        print(f"{label:20s} {len(shared):8d} {len(agree):8d} {len(dis):9d} {len(agree)/len(shared):9.1%}")

print()
print("  A vintage that NECS was delivered should agree at ~100% on connectivity.")
print("  Lower agreement = a different vintage or a different curator.")
