"""Certificate adjudication with examples, per group per pair -> certificate_adjudication.json.

For each cross-cohort group (overlap / biomapper_only / monti_only) run the KG-INDEPENDENT structure
certificate on each NECS metabolite vs the cohort partner(s) it links to, and record certified / refuted
/ refused counts plus concrete examples — including the REFUTED overlap cases (both methods agree yet the
independent structures disagree: a correlated error). # pragma: no cover (analysis/reporting).
"""

from __future__ import annotations

import csv
import json
import re
import os
from collections import defaultdict
from pathlib import Path

from studies.external_benchmarks.scorers.cross_cohort_overlap import curie_set

RUN = Path(os.environ["AB_RUN_DIR"]).expanduser() if os.environ.get("AB_RUN_DIR") else None  # main() requires it; import stays safe for pure-helper tests
PAIRS = ("arivale", "xuetal")


def _res(label):
    out = {}
    for x in (RUN / f"treatment__{label}_devapi.jsonl").open():
        r = json.loads(x)
        out[r["name"]] = curie_set(r["chosen_kg_id"], r["kg_equivalent_ids"])
    return out


def _blk(tag):
    out = {}
    p = RUN / f"oracle_provided_{tag}.jsonl"
    if p.exists():
        for x in p.open():
            r = json.loads(x)
            out[r["name"]] = r["block"]
    return out


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


# A sum-composition ("species-level") lipid carries a C:U token (e.g. 34:1). These are isobaric mixtures
# with no unique structure, so the independent-structure certificate cannot verify them (they land in
# `refused`) — reported as a labeled sub-category, name-harmonized only, NOT independently verifiable.
_SUM_COMPOSITION = re.compile(r"(?<![.\d])\d{1,3}:\d{1,2}(?![.\d])")


def is_species_level_lipid(name: str) -> bool:
    """True when the name is a sum-composition / species-level lipid shorthand (has a C:U token)."""
    return bool(_SUM_COMPOSITION.search(name or ""))


def main():  # pragma: no cover
    refmet = _refmet()
    out = {}
    for cohort in PAIRS:
        nc, cc = _res("necs"), _res(cohort)
        nblk, cblk = _blk(f"{cohort}_necs"), _blk(f"{cohort}_coh")
        coh_by_curie, coh_by_refmet, coh_by_name, coh_by_block = (defaultdict(set) for _ in range(4))
        for c in cc:
            for cu in cc[c]:
                coh_by_curie[cu].add(c)
            rm = refmet.get(c.strip().lower(), "")
            if rm:
                coh_by_refmet[rm].add(c)
            coh_by_name[c.strip().lower()].add(c)
            if cblk.get(c):
                coh_by_block[cblk[c]].add(c)

        groups = {g: {"certified": [], "refuted": [], "refused": []} for g in ("overlap", "biomapper_only", "monti_only")}
        for n in nc:
            nn, gb = n.strip().lower(), nblk.get(n)
            if not (coh_by_name.get(nn) or (gb and coh_by_block.get(gb))):
                continue
            bm = {c for cu in nc[n] for c in coh_by_curie.get(cu, set())}
            rm = refmet.get(nn, "")
            mo = coh_by_refmet.get(rm, set()) if rm else set()
            if bm and mo:
                grp, part = "overlap", bm | mo
            elif bm:
                grp, part = "biomapper_only", bm
            elif mo:
                grp, part = "monti_only", mo
            else:
                continue
            pblocks = [(p, cblk.get(p)) for p in part if cblk.get(p)]
            if not gb or not pblocks:
                verdict, ex = "refused", {"name": n}
            elif any(gb == b for _, b in pblocks):
                verdict, ex = "certified", {"name": n, "necs_block": gb, "partner": next(p for p, b in pblocks if b == gb)}
            else:
                p0, b0 = pblocks[0]
                verdict, ex = "refuted", {"name": n, "necs_block": gb, "partner": p0, "partner_block": b0}
            groups[grp][verdict].append(ex)

        out[cohort] = {
            "pair": f"necs<->{cohort}",
            "counts": {g: {v: len(groups[g][v]) for v in groups[g]} for g in groups},
            # honest sub-label: of the refused, how many are species-level lipids (name-harmonized only,
            # not independently verifiable) vs other refused. NOT a positive "certified/harmonized" count.
            "refused_species_lipid": {g: sum(1 for e in groups[g]["refused"] if is_species_level_lipid(e["name"])) for g in groups},
            "examples": {g: {v: groups[g][v][:6] for v in groups[g]} for g in groups},
        }
    (RUN / "certificate_adjudication.json").write_text(json.dumps(out, indent=2))
    for c, r in out.items():
        print(f"{r['pair']}: " + " | ".join(f"{g}:{r['counts'][g]}" for g in r["counts"]))
    print(f"[done] {RUN}/certificate_adjudication.json")


if __name__ == "__main__":  # pragma: no cover
    main()
