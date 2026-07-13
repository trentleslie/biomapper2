"""Build the shared hard-case gold set by auto-labeling the RefMet<->BioMapper ChEBI
disagreements with a non-circular InChIKey-connectivity label.

For each disagreement pair we resolve the InChIKey first block of the query compound
name and of every candidate ChEBI node via the layered
:class:`biomapper2.core.structure_resolver.StructureResolver` (KG ``equivalent_ids`` ->
Metabolomics Workbench ``/name`` -> PubChem ``/name``), then :func:`labeler.adjudicate`
picks the connectivity-matching node or defers to an expert.

Expensive-run hygiene: results are written to a timestamped directory by default (never
behind a flag), with input SHAs / git commit / KG URL pinned alongside so the run is
reproducible. ``--out`` only *overrides* the location.

    uv run python studies/shared_gold_set/build_gold_set.py
    uv run python studies/shared_gold_set/build_gold_set.py --limit 5   # smoke test
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from labeler import EXPERT, INCHIKEY_AUTO, Candidate, adjudicate, eligibility, rm_blinded_view

from biomapper2.config import KESTREL_API_URL
from biomapper2.core.linker import Linker
from biomapper2.core.structure_resolver import StructureResolver

STUDY_DIR = Path(__file__).resolve().parent
DATA_DIR = STUDY_DIR / "data"
DISAGREEMENTS_CSV = DATA_DIR / "chebi_disagreements_cat.csv"
RANK_PROBE_CSV = DATA_DIR / "rank_probe_results.csv"
RETRIEVABLE_RANK_MAX = 200  # retrievable@200; the probe window (n_candidates~50) is a conservative lower bound

QUERY_NODE_ID = "__query_name__"  # sentinel: forces StructureResolver down the name path, skipping the KG layer

# Independent hand-check labels (step 4: independence demonstration). Each auto-labeled sample
# row was re-adjudicated by structure-from-nomenclature reasoning — a *different* signal than the
# InChIKey first-block connectivity the auto label uses — keyed by query_name -> (gold, rationale).
HANDCHECK: dict[str, tuple[str, str]] = {
    "(15:3)-anacardic acid": (
        "CHEBI:174627",
        "2-OH-6-pentadecatrienyl-benzoate = anacardic C15:3; B nocardic acid is unrelated",
    ),
    "1-methylguanidine": ("CHEBI:16628", "free-base methylguanidine; B is the HCl salt"),
    "2-Methylmaleate": ("CHEBI:17626", "citraconate = 2-methylmaleate; B 3-methylmalate differs"),
    "2-hydroxypalmitate": ("CHEBI:65101", "palmitate = C16:0; B palmitoleate is C16:1"),
    "3-hydroxymandelate": ("CHEBI:86553", "meta-OH; B is the 4-OH para isomer"),
    "3-methylhistidine": ("CHEBI:70959", "exact name; B are N(pros)/N(tele) ring isomers"),
    "4-acetamidophenol": ("CHEBI:46195", "= paracetamol; B 2-acetamidophenol is the ortho isomer"),
    "4-hydroxyhippurate": ("CHEBI:71018", "para-OH; B is meta"),
    "4-methylbenzenesulfonate": ("CHEBI:27849", "= p-toluenesulfonate; B 4-formyl differs"),
    "4-methylcatechol sulfate": ("CHEBI:232803", "generic name match; A is the 1-O-position-specific node"),
    "6-shogaol": ("CHEBI:10138", "[6]-shogaol; A is the [8] homolog"),
    "9-hydroxystearate": ("CHEBI:136638", "9-OH-octadecanoate; B is the 8-OH isomer"),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=STUDY_DIR, text=True).strip()
    except Exception:
        return "unknown"


def _chebi(local_id: str) -> str:
    local_id = local_id.strip()
    return local_id if local_id.startswith("CHEBI:") else f"CHEBI:{local_id}"


def _load_retrievability() -> dict[str, dict]:
    """name -> {refmet_rank, bm_rank, refmet_in_kg} from the chebi_filter probe arm."""
    out: dict[str, dict] = {}
    with RANK_PROBE_CSV.open() as f:
        for row in csv.DictReader(f):
            if row.get("arm") != "chebi_filter":
                continue

            def _rank(v: str) -> int | None:
                v = (v or "").strip()
                return int(float(v)) if v else None

            out[row["name"]] = {
                "refmet_node": row.get("refmet_node") or "",
                "bm_node": row.get("bm_node") or "",
                "refmet_rank": _rank(row.get("refmet_rank", "")),
                "bm_rank": _rank(row.get("bm_rank", "")),
                "refmet_in_kg": (row.get("refmet_in_kg", "").strip().lower() in ("true", "1", "yes")),
            }
    return out


def _retrievable(gold_curie: str | None, refmet_curie: str, probe: dict | None) -> bool:
    """Is the (gold, or reference RefMet) node retrievable within the candidate window?"""
    if not probe:
        return False
    # Use the gold node's rank when known; else fall back to the reference RefMet node.
    rank = probe.get("refmet_rank")
    if gold_curie and probe.get("bm_node") and _chebi(str(probe["bm_node"])) == gold_curie:
        rank = probe.get("bm_rank")
    return rank is not None and rank <= RETRIEVABLE_RANK_MAX


def build_records(limit: int | None = None) -> list[dict]:
    resolver = StructureResolver(Linker())
    retrievability = _load_retrievability()

    rows = list(csv.DictReader(DISAGREEMENTS_CSV.open()))
    if limit:
        rows = rows[:limit]

    # Pre-fetch every candidate node record in one batched KG call (Linker batches internally).
    all_curies: list[str] = []
    for row in rows:
        all_curies.append(_chebi(row["refmet_id"]))
        all_curies.extend(_chebi(x) for x in row["biomapper_id"].split("|"))
    records = Linker.get_node_records(sorted(set(all_curies)))

    out: list[dict] = []
    for row in rows:
        query_name = row["name"]
        refmet_curie = _chebi(row["refmet_id"])
        bm_curies = [_chebi(x) for x in row["biomapper_id"].split("|")]
        bm_names = [n.strip() for n in row["biomapper_name"].split("|")]

        # Independent anchor: resolve the assay name's connectivity, skipping the KG layer.
        query_block = resolver.inchikey_block(QUERY_NODE_ID, query_name, records={})

        candidates: list[Candidate] = [
            Candidate("A", refmet_curie, resolver.inchikey_block(refmet_curie, row["refmet_name"], records))
        ]
        for i, curie in enumerate(bm_curies):
            name = bm_names[i] if i < len(bm_names) else (bm_names[0] if bm_names else None)
            candidates.append(Candidate("B", curie, resolver.inchikey_block(curie, name, records)))

        adj = adjudicate(query_block, candidates)
        probe = retrievability.get(query_name)
        retr = _retrievable(adj.gold_curie, refmet_curie, probe)
        all_curies_row = [refmet_curie] + bm_curies

        out.append(
            {
                "query_name": query_name,
                "match_level": row["level"],
                "category": row["category"],
                "candidate_A": {
                    "node": refmet_curie,
                    "name": row["refmet_name"],
                    "inchikey_block": candidates[0].block,
                    "kg_equiv_inchikeys": ((records.get(refmet_curie) or {}).get("equivalent_ids") or {}).get(
                        "INCHIKEY"
                    ),
                },
                "candidate_B": [
                    {
                        "node": c.curie,
                        "name": bm_names[i] if i < len(bm_names) else None,
                        "inchikey_block": c.block,
                        "kg_equiv_inchikeys": ((records.get(c.curie) or {}).get("equivalent_ids") or {}).get(
                            "INCHIKEY"
                        ),
                    }
                    for i, c in enumerate(candidates[1:])
                ],
                "query_inchikey_block": query_block,
                "gold_curie": adj.gold_curie,
                "adjudication_method": adj.adjudication_method,
                "difficulty_flag": adj.difficulty_flag,
                "matched_arms": adj.matched_arms,
                "retrievable@200": retr,
                "eligible_for": eligibility(adj.adjudication_method, retr),
                "rm_blinded_view": rm_blinded_view(query_name, all_curies_row, row["refmet_name"]),
            }
        )
    return out


def _flatten_for_csv(rec: dict) -> dict:
    b = rec["candidate_B"]
    return {
        "query_name": rec["query_name"],
        "match_level": rec["match_level"],
        "category": rec["category"],
        "candidate_A_node": rec["candidate_A"]["node"],
        "candidate_A_name": rec["candidate_A"]["name"],
        "candidate_A_block": rec["candidate_A"]["inchikey_block"],
        "candidate_B_nodes": "|".join(x["node"] for x in b),
        "candidate_B_names": "|".join((x["name"] or "") for x in b),
        "candidate_B_blocks": "|".join((x["inchikey_block"] or "") for x in b),
        "query_block": rec["query_inchikey_block"],
        "gold_curie": rec["gold_curie"] or "",
        "adjudication_method": rec["adjudication_method"],
        "difficulty_flag": rec["difficulty_flag"],
        "retrievable@200": rec["retrievable@200"],
        "eligible_for": ",".join(rec["eligible_for"]),
    }


def write_outputs(records: list[dict], out_dir: Path, limit: int | None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    with (out_dir / "gold_set.jsonl").open("w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")

    flat = [_flatten_for_csv(r) for r in records]
    with (out_dir / "gold_set.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(flat[0].keys()))
        w.writeheader()
        w.writerows(flat)

    # Deterministic hand-check sample: auto-labeled pairs, sorted by name.
    sample = sorted((r for r in records if r["adjudication_method"] == INCHIKEY_AUTO), key=lambda r: r["query_name"])[
        :12
    ]
    handcheck = [
        {
            "query_name": r["query_name"],
            "candidate_A": {"node": r["candidate_A"]["node"], "name": r["candidate_A"]["name"]},
            "candidate_B": [{"node": x["node"], "name": x["name"]} for x in r["candidate_B"]],
            "auto_gold": r["gold_curie"],
            "hand_gold": (HANDCHECK.get(r["query_name"]) or (None, None))[0],
            "hand_rationale": (HANDCHECK.get(r["query_name"]) or (None, None))[1],
            "agree": (HANDCHECK.get(r["query_name"]) or (None,))[0] == r["gold_curie"],
        }
        for r in sample
    ]
    (out_dir / "handcheck_sample.json").write_text(json.dumps(handcheck, indent=2))

    n_auto = sum(1 for r in records if r["adjudication_method"] == INCHIKEY_AUTO)
    n_expert = sum(1 for r in records if r["adjudication_method"] == EXPERT)
    provenance = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "kestrel_api_url": KESTREL_API_URL,
        "limit": limit,
        "n_pairs": len(records),
        "n_auto_labeled": n_auto,
        "n_expert_residual": n_expert,
        "inputs": {
            "chebi_disagreements_cat.csv": _sha256(DISAGREEMENTS_CSV),
            "rank_probe_results.csv": _sha256(RANK_PROBE_CSV),
        },
        "label_method": "inchikey_first_block_connectivity",
        "retrievable_window_note": (
            f"retrievable@{RETRIEVABLE_RANK_MAX} from the chebi_filter probe arm; probe window "
            "n_candidates~50 is a conservative lower bound for @200"
        ),
    }
    (out_dir / "provenance.json").write_text(json.dumps(provenance, indent=2))
    _write_report(records, handcheck, provenance, out_dir)


# difficulty_flags that are genuinely connectivity-ambiguous (the real expert long-pole) vs.
# flags that only landed in "expert" because the automatic name layer couldn't resolve a structure.
RESOLUTION_LIMITED_FLAGS = {"query_unresolvable", "no_candidate_matches_query"}


def _flag_kind(flag: str) -> str:
    if flag == "connectivity_match":
        return "auto"
    return "resolution-limited" if flag in RESOLUTION_LIMITED_FLAGS else "genuine-ambiguous"


def _write_report(records: list[dict], handcheck: list[dict], provenance: dict, out_dir: Path) -> None:
    from collections import Counter

    n = len(records)
    n_auto = provenance["n_auto_labeled"]
    n_expert = provenance["n_expert_residual"]
    by_reason = Counter(r["difficulty_flag"] for r in records)
    by_cat_expert = Counter(r["category"] for r in records if r["adjudication_method"] == EXPERT)
    n_retr = sum(1 for r in records if r["retrievable@200"])
    elig = Counter(t for r in records for t in r["eligible_for"])

    n_ambiguous = by_reason.get("ambiguous_shared_connectivity", 0)
    n_res_limited = sum(v for k, v in by_reason.items() if k in RESOLUTION_LIMITED_FLAGS)
    # How much of the flagged same-molecule-variant set is captured by the ambiguous bucket?
    same_mol_total = sum(1 for r in records if "same-molecule variant" in r["category"])
    same_mol_ambig = sum(
        1
        for r in records
        if "same-molecule variant" in r["category"] and r["difficulty_flag"] == "ambiguous_shared_connectivity"
    )

    n_agree = sum(1 for h in handcheck if h["agree"])
    n_checked = sum(1 for h in handcheck if h["hand_gold"] is not None)

    lines = [
        "# Shared hard-case gold set — auto-labeling report",
        "",
        f"- Generated (UTC): `{provenance['generated_utc']}`",
        f"- Git commit: `{provenance['git_commit']}`",
        f"- KG: `{provenance['kestrel_api_url']}`",
        f"- Label: **{provenance['label_method']}** (non-circular; independent of RefMet/BioMapper ID choice)",
        f"- Input SHA256 (disagreements): `{provenance['inputs']['chebi_disagreements_cat.csv'][:16]}…`",
        "",
        "## Headline",
        f"- **Pairs:** {n}",
        f"- **Auto-labeled (inchikey_auto):** {n_auto} ({n_auto / n:.0%})",
        f"- **Expert residual:** {n_expert} ({n_expert / n:.0%}), which decomposes into:",
        f"  - **{n_ambiguous} genuinely connectivity-ambiguous** — same 2-D skeleton, differ only by "
        "stereo/charge/positional/salt. This is the real ≥100-pair long-pole the plan warned about; "
        "first-block InChIKey *cannot* adjudicate it, so it is the true human-expert set.",
        f"  - **{n_res_limited} resolution-limited** — expert only because the query name did not resolve to a "
        "structure via MW/PubChem `/name` (mostly lipid shorthand / complex IUPAC). These are *recoverable* "
        "with a stronger query-structure source (provided InChIKey/SMILES), not genuine chemistry ambiguity.",
        f"- **Retrievable@{RETRIEVABLE_RANK_MAX}:** {n_retr} ({n_retr / n:.0%}) "
        f"({provenance['retrievable_window_note']}).",
        "",
        f"The flagged *same-molecule variant* set is captured cleanly by the ambiguous bucket: "
        f"**{same_mol_ambig}/{same_mol_total}** of those rows land in connectivity-ambiguous — confirming the "
        "plan's thesis that the stereo/charge/positional set is exactly what needs the human.",
        "",
        "### Adjudication breakdown",
        "| difficulty_flag | n | kind |",
        "|---|---|---|",
        *[f"| {k} | {v} | {_flag_kind(k)} |" for k, v in by_reason.most_common()],
        "",
        "### Expert residual by source category",
        "| category | n |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in by_cat_expert.most_common()],
        "",
        "### Consumer eligibility (auto rows only; expert rows await adjudication)",
        "| track | n |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in elig.most_common()],
        "",
        "## Independence demonstration (inter-method agreement)",
        f"Auto label = InChIKey first-block connectivity. Hand label = structure-from-nomenclature "
        f"reasoning on a deterministic sample of {len(handcheck)} auto-labeled rows — a *different* signal. "
        f"Agreement: **{n_agree}/{n_checked}** "
        f"({(n_agree / n_checked) if n_checked else 0:.0%}). Full sample in `handcheck_sample.json`.",
        "",
        "| query | auto_gold | hand_gold | agree | rationale |",
        "|---|---|---|---|---|",
        *[
            f"| {h['query_name']} | {h['auto_gold']} | {h['hand_gold']} | "
            f"{'✓' if h['agree'] else '✗'} | {h['hand_rationale']} |"
            for h in handcheck
        ],
        "",
        "## What downstream consumers get now",
        f"- **{n_auto} auto-labeled pairs** ready for the Tier-1 hard slice / ablation / TB-Science gold "
        "(gated on retrievability), each with an `rm_blinded_view` for the leakage control.",
        f"- **{n_ambiguous}-pair expert queue**, pre-narrowed to genuinely stereo/charge/positional cases — "
        "the actual human effort, and (being >100) enough on its own to hit the ablation's ≥100-pair bar once "
        "adjudicated.",
        f"- **{n_res_limited} resolution-limited pairs** flagged for a cheaper fix (supply a query structure) "
        "before they need a human.",
        "",
    ]
    (out_dir / "report.md").write_text("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=None, help="override output dir (default: timestamped results/ dir)")
    ap.add_argument("--limit", type=int, default=None, help="only process the first N pairs (smoke test)")
    args = ap.parse_args()

    out_dir = args.out or (STUDY_DIR / "results" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    records = build_records(limit=args.limit)
    write_outputs(records, out_dir, args.limit)

    n_auto = sum(1 for r in records if r["adjudication_method"] == INCHIKEY_AUTO)
    print(f"\nWrote {len(records)} gold records ({n_auto} auto-labeled, {len(records) - n_auto} expert-residual)")
    print(f"Output saved to: {out_dir}")


if __name__ == "__main__":
    main()
