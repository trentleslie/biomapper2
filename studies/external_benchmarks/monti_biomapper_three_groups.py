"""Monti-vs-BioMapper three-group characterization for a cross-cohort pair (offline; # pragma: no cover).

Compares two harmonizers over the SAME cohort panels, using the run's already-persisted resolutions:
  - Monti (Arm-B):  two names harmonize if they share a RefMet-standardized name.
  - BioMapper (Arm-M): two names harmonize if they share a KG CURIE (from the treatment resolution).

Per NECS metabolite that is TRULY present in the cohort (established INDEPENDENTLY, by a shared gold /
provided-id InChIKey block — the ceiling reference), classify into three groups:
  - OVERLAP     : both Monti and BioMapper harmonize it.
  - DISCREPANCY : exactly one does (monti_only + biomapper_only); the independent structure adjudicates.
  - NEITHER     : neither does, though gold says it is there — the PERFORMANCE CEILING (headroom).

Consumes only on-disk caches from an ab_lipid_oracle run (treatment devapi jsonl + oracle_provided jsonl)
plus the RefMet map. Writes three_groups.json. Live-free.
"""

from __future__ import annotations

import csv
import json
import os
from collections import defaultdict
from pathlib import Path

from studies.external_benchmarks.scorers.cross_cohort_overlap import curie_set

RUN = Path(os.environ["AB_RUN_DIR"]).expanduser()
GOLD_TSV = Path(os.environ["NECS_GOLD_TSV"]).expanduser()
REFMET_CACHE = Path(os.environ["REFMET_CACHE"]).expanduser()
PAIRS = ("arivale", "xuetal")


def _load_curies(label: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for line in (RUN / f"treatment__{label}_devapi.jsonl").open():
        r = json.loads(line)
        out[r["name"]] = curie_set(r["chosen_kg_id"], r["kg_equivalent_ids"])
    return out


def _load_blocks(tag: str) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    p = RUN / f"oracle_provided_{tag}.jsonl"
    if p.exists():
        for line in p.open():
            r = json.loads(line)
            out[r["name"]] = r["block"]
    return out


def _refmet_map() -> dict[str, str]:
    m: dict[str, str] = {}
    for line in REFMET_CACHE.open():
        parts = line.rstrip("\n").split("\t")
        if len(parts) == 2 and parts[0].strip().lower() != "input":
            m[parts[0].strip().lower()] = parts[1].strip()
    for row in csv.DictReader(GOLD_TSV.open(), delimiter="\t"):  # augment with necs gold_refmet
        nm, rm = row["chemical_name"].strip().lower(), (row.get("gold_refmet") or "").strip()
        if rm and nm not in m:
            m[nm] = rm
    return m


def _index(names, keyfn) -> dict[str, set[str]]:
    idx: dict[str, set[str]] = defaultdict(set)
    for n in names:
        for k in keyfn(n):
            if k:
                idx[k].add(n)
    return idx


def characterize(cohort: str, refmet: dict[str, str]) -> dict:
    necs_cur, coh_cur = _load_curies("necs"), _load_curies(cohort)
    necs_blk, coh_blk = _load_blocks(f"{cohort}_necs"), _load_blocks(f"{cohort}_coh")

    coh_by_curie = _index(coh_cur, lambda n: coh_cur.get(n, set()))
    coh_by_refmet = _index(coh_cur, lambda n: {refmet.get(n.strip().lower(), "")})
    coh_by_name: dict[str, set[str]] = defaultdict(set)
    for c in coh_cur:
        coh_by_name[c.strip().lower()].add(c)
    coh_by_block = _index([n for n in coh_cur if coh_blk.get(n)], lambda n: {coh_blk.get(n)})

    groups: dict[str, list[str]] = {"overlap": [], "biomapper_only": [], "monti_only": [], "neither": []}
    adjudication = {"biomapper_only_correct": 0, "biomapper_only_wrong": 0, "monti_only_correct": 0, "monti_only_wrong": 0}
    neither_why = {"no_independent_structure": 0, "structure_but_unlinked": 0}
    for n in necs_cur:
        n_norm = n.strip().lower()
        gblk = necs_blk.get(n)
        # Ground truth "present in both cohorts": shared exact Metabolon name (same assay platform) OR a
        # shared independent structure block. This universe INCLUDES the unresolvable lipids -> real ceiling.
        co_present = bool(coh_by_name.get(n_norm)) or bool(gblk and coh_by_block.get(gblk))
        if not co_present:
            continue
        bm = {c for cu in necs_cur[n] for c in coh_by_curie.get(cu, set())}
        n_rm = refmet.get(n_norm, "")
        mo = coh_by_refmet.get(n_rm, set()) if n_rm else set()
        has_bm, has_mo = bool(bm), bool(mo)
        if has_bm and has_mo:
            groups["overlap"].append(n)
        elif has_bm:
            groups["biomapper_only"].append(n)
            if gblk:
                ok = any(coh_blk.get(c) == gblk for c in bm)
                adjudication["biomapper_only_correct" if ok else "biomapper_only_wrong"] += 1
        elif has_mo:
            groups["monti_only"].append(n)
            if gblk:
                ok = any(coh_blk.get(c) == gblk for c in mo)
                adjudication["monti_only_correct" if ok else "monti_only_wrong"] += 1
        else:
            groups["neither"].append(n)
            neither_why["structure_but_unlinked" if gblk else "no_independent_structure"] += 1

    # Performance-ceiling view: of the FULL cohort panel, how many metabolites harmonize to NECS at all?
    # The unharmonized remainder is the headroom a perfect harmonizer would still need to close.
    necs_curies = set().union(*necs_cur.values()) if necs_cur else set()
    necs_refmets = {refmet.get(nm.strip().lower(), "") for nm in necs_cur} - {""}
    necs_by_rm: dict[str, set[str]] = defaultdict(set)
    for nm in necs_cur:
        rm = refmet.get(nm.strip().lower(), "")
        if rm:
            necs_by_rm[rm].add(nm)
    cov = {"biomapper": 0, "biomapper_bridge": 0, "monti": 0, "either": 0, "neither": 0}
    for c in coh_cur:
        bm = bool(coh_cur[c] & necs_curies)
        rm = refmet.get(c.strip().lower(), "")
        mo = bool(rm) and rm in necs_refmets
        # certificate-gated RefMet bridge: a certified structure match to some NECS metabolite of the same RefMet name
        bridge = False
        if not bm and rm and coh_blk.get(c):
            bridge = any(necs_blk.get(nm) and necs_blk[nm] == coh_blk[c] for nm in necs_by_rm.get(rm, ()))
        cov["biomapper"] += bm
        cov["biomapper_bridge"] += bm or bridge
        cov["monti"] += mo
        cov["either"] += bm or mo
        cov["neither"] += not (bm or mo)
    cov["panel_total"] = len(coh_cur)

    total = sum(len(v) for v in groups.values())
    return {
        "pair": f"necs<->{cohort}",
        "panel_coverage": cov,
        "universe_present_in_both": total,
        "counts": {k: len(v) for k, v in groups.items()},
        "discrepancy_total": len(groups["biomapper_only"]) + len(groups["monti_only"]),
        "adjudication": adjudication,
        "neither_breakdown": neither_why,
        "members": {k: sorted(v) for k, v in groups.items()},
        "examples": {k: sorted(v)[:12] for k, v in groups.items()},
    }


def main() -> None:  # pragma: no cover
    refmet = _refmet_map()
    out = {c: characterize(c, refmet) for c in PAIRS}
    (RUN / "three_groups.json").write_text(json.dumps(out, indent=2))
    for c, r in out.items():
        print(f"\n=== {r['pair']} (universe present-in-both = {r['universe_present_in_both']}) ===")
        for k, v in r["counts"].items():
            print(f"  {k:16} {v}")
        print(f"  adjudication: {r['adjudication']}")
    print(f"\n[done] {RUN}/three_groups.json")


if __name__ == "__main__":  # pragma: no cover
    main()
