"""STEP 1 GATE for the cross-cohort harmonization benchmark: is the NECS <-> LLFS recall arm viable?

The design (docs/superpowers/specs/2026-08-04-cross-cohort-harmonization-benchmark-design.md)
adjudicates links by structure only. BLSA failed this gate: 81% of its panel is sum-composition
lipid species that no structural oracle can resolve, capping its adjudicable subset at 93 analytes.

This asks the same three questions of LLFS:

  1. COMPOSITION   how many of the 408 are discrete molecules vs sum-composition lipid species?
  2. REPRODUCTION  does Monti's method (RefMet standardized-name join) reproduce their reported 163?
  3. ADJUDICABLE   of the pairs their method finds, how many could a structural oracle ever judge?

Question 3 is the gate. If it resembles BLSA's ratio, the recall claim needs a different
adjudication standard, a different partner, or a narrower claim, and we want to know that before
writing any benchmark code.

NETWORK: question 2 needs the Metabolomics Workbench RefMet name service, because neither panel
ships RefMet names for the NECS side (NECS's ``gold_refmet`` column is a boolean presence flag, not
a name). Responses are cached to disk so a re-run costs nothing. IPv4 is forced: this host's IPv6
route to several CDNs is dead and Python hangs in SYN-SENT where curl survives via happy-eyeballs.
"""

from __future__ import annotations

import csv
import json
import os
import re
import socket
import urllib.request
from collections import Counter
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
LLFS_XLSX = REPO / "data" / "NIHMS2038904-supplement-2.xlsx"
NECS_TSV = Path(os.path.expanduser(
    "~/external_benchmark_runs/scorer_rerun_20260723/necs/necs-metabolon_CHEBI_MAPPED.tsv"))
OUT = Path(os.path.expanduser("~/external_benchmark_runs/cohort_panels_20260804"))
CACHE = OUT / "necs_refmet_convert_cache.tsv"

MONTI_REPORTED_OVERLAP = 163  # "NECS with LLFS ... yielded an overlap of 163" (Monti et al. 2026)
REFMET_BULK = "https://www.metabolomicsworkbench.org/databases/refmet/name_to_refmet_new_min.php"
BATCH = 250

# Sentinels either panel uses for "no value". LLFS writes an unmapped RefMet name as "-", which is
# NOT a name; treating it as one would silently join every unmapped LLFS row to every unmapped
# NECS row.
_NULL = frozenset({"", "-", "na", "nan", "none", "null"})

# A sum-composition lipid species names a SET of molecules (chain notation such as 34:1,
# d18:1/20:0, O-36:4), so it has no unique structure and no structural oracle can adjudicate it.
CHAIN = re.compile(r"\b[dtOP]?-?\d{1,2}:\d{1,2}\b")


def clean(v) -> str:
    s = "" if v is None else str(v).strip()
    return "" if s.lower() in _NULL else s


def force_ipv4() -> None:
    real = socket.getaddrinfo

    def ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
        return real(host, port, socket.AF_INET, type, proto, flags)

    socket.getaddrinfo = ipv4_only  # type: ignore[assignment]


def refmet_convert(names: list[str]) -> dict[str, str]:
    """Map input name -> RefMet standardized name via the bulk service, cached on disk.

    This is the same service Monti's ``RC$refmet_convert`` wraps: the response columns are exactly
    the ones their published ``annotation`` sheet carries. An unmapped name yields "-" upstream and
    is normalized to "" here, matching their ``drop_na(refmet_name)``.
    """
    cached: dict[str, str] = {}
    if CACHE.exists():
        with open(CACHE, encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                cached[row["input"]] = row["refmet"]
    todo = [n for n in dict.fromkeys(names) if n and n not in cached]
    if todo:
        force_ipv4()
        print(f"  RefMet: converting {len(todo)} uncached names in batches of {BATCH}...", flush=True)
        for i in range(0, len(todo), BATCH):
            chunk = todo[i:i + BATCH]
            body = ("\n".join(chunk)).encode("utf-8")
            # multipart/form-data with a single field, matching the service's HTML form
            boundary = "----refmetbatch"
            payload = (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"metabolite_name\"\r\n\r\n"
            ).encode() + body + f"\r\n--{boundary}--\r\n".encode()
            req = urllib.request.Request(
                REFMET_BULK, data=payload,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
            with urllib.request.urlopen(req, timeout=180) as resp:
                text = resp.read().decode("utf-8", errors="replace")
            lines = [ln for ln in text.splitlines() if ln.strip()]
            got = 0
            for ln in lines[1:]:  # first line is the header
                parts = ln.split("\t")
                if len(parts) >= 2:
                    cached[parts[0].strip()] = clean(parts[1])
                    got += 1
            print(f"    batch {i//BATCH + 1}: sent {len(chunk)}, parsed {got}", flush=True)
        with open(CACHE, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["input", "refmet"], delimiter="\t")
            w.writeheader()
            for k, v in cached.items():
                w.writerow({"input": k, "refmet": v})
    return cached


def necs_has_structure(r: dict) -> bool:
    """NECS row carries a usable gold InChIKey. Accepts BOTH the legacy two-block and the standard
    three-block forms (a repaired gold carries three-block keys) — see scorers.gold_structure."""
    from studies.external_benchmarks.scorers.gold_structure import has_gold_structure
    return has_gold_structure(r.get("gold_inchikey"))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    x = pd.ExcelFile(LLFS_XLSX)
    ann = x.parse("annotation").fillna("")
    assert len(ann) == 408, f"expected Monti's 408 LLFS metabolites, got {len(ann)}"
    ann["name"] = ann["Compound.Name"].map(clean)
    ann["refmet"] = ann["Standardized names (RefMet)"].map(clean)
    ann["main_class"] = ann["Main.class"].map(clean)
    ann["sum_comp"] = [bool(CHAIN.search(n)) for n in ann["name"]]

    # ---- 1. composition -------------------------------------------------------------------------
    n_sum = int(ann["sum_comp"].sum())
    print(f"LLFS panel: {len(ann)} metabolites   (Monti states 188 lipid / 220 polar)")
    print(f"  sum-composition lipid species : {n_sum:4d}  ({n_sum/len(ann):.0%})")
    print(f"  discrete molecules            : {len(ann)-n_sum:4d}  ({(len(ann)-n_sum)/len(ann):.0%})")
    print("  top sum-composition classes:", ", ".join(
        f"{k}={v}" for k, v in Counter(ann.loc[ann.sum_comp, "main_class"]).most_common(5)))
    print()

    # ---- 2. reproduce Monti's 163 ---------------------------------------------------------------
    necs = list(csv.DictReader(open(NECS_TSV, encoding="utf-8"), delimiter="\t"))
    necs_names = [(r.get("chemical_name") or "").strip() for r in necs]
    conv = refmet_convert([n for n in necs_names if n])

    necs_by_refmet: dict[str, list[dict]] = {}
    for r, nm in zip(necs, necs_names):
        rm = clean(conv.get(nm, ""))
        if rm:
            necs_by_refmet.setdefault(rm.lower(), []).append(r)
    llfs_by_refmet: dict[str, list] = {}
    for _, r in ann.iterrows():
        if r["refmet"]:
            llfs_by_refmet.setdefault(r["refmet"].lower(), []).append(r)

    print("RefMet standardized-name coverage")
    print(f"  LLFS with a RefMet name : {len(ann[ann.refmet != '']):4d} of {len(ann)}"
          f"   ({len(ann[ann.refmet != ''])/len(ann):.0%})")
    n_necs_rm = sum(1 for n in necs_names if n and clean(conv.get(n, "")))
    print(f"  NECS with a RefMet name : {n_necs_rm:4d} of {len(necs)}   ({n_necs_rm/len(necs):.0%})")
    shared = sorted(set(necs_by_refmet) & set(llfs_by_refmet))
    print(f"  shared RefMet names     : {len(shared):4d}   (Monti reports {MONTI_REPORTED_OVERLAP},"
          f" delta {len(shared)-MONTI_REPORTED_OVERLAP:+d})")
    print()

    if not shared:
        raise SystemExit("no shared RefMet names: the reproduction failed, refusing to report a gate.")

    # ---- 3. THE GATE ----------------------------------------------------------------------------
    counts = Counter()
    rows = []
    for key in shared:
        lr = llfs_by_refmet[key][0]
        nrs = necs_by_refmet[key]
        llfs_ok = not lr["sum_comp"]
        necs_ok = any(necs_has_structure(r) for r in nrs)
        verdict = ("adjudicable" if (llfs_ok and necs_ok)
                   else "blocked_both" if (not llfs_ok and not necs_ok)
                   else "blocked_llfs_sum_composition" if not llfs_ok
                   else "blocked_necs_no_structure")
        counts[verdict] += 1
        rows.append({"refmet": key, "llfs_name": lr["name"],
                     "necs_name": (nrs[0].get("chemical_name") or "").strip(),
                     "llfs_sum_composition": not llfs_ok, "necs_has_structure": necs_ok,
                     "verdict": verdict})

    adj = counts["adjudicable"]
    print("GATE: of the overlapping pairs their method finds, how many can structure adjudicate?")
    for k in ("adjudicable", "blocked_llfs_sum_composition", "blocked_necs_no_structure", "blocked_both"):
        print(f"  {k:32s} {counts[k]:4d}  ({counts[k]/len(shared):.0%})")
    print(f"\n  BLSA comparison: 93 of 497 analytes (19%) were discrete")
    print()
    for label, v in (("adjudicable", "adjudicable"), ("blocked by lipid", "blocked_llfs_sum_composition")):
        print(f"  sample {label} pairs:")
        for r in [r for r in rows if r["verdict"] == v][:8]:
            print(f"     {r['refmet'][:32]:34s} LLFS {r['llfs_name'][:24]:26s} NECS {r['necs_name'][:24]}")
        print()

    pd.DataFrame(rows).to_csv(OUT / "llfs_step1_overlap_triage.csv", index=False)
    (OUT / "llfs_step1_sizing.json").write_text(json.dumps({
        "llfs_n": len(ann), "llfs_sum_composition": n_sum, "llfs_discrete": len(ann) - n_sum,
        "llfs_with_refmet": int((ann.refmet != "").sum()), "necs_with_refmet": n_necs_rm,
        "refmet_overlap": len(shared), "monti_reported_overlap": MONTI_REPORTED_OVERLAP,
        "gate": dict(counts), "adjudicable": adj,
        "source_llfs": str(LLFS_XLSX), "source_necs": str(NECS_TSV), "refmet_service": REFMET_BULK,
    }, indent=2))
    print(f"saved -> {OUT}")


if __name__ == "__main__":
    main()
