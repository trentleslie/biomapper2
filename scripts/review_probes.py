"""Verify the three decisive review findings against data already in hand. No network."""
import csv, os, re, collections
import pandas as pd

RUNS = os.path.expanduser("~/external_benchmark_runs")
NECS = f"{RUNS}/scorer_rerun_20260723/necs/necs-metabolon_CHEBI_MAPPED.tsv"
ARIV = f"{RUNS}/arivale_public_panel_20260804/watanabe2023_supp_data2_analytes.xlsx"
LLFS = os.path.expanduser("~/worktrees/cross-cohort/data/NIHMS2038904-supplement-2.xlsx")
CACHE = f"{RUNS}/cohort_panels_20260804/necs_refmet_convert_cache.tsv"

def clean(v):
    s = "" if v is None else str(v).strip()
    return "" if s.lower() in ("", "-", "na", "nan", "none", "null") else s

def has_struct(r):
    v = (r.get("gold_inchikey") or "").strip().split("-")
    return len(v) == 2 and len(v[0]) == 14

print("=" * 72)
print("FINDING 2 (feasibility, P0): does LLFS carry ANY registry identifier?")
print("=" * 72)
x = pd.ExcelFile(LLFS)
for s in x.sheet_names:
    cols = list(x.parse(s, nrows=0).columns)
    idish = [c for c in cols if re.search(r"hmdb|pubchem|kegg|\bcas\b|inchi|smiles|chebi", str(c), re.I)]
    print(f"  sheet {s!r}: {len(cols)} cols; identifier-like: {idish or 'NONE'}")

print()
print("=" * 72)
print("FINDING 4 (product-lens, P0): do the RefMet-unstandardizable NECS names")
print("                              even HAVE a gold structure to adjudicate with?")
print("=" * 72)
necs = list(csv.DictReader(open(NECS, encoding="utf-8"), delimiter="\t"))
conv = {r["input"]: clean(r["refmet"]) for r in csv.DictReader(open(CACHE, encoding="utf-8"), delimiter="\t")}
unstd = [r for r in necs if (r["chemical_name"].strip() and not conv.get(r["chemical_name"].strip()))]
std = [r for r in necs if (r["chemical_name"].strip() and conv.get(r["chemical_name"].strip()))]
u_struct = sum(1 for r in unstd if has_struct(r))
s_struct = sum(1 for r in std if has_struct(r))
xcode = re.compile(r"^\s*x\s*-\s*\d+", re.I)
u_x = sum(1 for r in unstd if xcode.match(r["chemical_name"]))
print(f"  NECS rows RefMet CANNOT standardize : {len(unstd):5d}")
print(f"     of those, carrying gold structure: {u_struct:5d}  ({u_struct/len(unstd):.0%})")
print(f"     of those, unnamed 'x-NNNNN' codes: {u_x:5d}  ({u_x/len(unstd):.0%})")
print(f"  NECS rows RefMet CAN standardize    : {len(std):5d}")
print(f"     of those, carrying gold structure: {s_struct:5d}  ({s_struct/len(std):.0%})")
print()
print(f"  >>> The recall claim needs reference pairs the baseline MISSES.")
print(f"  >>> Ceiling on NECS side = {u_struct} rows (structure-bearing AND RefMet-invisible).")

print()
print("=" * 72)
print("FINDING 1 (adversarial + product-lens, P0): does the reference gold inherit")
print("                                            the vendor isomer collisions?")
print("=" * 72)
ariv = pd.read_excel(ARIV, sheet_name="Arivale_Metabolomics").fillna("")
# collision signature: one vendor id appearing on MORE THAN ONE Arivale row
for ns, col in (("CAS", "CAS_ID"), ("KEGG", "KEGG_ID"), ("HMDB", "HMDB_ID"), ("PUBCHEM", "PubChem_ID")):
    idx = collections.defaultdict(set)
    for _, r in ariv.iterrows():
        for v in re.split(r"[;,|]", clean(r.get(col))):
            v = v.strip().split(".")[0]
            if v:
                idx[v].add(clean(r["BiochemicalName"]))
    dup = {k: v for k, v in idx.items() if len(v) > 1}
    rows_hit = sum(len(v) for v in dup.values())
    print(f"  {ns:8s}: {len(dup):3d} ids appear on >1 Arivale analyte, touching {rows_hit:3d} analytes")
    for k, v in list(dup.items())[:3]:
        print(f"             {k:14s} -> {sorted(v)}")
n_any = set()
for ns, col in (("CAS", "CAS_ID"), ("KEGG", "KEGG_ID"), ("HMDB", "HMDB_ID"), ("PUBCHEM", "PubChem_ID")):
    idx = collections.defaultdict(set)
    for i, r in ariv.iterrows():
        for v in re.split(r"[;,|]", clean(r.get(col))):
            v = v.strip().split(".")[0]
            if v:
                idx[v].add(i)
    for k, v in idx.items():
        if len(v) > 1:
            n_any |= v
print(f"\n  >>> Arivale analytes whose vendor id is shared with another analyte: {len(n_any)} of {len(ariv)}"
      f"  ({len(n_any)/len(ariv):.0%})")
print("  >>> Every one of these is a row where an id-derived reference key may name the WRONG molecule.")
