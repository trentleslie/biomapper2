"""NECS gold-disagreement exemplar set (Unit 8) — the primary Deliverable-1 artifact.

One row per key-vs-key disagreement (at ``block1+block2[:8]``), each individually checkable from
the single published MOESM5 file: name, both candidate keys, both SMILES, formula, the assigned
KIND/class, the repair state, and the rule applied. A reader can verify any single row without
re-running anything and without BioMapper.

Numbers in the rendered report are computed from the emitted JSON (never hand-typed), so prose and
artifact cannot drift. ``undecidable`` rows are shown, not dropped, and no rate is plotted across
the abstention boundary.

LICENSE: the rows derive from the Monti et al. supplement (Springer terms). Producing the artifact
to a run dir is fine; committing/publishing it requires the supplement-terms check (see plan Unit 1).
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from ..scorers.necs_gold_repair import COMPARISON_RULE, _adj, classify_row

ATTRIBUTION = (
    "Source values (compound name, InChIKeys, SMILES, formula) are extracted from the supplement "
    "of Monti et al. 2026, GeroScience, doi:10.1007/s11357-026-02174-2 (Table S1 / MOESM5), "
    "licensed CC BY-NC-ND 4.0. Reproduced with attribution for non-commercial research; the "
    "KIND/defect classification and repair verdicts are this work's own analysis."
)


def build_exemplar_set(input_df: pd.DataFrame) -> dict[str, Any]:
    """Return {'exemplars': [...one per disagreement...], 'summary': {...}} from a built input_df."""
    exemplars: list[dict[str, Any]] = []
    for r in input_df.to_dict("records"):
        lk = str(r.get("gold_inchikey", "") or "").strip()
        mk = str(r.get("gold_inchikey_standard", "") or "").strip()
        if not lk or not mk or _adj(lk) == _adj(mk):
            continue  # not a disagreement at the adjudication key
        res = classify_row(lk, r.get("gold_smiles"), mk, r.get("gold_smiles_standard"),
                           r.get("gold_formula"))
        exemplars.append({
            "chemical_name": str(r.get("chemical_name", "")),
            "legacy_inchikey": lk,
            "modern_inchikey": mk,
            "legacy_smiles": str(r.get("gold_smiles", "") or ""),
            "modern_smiles": str(r.get("gold_smiles_standard", "") or ""),
            "formula": str(r.get("gold_formula", "") or ""),
            "kind": res["kind"],
            "klass": res["klass"],
            "arbiter": res["arbiter"],
            "offline_resolved": res["offline_resolved"],
            "rdkit_hint": res["rdkit_hint"],
            "reason": res["reason"],
            "comparison_rule": COMPARISON_RULE,
        })
    kind_counts = dict(Counter(e["kind"] for e in exemplars))
    summary = {
        "n_disagreements": len(exemplars),
        "comparison_rule": COMPARISON_RULE,
        "kind_counts": kind_counts,
        "n_offline_resolved": sum(1 for e in exemplars if e["offline_resolved"]),
        "n_pending_anchor": sum(
            1 for e in exemplars if e["kind"] in ("kind_b_structure", "stereo_conflict", "stereo_odd")
        ),
    }
    summary["attribution"] = ATTRIBUTION
    return {"exemplars": exemplars, "summary": summary}


def render_markdown(bundle: dict[str, Any]) -> str:
    """Render the exemplar report; every number is read from ``bundle``, never hard-typed."""
    s = bundle["summary"]
    lines = [
        "# NECS gold-disagreement exemplar set",
        "",
        f"> {s['attribution']}",
        "",
        f"Disagreements at `{s['comparison_rule']}`: **{s['n_disagreements']}** "
        f"(offline-resolved {s['n_offline_resolved']}, pending external anchor {s['n_pending_anchor']}).",
        "",
        "Each row is verifiable from the single published MOESM5 file. `undecidable` rows are listed,",
        "not dropped; no rate is computed across them.",
        "",
        "## By kind",
        "",
        "| kind | n |",
        "|---|---|",
    ]
    for kind, n in sorted(s["kind_counts"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| {kind} | {n} |")
    lines += ["", "## Exemplars", "",
              "| name | legacy key | modern key | formula | kind | arbiter |",
              "|---|---|---|---|---|---|"]
    for e in bundle["exemplars"]:
        lines.append(
            f"| {e['chemical_name']} | `{e['legacy_inchikey']}` | `{e['modern_inchikey']}` | "
            f"{e['formula']} | {e['kind']} | {e['arbiter'] or '—'} |"
        )
    return "\n".join(lines) + "\n"


def write_exemplar_report(bundle: dict[str, Any], out_dir: str | Path) -> dict[str, str]:
    """Persist the JSON artifact + markdown to ``out_dir``. Returns the written paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "necs_gold_exemplars.json"
    md_path = out / "necs_gold_exemplars.md"
    json_path.write_text(json.dumps(bundle, indent=2))
    md_path.write_text(render_markdown(bundle))
    return {"json": str(json_path), "markdown": str(md_path)}
