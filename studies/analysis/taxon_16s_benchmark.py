"""16S taxon label benchmark: run the pinned panel through ``Mapper`` and score it (16S plan U4, R16).

Runs ``Mapper.map_dataset_to_kg(entity_type="microbiome")`` over ``data/taxon_16s/labels.tsv`` against the
configured Kestrel, scores every row against the corrected truth (``taxon_16s_truth_fix.py``), and ALWAYS
writes ``results/taxon_16s_<UTC>.json`` (``--out`` only overrides the path). The artifact pins:

* sha256 of every input file, the engine git SHA plus a dirty flag;
* the KG build from Kestrel ``/metagraph`` at the start AND the end of the run (a mismatch is flagged);
* the NCBI snapshot version.

Scoring is the vault scorer's category ladder (``16s_probe/datasets/score.py``), ported:

    CORRECT | CORRECT-PARENT | CORRECT-STALE-ID | PARTIAL-COMPONENT | WRONG-RANK | DUP/NON-NCBI | WRONG-TAXON | NO-HIT

Two acceptability rules are reported side by side:

* **equivalence-set**: a merged (stale) taxid counts as the same taxon, so CORRECT-STALE-ID is acceptable;
* **strict**: CORRECT-STALE-ID is not acceptable.

Both treat NO-HIT on a no-node (cat ``c``) row as a correct abstention. Cat ``x`` rows (eukaryote or
domain/kingdom-only labels) are excluded from accuracy, as in the vault. Rows with a Kestrel fault are
EXCLUDED and counted, never scored as NO-HIT. Hit lineages (for kingdom and WRONG-RANK) come from live
NCBI E-utilities, cached, independently of the snapshot the annotator uses.

The checkpoint verdict (plan U7) is computed here and fails closed: it is refused, not written as a
pass or fail, when the scored population is smaller than the panel minus the faulted rows.

Usage::

    uv run python -m studies.analysis.taxon_16s_benchmark            # writes results/taxon_16s_<UTC>.json
    uv run python -m studies.analysis.taxon_16s_benchmark --limit 50 # smoke run on the first 50 rows
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import subprocess
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

DATA_DIR = Path(__file__).parent / "data" / "taxon_16s"
RESULTS_DIR = Path(__file__).parent / "results"
REPO_ROOT = Path(__file__).resolve().parents[2]

CATEGORIES = (
    "CORRECT",
    "CORRECT-PARENT",
    "CORRECT-STALE-ID",
    "PARTIAL-COMPONENT",
    "WRONG-RANK",
    "DUP/NON-NCBI",
    "WRONG-TAXON",
    "NO-HIT",
)
OK_EQUIVALENCE = frozenset({"CORRECT", "CORRECT-PARENT", "CORRECT-STALE-ID"})
OK_STRICT = frozenset({"CORRECT", "CORRECT-PARENT"})
PROKARYOTE_DOMAINS = ("2", "2157")
EUKARYOTE_DOMAIN = "2759"

# Pre-stated checkpoint rule (plan U7), fixed before the first PR1 run.
CHECKPOINT_RULE = {
    "eukaryote_or_homonym_commits": 0,
    "duplicate_node_commits": 0,
    "no_node_abstention_min": 0.90,
    "panel_equivalence_acceptable_min": 0.95,
}


# --------------------------------------------------------------------------------------------- scoring


def ncbi_of(node_id: str | None, equivalent_ids: Any = None) -> str | None:
    """The NCBI taxid a committed node stands for: its own id, else an NCBITaxon equivalent id."""
    if not node_id:
        return None
    if node_id.startswith("NCBITaxon:"):
        return node_id.split(":", 1)[1]
    if isinstance(equivalent_ids, dict):
        ids = equivalent_ids.get("NCBITaxon") or []
        return str(sorted(ids, key=str)[0]) if ids else None
    for eq in equivalent_ids or []:
        if str(eq).startswith("NCBITaxon:"):
            return str(eq).split(":", 1)[1]
    return None


def score_hit(node_id: str | None, equivalent_ids: Any, truth: dict, lineage: dict[str, dict]) -> str:
    """The vault category for one committed node (``None`` = no commit) against one truth record."""
    if not node_id:
        return "NO-HIT"
    t = ncbi_of(node_id, equivalent_ids)
    if t is None:
        return "DUP/NON-NCBI"
    targets = {str(x) for x in truth.get("targets") or [] if x}
    components = {str(x) for x in truth.get("components") or [] if x}
    current = (lineage.get(t) or {}).get("taxid", t)
    target_current = {(lineage.get(x) or {}).get("taxid", x) for x in targets}
    if t in targets:
        return "CORRECT" if truth["cat"] == "a" else "CORRECT-PARENT"
    if (t != current and current in targets) or (t in target_current):
        return "CORRECT-STALE-ID"
    if t in components:
        return "PARTIAL-COMPONENT"
    lin = set((lineage.get(t) or {}).get("lineage") or [])
    for x in targets | components:
        if x in lin or t in set((lineage.get(x) or {}).get("lineage") or []):
            return "WRONG-RANK"
    return "WRONG-TAXON"


def acceptable(category: str, truth: dict, *, strict: bool) -> bool:
    ok = OK_STRICT if strict else OK_EQUIVALENCE
    return category in ok or (truth["cat"] == "c" and category == "NO-HIT")


def kingdom(taxid: str | None, lineage: dict[str, dict]) -> str:
    if taxid is None:
        return ""
    lin = (lineage.get(taxid) or {}).get("lineage") or []
    if taxid in PROKARYOTE_DOMAINS or any(d in lin for d in PROKARYOTE_DOMAINS):
        return "prok"
    if taxid == EUKARYOTE_DOMAIN or EUKARYOTE_DOMAIN in lin:
        return "euk"
    return "other" if lineage.get(taxid) else "unknown"


def score_rows(rows: list[dict], truth: dict[str, dict], lineage: dict[str, dict], homonym_side: set[str]) -> list[dict]:
    """Per-row scoring records. ``rows`` carry id/source/label/n_units/reads/chosen/equivalents/faulted."""
    out = []
    for r in rows:
        g = truth[r["id"]]
        rec = {k: r[k] for k in ("id", "source", "label", "n_units", "reads", "chosen", "faulted", "route")}
        rec.update(cat=g["cat"], rule=g.get("rule"), targets=g.get("targets") or [])
        if r["faulted"]:
            rec.update(category=None, acceptable_eq=None, acceptable_strict=None, hit_kingdom="")
            out.append(rec)
            continue
        category = score_hit(r["chosen"], r.get("equivalents"), g, lineage)
        t = ncbi_of(r["chosen"], r.get("equivalents"))
        rec.update(
            category=category,
            hit_taxid=t,
            acceptable_eq=acceptable(category, g, strict=False),
            acceptable_strict=acceptable(category, g, strict=True),
            hit_kingdom=kingdom(t, lineage),
            duplicate_node_commit=bool(r["chosen"]) and not str(r["chosen"]).startswith("NCBITaxon:"),
            homonym_commit=t in homonym_side if t else False,
        )
        out.append(rec)
    return out


def tally(scored: list[dict], human_pending: set[str] | None = None) -> dict[str, Any]:
    """Per-source and ALL tallies (strict and equivalence-set, unit- and read-weighted)."""
    human_pending = human_pending or set()
    out: dict[str, Any] = {}
    for source in sorted({r["source"] for r in scored}) + ["ALL", "ALL_16S"]:
        if source == "ALL":
            rs = scored
        elif source == "ALL_16S":
            rs = [r for r in scored if r["source"] != "bare_controls"]
        else:
            rs = [r for r in scored if r["source"] == source]
        faulted = [r for r in rs if r["faulted"]]
        ev = [r for r in rs if not r["faulted"] and r["cat"] != "x"]
        d: dict[str, Any] = {
            "n": len(rs),
            "faulted": len(faulted),
            "n_scored": len(ev),
            "cat": dict(Counter(r["cat"] for r in rs)),
            "category": dict(Counter(r["category"] for r in ev)),
        }
        for mode, key in (("eq", "acceptable_eq"), ("strict", "acceptable_strict")):
            ok = [r for r in ev if r[key]]
            units = sum(r["n_units"] for r in ev)
            reads = sum(r["reads"] for r in ev)
            d[f"acceptable_{mode}"] = len(ok)
            d[f"acceptable_{mode}_rate"] = round(len(ok) / len(ev), 4) if ev else None
            d[f"acceptable_{mode}_unit_wt"] = round(sum(r["n_units"] for r in ok) / units, 4) if units else None
            d[f"acceptable_{mode}_read_wt"] = round(sum(r["reads"] for r in ok) / reads, 4) if reads else None
        no_node = [r for r in ev if r["cat"] == "c"]
        no_node_settled = [r for r in no_node if r["id"] not in human_pending]
        d["no_node_rows"] = len(no_node)
        d["no_node_abstained"] = sum(r["category"] == "NO-HIT" for r in no_node)
        d["no_node_abstention"] = round(d["no_node_abstained"] / len(no_node), 4) if no_node else None
        d["no_node_rows_excl_human_pending"] = len(no_node_settled)
        abst = sum(r["category"] == "NO-HIT" for r in no_node_settled)
        d["no_node_abstention_excl_human_pending"] = round(abst / len(no_node_settled), 4) if no_node_settled else None
        live = [r for r in rs if not r["faulted"]]
        d["eukaryote_commits"] = sum(r["hit_kingdom"] == "euk" for r in live)
        d["homonym_commits"] = sum(bool(r.get("homonym_commit")) for r in live)
        d["duplicate_node_commits"] = sum(bool(r.get("duplicate_node_commit")) for r in live)
        d["commits"] = sum(bool(r["chosen"]) for r in live)
        out[source] = d
    return out


def checkpoint_verdict(scored: list[dict], tallies: dict[str, Any], panel_size: int) -> dict[str, Any]:
    """The pre-stated U7 checkpoint rule on the 16S rows, failing closed on a shrunk population."""
    faulted = sum(1 for r in scored if r["faulted"])
    expected = panel_size - faulted
    present = len(scored) - faulted
    if panel_size <= 0 or present < expected or present <= 0:
        return {
            "status": "REFUSED",
            "reason": f"scored population {present} < panel {panel_size} minus faulted {faulted}",
        }
    t = tallies["ALL_16S"]
    terms = {
        "eukaryote_or_homonym_commits": t["eukaryote_commits"] + t["homonym_commits"],
        "duplicate_node_commits": t["duplicate_node_commits"],
        "no_node_abstention": t["no_node_abstention"],
        "panel_equivalence_acceptable": t["acceptable_eq_rate"],
    }
    met = {
        "eukaryote_or_homonym_commits": terms["eukaryote_or_homonym_commits"]
        <= CHECKPOINT_RULE["eukaryote_or_homonym_commits"],
        "duplicate_node_commits": terms["duplicate_node_commits"] <= CHECKPOINT_RULE["duplicate_node_commits"],
        "no_node_abstention": (terms["no_node_abstention"] or 0) >= CHECKPOINT_RULE["no_node_abstention_min"],
        "panel_equivalence_acceptable": (terms["panel_equivalence_acceptable"] or 0)
        >= CHECKPOINT_RULE["panel_equivalence_acceptable_min"],
    }
    return {
        "status": "MET" if all(met.values()) else "NOT_MET",
        "rule": CHECKPOINT_RULE,
        "terms": terms,
        "met": met,
        "outcome": (
            "PR2 shrinks to U9 (fields + link_miss) and the U10 gate"
            if all(met.values())
            else "PR2 is the full ladder (U8-U10)"
        ),
        "note": "Trent confirms the PR2 scope; this verdict is input to that decision, not the decision.",
    }


# ------------------------------------------------------------------------------------------- run pins


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git() -> dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=REPO_ROOT, stderr=subprocess.DEVNULL).decode().strip()

    try:
        return {"sha": run("rev-parse", "HEAD"), "dirty": bool(run("status", "--porcelain")), "branch": run("branch", "--show-current")}
    except Exception:  # noqa: BLE001 - outside a checkout
        return {"sha": None, "dirty": None, "branch": None}


def _metagraph() -> dict[str, Any]:
    from biomapper2.config import get_kestrel_api_url

    url = get_kestrel_api_url().rstrip("/") + "/metagraph"
    mg = requests.get(url, timeout=120).json()
    return {
        "kestrel": get_kestrel_api_url(),
        "version": mg.get("version"),
        "biolink_version": mg.get("biolink_version"),
        "microbiome_kg": (mg.get("source_versions") or {}).get("microbiome-kg"),
        "fetched": datetime.now(timezone.utc).isoformat(),
    }


def _parse_cell(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value is None or (isinstance(value, float) and value != value) or value == "":
        return None
    try:
        return ast.literal_eval(str(value))
    except (ValueError, SyntaxError):
        return value


def run_mapper(labels: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    """Map the panel; returns one row per label with chosen node, equivalents, route and fault flag."""
    from biomapper2.core.annotators.taxon_label import TaxonLabelAnnotator
    from biomapper2.mapper import Mapper

    mapper = Mapper()
    # The route rides the annotator_source helper column, which the TSV drops; capture it from the engine.
    captured: dict[Any, str] = {}
    engine = mapper.annotation_engine
    original = engine.annotate

    def annotate_and_capture(*args: Any, **kwargs: Any):
        result = original(*args, **kwargs)
        if isinstance(result, pd.DataFrame) and "annotator_source" in result:
            for idx, source in result["annotator_source"].items():
                captured[idx] = (source or {}).get(TaxonLabelAnnotator.slug)
        return result

    engine.annotate = annotate_and_capture  # type: ignore[method-assign]
    try:
        df = labels.reset_index(drop=True)
        path, _stats = mapper.map_dataset_to_kg(
            df, entity_type="microbiome", name_column="label", provided_id_columns=[], output_dir=out_dir, output_prefix="taxon_16s"
        )
    finally:
        engine.annotate = original  # type: ignore[method-assign]
    out = pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False)
    rows = []
    for i, r in out.iterrows():
        chosen = r.get("chosen_kg_id") or None
        error = r.get("error") or ""
        rows.append(
            {
                "chosen": chosen,
                "equivalents": _parse_cell(r.get("kg_equivalent_ids")),
                "faulted": "Kestrel fault" in error,
                "route": captured.get(i),
                "curies_assigned": _parse_cell(r.get("curies_assigned")),
            }
        )
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--out", type=Path, default=None, help="override results/taxon_16s_<UTC>.json")
    parser.add_argument("--limit", type=int, default=None, help="smoke run on the first N rows (no verdict)")
    args = parser.parse_args(argv)

    from biomapper2.core import ncbi_taxonomy

    from .taxon_16s_truth_fix import Eutils

    started = datetime.now(timezone.utc)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    out_path = args.out or (RESULTS_DIR / f"taxon_16s_{stamp}.json")
    inputs = {p.name: _sha256(p) for p in sorted(args.data_dir.iterdir()) if p.is_file()}
    labels = pd.read_csv(args.data_dir / "labels.tsv", sep="\t", dtype=str, keep_default_na=False)
    # The expected 16S population comes from the PINNED panel, never from the scored rows, so the
    # fail-closed shrink check in checkpoint_verdict can actually fire.
    panel_16s = int((labels["source"] != "bare_controls").sum())
    if args.limit:
        labels = labels.head(args.limit)
    truth = json.loads((args.data_dir / "truth.json").read_text())
    fix_summary = json.loads((args.data_dir / "baseline_corrected.json").read_text())
    human_pending = set(fix_summary.get("human_list") or [])
    pins_start = {"git": _git(), "kg": _metagraph(), "snapshot_version": ncbi_taxonomy.version()}

    with tempfile.TemporaryDirectory() as tmp:
        mapped = run_mapper(labels, Path(tmp))

    pins_end = {"git": _git(), "kg": _metagraph(), "snapshot_version": ncbi_taxonomy.version()}
    if len(mapped) != len(labels):
        # zip() below would silently drop the unmatched rows; the shrink check must see them as missing.
        print(f"WARNING: mapper returned {len(mapped)} rows for {len(labels)} labels; the verdict will refuse")
    rows = []
    for (_, lab), (_, m) in zip(labels.iterrows(), mapped.iterrows()):
        rows.append(
            {
                "id": lab["id"],
                "source": lab["source"],
                "label": lab["label"],
                "n_units": int(lab["n_units"]),
                "reads": float(lab["reads"] or 0),
                "chosen": m["chosen"],
                "equivalents": m["equivalents"],
                "faulted": bool(m["faulted"]),
                "route": m["route"],
                "voted": bool((m["curies_assigned"] or {}).get("taxon-label")),
            }
        )
    eutils = Eutils()
    try:
        needed = {ncbi_of(r["chosen"], r["equivalents"]) for r in rows} | {
            str(x) for r in rows for x in (truth[r["id"]].get("targets") or []) + (truth[r["id"]].get("components") or [])
        }
        lineage = eutils.lineage(sorted(x for x in needed if x))
    finally:
        eutils.save()
    homonym_side = {str(t) for t in ncbi_taxonomy.load_or_raise().homonym_nonprokaryote}
    scored = score_rows(rows, truth, lineage, homonym_side)
    for rec, row in zip(scored, rows):
        rec["voted"] = row["voted"]
    tallies = tally(scored, human_pending)
    voted = [r for r in scored if r["voted"] and not r["faulted"]]
    linkage = {
        "voted": len(voted),
        "linked": sum(bool(r["chosen"]) for r in voted),
        "rate": round(sum(bool(r["chosen"]) for r in voted) / len(voted), 4) if voted else None,
    }
    verdict = (
        {"status": "REFUSED", "reason": "--limit smoke run"}
        if args.limit
        else checkpoint_verdict([r for r in scored if r["source"] != "bare_controls"], tallies, panel_16s)
    )
    artifact = {
        "study": "taxon_16s_benchmark",
        "plan": "docs/plans/2026-11-18-001-feat-16s-taxon-label-resolution-plan.md (U4/U7)",
        "started": started.isoformat(),
        "finished": datetime.now(timezone.utc).isoformat(),
        "inputs_sha256": inputs,
        "pins_start": pins_start,
        "pins_end": pins_end,
        "kg_build_changed_during_run": pins_start["kg"]["version"] != pins_end["kg"]["version"]
        or pins_start["kg"]["microbiome_kg"] != pins_end["kg"]["microbiome_kg"],
        "limit": args.limit,
        "human_pending_rows": sorted(human_pending),
        "routes": dict(Counter(r["route"] for r in scored)),
        "linkage": linkage,
        "tallies": tallies,
        "checkpoint": verdict,
        "rows": scored,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, indent=1, default=str) + "\n")
    t = tallies["ALL_16S"]
    print(
        f"16S rows: scored {t['n_scored']} faulted {t['faulted']} | acceptable eq {t['acceptable_eq_rate']} "
        f"strict {t['acceptable_strict_rate']} | no-node abstention {t['no_node_abstention']} "
        f"(excl. human-pending {t['no_node_abstention_excl_human_pending']}) | euk {t['eukaryote_commits']} "
        f"homonym {t['homonym_commits']} dup {t['duplicate_node_commits']} | linkage {linkage['rate']}"
    )
    print(f"checkpoint: {verdict['status']}")
    print(f"saved {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
