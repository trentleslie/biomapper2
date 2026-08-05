"""FIELD-LEVEL TEST: how often does independently curated cohort gold disagree with itself?

The NECS finding needed two independent measurements of the same molecule plus a third adjudicator.
SRM1950 failed to reproduce it because a single reference set supplies only one measurement.

The COMETS ManualMappings set supplies the missing apparatus natively. Expert curators linked
metabolites ACROSS five independent cohort datasets, and every row carries its own source dataset's
reference identifiers. So for any curator group spanning two or more datasets:

    the curators assert "these rows are the same molecule"
    each dataset independently asserts an identifier for it
    if those identifiers disagree, at least one dataset's gold is wrong

The curator linkage is independent of the identifiers (it is a human judgement about the metabolite),
and it is independent of any resolver. That is exactly the two-independent-measurements design, and
it spans five cohorts rather than one vendor.

This pass is LOCAL ONLY: it screens for within-group identifier conflicts. It does not yet adjudicate
which side is right; that needs the third path and is the follow-on.
"""
import csv, os, re
from collections import Counter, defaultdict

SRC = os.path.expanduser(
    "~/external_benchmark_runs/metlinkr_dev_rerun_20260722/metlinkr-comets_CHEBI_MAPPED.tsv")
_NULL = frozenset({"", "na", "nan", "none", "null"})


def clean(v):
    s = "" if v is None else str(v).strip()
    return "" if s.lower() in _NULL else s


def norm_hmdb(v):
    d = "".join(c for c in v if c.isdigit())
    return "HMDB" + d.zfill(7) if d else ""


def norm_pc(v):
    v = clean(v)
    if v.endswith(".0"):
        v = v[:-2]
    return v if v.isdigit() else ""


rows = list(csv.DictReader(open(SRC, encoding="utf-8"), delimiter="\t"))
print(f"COMETS rows: {len(rows)}")
print(f"source datasets: {sorted({clean(r['source_file']) for r in rows if clean(r['source_file'])})}")
print()

groups = defaultdict(list)
for r in rows:
    g = clean(r["curator_group_label"])
    if g:
        groups[g].append(r)

multi = {g: m for g, m in groups.items()
         if len({clean(x["source_file"]) for x in m if clean(x["source_file"])}) > 1}
print(f"curator groups                        : {len(groups)}")
print(f"  spanning >1 source dataset          : {len(multi)}")
print()

tally = Counter()
conflicts = []
for g, members in multi.items():
    per_ns = {"hmdb": set(), "pubchem": set()}
    for m in members:
        for part in re.split(r"[|;,]", clean(m["curator_hmdb"])):
            v = norm_hmdb(clean(part))
            if v:
                per_ns["hmdb"].add(v)
        for part in re.split(r"[|;,]", clean(m["curator_pubchem"])):
            v = norm_pc(part)
            if v:
                per_ns["pubchem"].add(v)
    testable = [ns for ns, s in per_ns.items() if len(s) >= 1]
    if not testable:
        tally["no_ids"] += 1
        continue
    disagree = [ns for ns, s in per_ns.items() if len(s) > 1]
    if disagree:
        tally["CONFLICT"] += 1
        conflicts.append((g, members, {ns: sorted(per_ns[ns]) for ns in disagree}))
    else:
        tally["consistent"] += 1

print("Within-group identifier agreement across independently curated datasets:")
for k in ("consistent", "CONFLICT", "no_ids"):
    print(f"  {k:14s} {tally[k]:5d}")
testable = tally["consistent"] + tally["CONFLICT"]
if testable:
    print(f"\n  testable groups (>=1 id present)     : {testable}")
    print(f"  groups where the datasets DISAGREE   : {tally['CONFLICT']} "
          f"({tally['CONFLICT']/testable:.1%})")
    print(f"  NECS/Metabolon single-panel base rate : 1.6%")

print("\n  examples (same molecule per the curators, different identifier per the datasets):")
for g, members, d in conflicts[:14]:
    names = sorted({clean(m["metabolite_name"])[:26] for m in members})
    srcs = sorted({clean(m["source_file"]).replace("inputs_", "")[:14] for m in members})
    print(f"    {g[:30]:32s} {str(d)[:58]:60s}")
    print(f"      names={names[:3]}  datasets={srcs}")
