"""Feasibility spike probe: can biomapper2's KG (Kestrel/SPOKE) resolve microbial
taxon identifiers and cross-walk NCBITaxon <-> GTDB / SILVA / Greengenes today?

TIME-BOXED SPIKE — measurement only, not a tier build. For each fixture pair:
  A. name -> KG anchor:  text-search(NCBI name, OrganismTaxon) returns an NCBITaxon node? (what
     the KestrelHybridSearch annotator does for name input)
  B. NCBITaxon -> node:  get-nodes(NCBITaxon:id) returns a node, and does it carry ANY GTDB/SILVA/
     GG equivalent_id (the cross-namespace bridge)?
  C. other-name -> KG:   text-search(GTDB/SILVA renamed string) resolves to a node at all?

Saves a timestamped JSON + prints a per-family summary. Reads KESTREL_API_KEY from .env.
Usage:  uv run python scripts/spike_microbiome_taxon_probe.py [--out PATH]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://kestrel.nathanpricelab.com/api"
FIXTURES = ROOT / "tests" / "fixtures" / "microbiome_taxon_pairs.csv"
CROSS_NS = re.compile(r"^(GTDB|SILVA|GREENGENES|GG2?|LPSN|BACDIVE)", re.I)


def load_key() -> str:
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("KESTREL_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("KESTREL_API_KEY not found in .env")


def post(sess: requests.Session, ep: str, payload: dict) -> dict:
    r = sess.post(f"{BASE}/{ep}", json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def first_node(val):
    if isinstance(val, list):
        return val[0] if val else None
    return val


def probe(sess: requests.Session, row: dict) -> dict:
    name = row["ncbi_name"]
    curie = f"NCBITaxon:{row['ncbitaxon_id']}"
    other = row["other_name"]
    out = {**row, "curie": curie}

    # A. name -> KG anchor (OrganismTaxon)
    ts = post(sess, "text-search", {"search_text": [name], "limit": 5, "category_filter": "biolink:OrganismTaxon"})
    hits = ts.get(name, []) if isinstance(ts, dict) else []
    top = hits[0] if hits else {}
    # Anchoring means the top hit is an NCBITaxon node, not merely any returned ID.
    out["A_name_resolves"] = str(top.get("id", "")).startswith("NCBITaxon:")
    out["A_top_id"] = top.get("id")
    out["A_top_name"] = top.get("name")

    # B. NCBITaxon id -> node + cross-namespace equivalents
    gn = post(sess, "get-nodes", {"curies": [curie], "slim": False, "truncate_long_fields": False})
    node = first_node(gn.get(curie)) or first_node(next(iter(gn.values()), None)) if gn else None
    out["B_node_exists"] = bool(node)
    eqs = (node or {}).get("equivalent_ids") or []
    out["B_equivalent_ids"] = eqs
    out["B_cross_ns_equivalents"] = [e for e in eqs if CROSS_NS.match(str(e))]
    out["B_bridge_ok"] = bool(out["B_cross_ns_equivalents"])

    # C. GTDB/SILVA renamed string -> any KG node
    label = other.replace("s__", "").strip()
    tsc = post(sess, "text-search", {"search_text": [label], "limit": 5, "category_filter": "biolink:OrganismTaxon"})
    chits = tsc.get(label, []) if isinstance(tsc, dict) else []
    ctop = chits[0] if chits else {}
    out["C_other_name_resolves"] = bool(chits)
    out["C_top_id"] = ctop.get("id")
    out["C_top_name"] = ctop.get("name")
    # accidental cross-walk: GTDB name lands on the SAME NCBITaxon anchor as the NCBI name
    out["C_same_anchor_as_A"] = bool(ctop.get("id")) and ctop.get("id") == out["A_top_id"]
    return out


def summarize(rows: list[dict]) -> dict:
    fams: dict[str, dict] = {}
    for r in rows:
        f = fams.setdefault(r["family"], {"n": 0, "A": 0, "B_node": 0, "B_bridge": 0, "C": 0, "C_same": 0})
        f["n"] += 1
        f["A"] += int(r["A_name_resolves"])
        f["B_node"] += int(r["B_node_exists"])
        f["B_bridge"] += int(r["B_bridge_ok"])
        f["C"] += int(r["C_other_name_resolves"])
        f["C_same"] += int(r["C_same_anchor_as_A"])
    return fams


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    key = load_key()
    sess = requests.Session()
    sess.headers.update({"X-API-Key": key, "Content-Type": "application/json"})

    with FIXTURES.open() as fh:
        rows = list(csv.DictReader(fh))

    results = [probe(sess, r) for r in rows]
    fams = summarize(results)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = args.out or (ROOT / "data" / "review" / f"microbiome_taxon_spike_{ts}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"generated_utc": ts, "summary": fams, "results": results}, indent=2))

    print(f"\n=== biomapper2 microbiome taxon feasibility probe ({ts}) ===")
    for fam, s in fams.items():
        n = s["n"]
        print(f"\n[{fam}]  n={n}")
        print(f"  A NCBI-name -> KG OrganismTaxon node : {s['A']}/{n}  ({100*s['A']//n}%)")
        print(f"  B NCBITaxon id -> KG node exists     : {s['B_node']}/{n}  ({100*s['B_node']//n}%)")
        print(
            f"  B node carries GTDB/SILVA/GG equiv   : {s['B_bridge']}/{n}  ({100*s['B_bridge']//n}%)  <-- cross-namespace bridge"
        )  # noqa: E501
        print(f"  C other-system name -> any KG node   : {s['C']}/{n}  ({100*s['C']//n}%)")
        print(f"  C  ...lands on SAME anchor as NCBI   : {s['C_same']}/{n}  ({100*s['C_same']//n}%)")
    print(f"\nsaved -> {out}")


if __name__ == "__main__":
    main()
