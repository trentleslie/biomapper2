"""Unit 4 (live driver) — resolve the cohort panels through BioMapper and score Arm-M overlap.

Names-only (Arm M): each panel's names are run through ``Mapper.map_dataset_to_kg`` against public
Kraken 2.1.0, the full mapped TSV is persisted per panel (so a mid-run 5xx loses nothing), and the
identifier-only CURIE sets are intersected NECS↔cohort to give the Arm-M overlap. The result is
compared to the locked Arm-B baseline (Monti's method) per pair.

This is the SUPERVISED, gated live step: it is only invoked explicitly (``python -m
studies.external_benchmarks.cross_cohort_run``); nothing here runs inside an automated tail. The
manifest pins the deployment URL, the ``/metagraph`` fingerprint, source versions, source SHAs, and
the repo commit (R23). Structure certification is NOT run here (coverage-first).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from .adapters.cohort_panel import ARIVALE, SPREADSHEET_COHORTS, load_cohort_panel
from .scorers.arm_b_baseline import arm_b_overlap
from .scorers.cross_cohort_overlap import link_by_intersection, row_curie_set

SPREADSHEET = Path.home() / ".claude/uploads/2390692a-d27f-5fa2-bb74-9b032f2d5009/99293a9b-datasets_metabolites.xlsx"
ARIVALE_XLSX = Path.home() / "external_benchmark_runs/arivale_public_panel_20260804/watanabe2023_supp_data2_analytes.xlsx"
REFMET_CACHE = Path.home() / "external_benchmark_runs/cohort_panels_20260804/necs_refmet_convert_cache.tsv"
COHORTS = ("arivale", "xuetal", "llfs", "blsa")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10
        ).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def load_panels() -> dict[str, list[str]]:
    ss = pd.read_excel(SPREADSHEET, sheet_name="Sheet 1", dtype=str).fillna("")
    panels = {k: load_cohort_panel(ss, SPREADSHEET_COHORTS[k]).names for k in ("necs", "xuetal", "llfs", "blsa")}
    ar = pd.read_excel(ARIVALE_XLSX, sheet_name="Arivale_Metabolomics", dtype=str).fillna("")
    panels["arivale"] = load_cohort_panel(ar, ARIVALE).names
    return panels


def resolve_panel(mapper: Any, names: list[str], out_dir: Path, label: str) -> dict[str, frozenset[str]]:
    """Run one panel name-only through BioMapper; persist the mapped TSV; return {name: curie_set}."""
    df = pd.DataFrame({"name": names})
    out_tsv, stats = mapper.map_dataset_to_kg(
        dataset=df, entity_type="metabolite", name_column="name",
        provided_id_columns=[], vocab="CHEBI", annotation_mode="all",
    )
    dest = out_dir / f"{label}_mapped.tsv"
    res = pd.read_csv(out_tsv, sep="\t", dtype=str).fillna("")
    res.to_csv(dest, sep="\t", index=False)
    (out_dir / f"{label}_stats.json").write_text(json.dumps(stats, indent=2, default=str))
    return {r["name"]: row_curie_set(r) for _, r in res.iterrows() if str(r.get("name", "")).strip()}


def main() -> None:
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path.home() / f"external_benchmark_runs/cross_cohort_arm_m_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    import requests

    from biomapper2.config import KESTREL_API_URL
    from biomapper2.mapper import Mapper

    fingerprint = requests.get(f"{KESTREL_API_URL}/metagraph", timeout=30).json()
    print(f"[run] {out_dir}", flush=True)
    print(f"[kg] {fingerprint.get('graph')} {fingerprint.get('version')} biolink={fingerprint.get('biolink_version')}", flush=True)

    panels = load_panels()
    mapper = Mapper()

    curies: dict[str, dict[str, frozenset[str]]] = {}
    for label in ("necs", *COHORTS):
        print(f"[resolve] {label} n={len(panels[label])} ...", flush=True)
        curies[label] = resolve_panel(mapper, panels[label], out_dir, label)
        print(f"[resolve] {label} done, {sum(1 for s in curies[label].values() if s)}/{len(curies[label])} resolved", flush=True)

    # RefMet cache for the Arm-B RefMet pairs
    import csv

    rm = {r["input"]: r["refmet"] for r in csv.DictReader(REFMET_CACHE.open(), delimiter="\t")}
    necs_names = panels["necs"]

    results: dict[str, Any] = {}
    for coh in COHORTS:
        ov = link_by_intersection(curies["necs"], curies[coh])
        armb = arm_b_overlap(coh, necs_names, panels[coh], refmet_map=rm)
        results[coh] = {
            "arm_m_links": ov.n_links,
            "arm_m_necs_linked": ov.n_a_linked,
            "arm_m_cohort_linked": ov.n_b_linked,
            "necs_comparable": ov.n_a_comparable,
            "cohort_comparable": ov.n_b_comparable,
            "arm_b": armb.count,
            "monti_published": armb.published,
            "arm_b_gap_to_published": armb.gap,
            "arm_m_vs_arm_b": ov.n_a_linked - armb.count,
        }
        print(f"[pair] NECS<->{coh}: Arm-M(necs-linked)={ov.n_a_linked}  Arm-B={armb.count}  published={armb.published}", flush=True)

    manifest = {
        "arm": "M (BioMapper, names only) vs B (Monti method, locked)",
        "commit": _commit(),
        "deployment_url": KESTREL_API_URL,
        "metagraph_fingerprint": fingerprint,
        "sources": {
            "spreadsheet_sha256": _sha(SPREADSHEET),
            "arivale_sha256": _sha(ARIVALE_XLSX),
            "refmet_cache_sha256": _sha(REFMET_CACHE),
        },
        "panel_sizes": {k: len(v) for k, v in panels.items()},
        "results": results,
    }
    (out_dir / "arm_m_vs_arm_b.json").write_text(json.dumps(manifest, indent=2))
    print(f"[done] {out_dir}/arm_m_vs_arm_b.json", flush=True)


if __name__ == "__main__":
    sys.exit(main())
