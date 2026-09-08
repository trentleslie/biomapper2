"""Certificate-gated RefMet-name bridge — D2 re-resolution prototype (offline; # pragma: no cover).

BioMapper links two cohort names when they share a KG CURIE. This bridge ADDS a link when they share a
RefMet standardized name but NOT a CURIE (the Monti-only cases), GATED by the KG-independent structure
certificate: adopt only CERTIFIED bridge links (structures agree), REJECT refuted ones (Monti's errors),
hold REFUSED ones (no independent structure -> the lipid-oracle frontier). Quantifies, per pair:

  biomapper_harmonized      - NECS metabolites BioMapper links to the cohort (baseline)
  bridge_certified (+gain)  - additional correct links the gated bridge adds
  bridge_refuted (rejected) - Monti-only links the gate correctly refuses (errors NOT imported)
  bridge_refused (pending)  - unverifiable (need structure; the ceiling frontier)

Writes refmet_bridge.json. Consumes only the ab_lipid_oracle run caches + the RefMet map.
"""

from __future__ import annotations

import csv
import json
import os
from collections import defaultdict
from pathlib import Path

from studies.external_benchmarks.scorers.cross_cohort_overlap import curie_set

RUN = Path(os.environ["AB_RUN_DIR"]).expanduser()
PAIRS = ("arivale", "xuetal")


def _res(label):
    return {json.loads(x)["name"]: curie_set(json.loads(x)["chosen_kg_id"], json.loads(x)["kg_equivalent_ids"])
            for x in (RUN / f"treatment__{label}_devapi.jsonl").open()}


def _blk(tag):
    d = {}
    p = RUN / f"oracle_provided_{tag}.jsonl"
    if p.exists():
        for x in p.open():
            r = json.loads(x)
            d[r["name"]] = r["block"]
    return d


def _refmet():
    m = {}
    for line in Path(os.environ["REFMET_CACHE"]).open():
        p = line.rstrip("\n").split("\t")
        if len(p) == 2 and p[0].strip().lower() != "input":
            m[p[0].strip().lower()] = p[1].strip()
    for r in csv.DictReader(Path(os.environ["NECS_GOLD_TSV"]).open(), delimiter="\t"):
        rm = (r.get("gold_refmet") or "").strip()
        if rm and r["chemical_name"].strip().lower() not in m:
            m[r["chemical_name"].strip().lower()] = rm
    return m


def main():  # pragma: no cover
    refmet = _refmet()
    out = {}
    for cohort in PAIRS:
        nc, cc = _res("necs"), _res(cohort)
        nblk, cblk = _blk(f"{cohort}_necs"), _blk(f"{cohort}_coh")
        coh_by_curie, coh_by_refmet = defaultdict(set), defaultdict(set)
        for c in cc:
            for cu in cc[c]:
                coh_by_curie[cu].add(c)
            rm = refmet.get(c.strip().lower(), "")
            if rm:
                coh_by_refmet[rm].add(c)

        bm_harmonized = 0
        gate = {"certified": [], "refuted": [], "refused": []}
        for n in nc:
            nn = n.strip().lower()
            bm = {c for cu in nc[n] for c in coh_by_curie.get(cu, set())}
            if bm:
                bm_harmonized += 1
                continue  # BioMapper already links it — not a bridge candidate
            rm = refmet.get(nn, "")
            bridge = coh_by_refmet.get(rm, set()) if rm else set()
            if not bridge:
                continue  # neither CURIE nor RefMet bridge -> nothing to add
            gb = nblk.get(n)
            pblocks = [cblk.get(p) for p in bridge if cblk.get(p)]
            if not gb or not pblocks:
                gate["refused"].append(n)
            elif any(gb == b for b in pblocks):
                gate["certified"].append(n)
            else:
                gate["refuted"].append(n)

        c, r, u = len(gate["certified"]), len(gate["refuted"]), len(gate["refused"])
        out[cohort] = {
            "pair": f"necs<->{cohort}",
            "biomapper_harmonized": bm_harmonized,
            "bridge_certified_gain": c,
            "bridge_refuted_rejected": r,
            "bridge_refused_pending": u,
            "harmonized_after_gated_bridge": bm_harmonized + c,
            "gain_pct": round(100 * c / bm_harmonized, 2) if bm_harmonized else None,
            "errors_rejected_pct": round(100 * r / (r + c), 1) if (r + c) else None,
            "examples_added": sorted(gate["certified"])[:10],
            "examples_rejected": sorted(gate["refuted"])[:10],
        }
    (RUN / "refmet_bridge.json").write_text(json.dumps(out, indent=2))
    for _, o in out.items():
        print(f"\n=== {o['pair']} ===")
        print(f"  BioMapper baseline harmonized : {o['biomapper_harmonized']}")
        print(f"  + gated RefMet bridge (certified): +{o['bridge_certified_gain']}  -> {o['harmonized_after_gated_bridge']} ({o['gain_pct']}% gain)")
        print(f"  gate REJECTED (Monti errors avoided): {o['bridge_refuted_rejected']}")
        print(f"  pending (no structure -> oracle frontier): {o['bridge_refused_pending']}")
        print(f"  added examples: {o['examples_added'][:6]}")
    print(f"\n[done] {RUN}/refmet_bridge.json")


if __name__ == "__main__":  # pragma: no cover
    main()
