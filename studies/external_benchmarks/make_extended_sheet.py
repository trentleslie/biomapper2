"""Assemble the extended-provenance workbook (TSV per tab) from a completed ab_lipid_oracle run.

Same tab structure as the first mappings sheet, but richer columns: Kraken node identifiers
(chosen_kg_id + per-namespace kg_equivalent_ids), Metabolomics Workbench / RefMet results, full
structure provenance (gold InChIKey/SMILES/HMDB/PubChem/KEGG/CAS), the independent oracle block, and the
three-group membership + certificate adjudication. # pragma: no cover (assembly/reporting).
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

from studies.external_benchmarks.scorers.cross_cohort_overlap import curie_set

RUN = Path(os.environ["AB_RUN_DIR"]).expanduser()
GOLD_TSV = Path(os.environ["NECS_GOLD_TSV"]).expanduser()
REFMET_CACHE = Path(os.environ["REFMET_CACHE"]).expanduser()
OUT = RUN / "extended_sheet"
NS = ("CHEBI", "HMDB", "RM", "PUBCHEM.COMPOUND", "CAS", "KEGG.COMPOUND", "CHEMBL.COMPOUND", "LM", "UNII", "INCHIKEY")


def _load_resolution(label):
    out = {}
    for line in (RUN / f"treatment__{label}_devapi.jsonl").open():
        r = json.loads(line)
        out[r["name"]] = r
    return out


def _load_blocks(tag):
    out = {}
    p = RUN / f"oracle_provided_{tag}.jsonl"
    if p.exists():
        for line in p.open():
            r = json.loads(line)
            out[r["name"]] = r
    return out


def _gold():
    out = {}
    for row in csv.DictReader(GOLD_TSV.open(), delimiter="\t"):
        out[row["chemical_name"].strip().lower()] = row
    return out


def _refmet(gold):
    m = {}
    for line in REFMET_CACHE.open():
        p = line.rstrip("\n").split("\t")
        if len(p) == 2 and p[0].strip().lower() != "input":
            m[p[0].strip().lower()] = p[1].strip()
    for k, row in gold.items():
        rm = (row.get("gold_refmet") or "").strip()
        if rm and k not in m:
            m[k] = rm
    return m


def _kg_cols(rec, gold_row):
    eq = rec.get("kg_equivalent_ids") or {}
    cols = {"chosen_kg_id": rec.get("chosen_kg_id") or "", "chosen_kg_id_review": rec.get("chosen_kg_id_review") or ""}
    for ns in NS:
        cols[f"kg_{ns}"] = ";".join((eq.get(ns) or [])[:6])
    return cols


def main():  # pragma: no cover
    OUT.mkdir(parents=True, exist_ok=True)
    gold, tg = _gold(), json.loads((RUN / "three_groups.json").read_text())
    refmet = _refmet(gold)

    # --- Tab 1: raw mappings (one row per name per cohort, full provenance) ---
    raw_hdr = ["cohort", "name", "chosen_kg_id", "chosen_kg_id_review"] + [f"kg_{n}" for n in NS] + [
        "mw_refmet_name", "gold_refmet", "gold_inchikey", "gold_smiles", "gold_hmdb", "gold_pubchem",
        "gold_kegg", "gold_cas", "has_gold_structure", "provided_ids", "independent_block", "independent_source"]
    with (OUT / "1_raw_mappings.tsv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=raw_hdr, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for cohort in ("necs", "arivale", "xuetal"):
            res = _load_resolution(cohort)
            blk = _load_blocks(f"arivale_{'necs' if cohort=='necs' else 'coh'}") if cohort in ("necs", "arivale") else {}
            xblk = _load_blocks("xuetal_coh") if cohort == "xuetal" else {}
            nblk = _load_blocks("xuetal_necs") if cohort == "necs" else {}
            for name, rec in res.items():
                g = gold.get(name.strip().lower(), {})
                b = blk.get(name) or xblk.get(name) or nblk.get(name) or {}
                row = {"cohort": cohort, "name": name, "mw_refmet_name": refmet.get(name.strip().lower(), ""),
                       "gold_refmet": g.get("gold_refmet", ""), "gold_inchikey": g.get("gold_inchikey", ""),
                       "gold_smiles": g.get("gold_smiles", ""), "gold_hmdb": g.get("gold_hmdb", ""),
                       "gold_pubchem": g.get("gold_pubchem", ""), "gold_kegg": g.get("gold_kegg", ""),
                       "gold_cas": g.get("gold_cas", ""), "has_gold_structure": g.get("has_gold_structure", ""),
                       "provided_ids": g.get("provided_ids", ""), "independent_block": b.get("block") or "",
                       "independent_source": b.get("source") or ""}
                row.update(_kg_cols(rec, g))
                w.writerow(row)

    # --- Tab 2: overlaps (three-group membership per NECS metabolite per pair) ---
    with (OUT / "2_overlaps.tsv").open("w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["pair", "group", "necs_metabolite", "mw_refmet_name", "necs_chosen_kg_id", "necs_independent_block"])
        for cohort, r in tg.items():
            pair = r["pair"]
            necs_res = _load_resolution("necs")
            nblk = _load_blocks(f"{cohort}_necs")
            for group, names in r["members"].items():
                for n in names:
                    w.writerow([pair, group, n, refmet.get(n.strip().lower(), ""),
                                (necs_res.get(n) or {}).get("chosen_kg_id", ""), (nblk.get(n) or {}).get("block", "")])

    # --- Tab 3: disparity characterization (counts + adjudication per pair) ---
    with (OUT / "3_disparity.tsv").open("w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["pair", "universe_present_in_both", "overlap", "biomapper_only", "monti_only", "neither",
                    "panel_total", "harmonized_either", "ceiling_neither", "ceiling_pct",
                    "bm_only_correct", "bm_only_wrong", "monti_only_correct", "monti_only_wrong"])
        for cohort, r in tg.items():
            c, cov, a = r["counts"], r["panel_coverage"], r["adjudication"]
            w.writerow([r["pair"], r["universe_present_in_both"], c["overlap"], c["biomapper_only"], c["monti_only"],
                        c["neither"], cov["panel_total"], cov["either"], cov["neither"],
                        f'{100*cov["neither"]/cov["panel_total"]:.1f}%', a["biomapper_only_correct"],
                        a["biomapper_only_wrong"], a["monti_only_correct"], a["monti_only_wrong"]])

    # --- Tab 4: column definitions ---
    defs = [
        ("cohort", "Source cohort panel (necs / arivale / xuetal)."),
        ("name", "Metabolite name as published by the cohort (Metabolon nomenclature)."),
        ("chosen_kg_id", "KRAKEN node BioMapper committed for this name (the resolved KG identifier)."),
        ("chosen_kg_id_review", "Resolver review flag on the committed node, if any."),
        ("kg_<NS>", "Kraken node's equivalent identifiers in namespace NS (CHEBI/HMDB/RM/PUBCHEM/CAS/KEGG/CHEMBL/LM/UNII/INCHIKEY); up to 6 shown."),
        ("mw_refmet_name", "Metabolomics Workbench RefMet standardized name (the Monti/Arm-B linking key)."),
        ("gold_refmet", "Curator-provided RefMet name from the source workbook."),
        ("gold_inchikey / gold_smiles", "Curator gold structure (independent of the KG)."),
        ("gold_hmdb / gold_pubchem / gold_kegg / gold_cas", "Curator cross-reference identifiers (the provided-id oracle inputs)."),
        ("has_gold_structure", "Whether a gold structure is present for this name."),
        ("provided_ids", "The ids actually handed to BioMapper (RefMet + CHEBI) — distinct from the oracle's hmdb/pubchem (disjointness)."),
        ("independent_block / independent_source", "InChIKey first-block resolved by the KG-independent oracle, and its provenance tag."),
        ("group", "overlap = both Monti & BioMapper link; biomapper_only / monti_only = one; neither = performance-ceiling headroom."),
        ("harmonized_either / ceiling_neither", "Panel coverage: metabolites harmonized to NECS by either method vs by neither (the ceiling)."),
        ("bm_only_correct/wrong, monti_only_correct/wrong", "Discrepancy adjudicated by the independent structure (block match)."),
    ]
    with (OUT / "4_column_definitions.tsv").open("w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["column", "definition"])
        w.writerows(defs)

    # --- Tab 5: provenance notes ---
    notes = [
        ("run_dir", RUN.name),
        ("kg_build", "Kestrel v2.1.0 / kg2 2.10.2 / RefMet+LIPIDMAPS accessed_2026-08-07 (public krakenkg.com)"),
        ("biomapper_resolution", "treatment arm = Kestrel category/prefix fix (PR #64); name-only (Arm M), NOT fed the oracle's hmdb/pubchem"),
        ("monti_arm", "Arm-B replication: shared RefMet-standardized name (Metabolomics Workbench)"),
        ("independent_oracle", "provided HMDB/PubChem/gold-InChIKey -> PubChem PUG-REST; KG-independent (biomapper resolves via name/RM/CHEBI)"),
        ("gold_source", GOLD_TSV.name),
        ("refmet_source", REFMET_CACHE.name),
        ("caveat", "kg_<NS> capped at 6 ids/namespace; full kg_ids + resolution_certificate require a re-query (not in this sheet)"),
        ("api_key", "NOT recorded in any artifact; internal endpoints omitted"),
    ]
    with (OUT / "5_provenance_notes.tsv").open("w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["key", "value"])
        w.writerows(notes)

    for f in sorted(OUT.glob("*.tsv")):
        print(f"  {f.name}: {sum(1 for _ in f.open())-1} rows")
    print(f"[done] {OUT}")


if __name__ == "__main__":  # pragma: no cover
    main()
