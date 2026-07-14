"""Campaign report assembler — NECS + gene/protein backbones (the deferred follow-on).

Distinct from ``assemble.py`` (the Hajjar internal report) in three ways, each a Hajjar
calibration learning folded in:

  1. **One accuracy number per dataset, no per-vocab axis.** The Hajjar run proved
     ``chosen_kg_id`` is annotation-driven, not vocab-steered, so a per-vocab heatmap is
     uninformative. Each dataset contributes exactly one headline accuracy.
  2. **Two arms, two correctness rules.** Metabolite (NECS) uses the structure oracle and
     reports BOTH the strict InChIKey-first-block accuracy AND the charge/protonation-normalized
     accuracy. Gene/protein (backbones) uses CURIE equality (Top-1 + coverage/precision/recall/F1).
  3. **No competitor figure/column.** NECS and the backbones have NO published same-set
     competitor numbers, so — unlike Hajjar — only BioMapper-vs-reference/oracle is reported.
     Nothing is fabricated (no S2, no per-tool spread).

Internal only; never invokes /publish-wiki. Every number is sourced from a validated results
bundle passed in — nothing is typed by hand.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

CAMPAIGN_FRAMING = (
    "Deferred follow-on to the Hajjar vertical slice. Metabolite arm (NECS) is scored by the "
    "independent InChIKey structure oracle (strict + charge-normalized); the gene/protein arm "
    "(HGNC / UniProt idmapping / NCBI gene2ensembl) is scored by CURIE equality against each "
    "backbone's authoritative held-out cross-references. ONE accuracy number per dataset (no "
    "per-vocab axis). No competitor comparison exists for these sets, so none is drawn."
)


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _metabolite_row(entry: dict[str, Any]) -> str:
    core = entry["result"]["comparable_core"]
    cn = entry["result"].get("comparable_core_charge_normalized")
    cn_acc = _pct(cn["top1_accuracy"]) if cn else "n/a"
    cov = entry["result"]["coverage"]
    fb = entry["result"].get("fallback_bucket", {})
    return (
        f"| {entry['key']} | metabolite | {_pct(core['top1_accuracy'])} | {cn_acc} | "
        f"{core['scored_denominator']} | {cov['n_predicted']}/{cov['total']} | {fb.get('count', 0)} |"
    )


def _curie_row(entry: dict[str, Any]) -> str:
    core = entry["result"]["comparable_core"]
    stats = entry["result"].get("curie_stats", {})
    cov = entry["result"]["coverage"]
    return (
        f"| {entry['key']} | {entry.get('arm', 'gene/protein')} | {_pct(core['top1_accuracy'])} | "
        f"{core['scored_denominator']} | {cov['n_predicted']}/{cov['total']} | "
        f"{_pct(stats.get('precision'))} | {_pct(stats.get('recall'))} | {_pct(stats.get('f1'))} |"
    )


def assemble_campaign_report(
    *,
    metabolite_entries: list[dict[str, Any]],
    curie_entries: list[dict[str, Any]],
    integrity: dict[str, Any] | None = None,
    out_path: str | Path,
) -> str:
    """Assemble + write the internal campaign report. Returns the markdown text.

    ``metabolite_entries`` items: ``{"key", "result": <score_structure_oracle output>}``.
    ``curie_entries`` items: ``{"key", "arm", "result": <score_curie output>}``.
    """
    integrity = integrity or {}
    lines: list[str] = []
    lines.append("# BioMapper External Benchmarks — NECS + gene/protein backbones (internal)")
    lines.append("")
    lines.append("> INTERNAL — repo/vault only. Not for wiki publication this pass.")
    lines.append("")
    lines.append("## Framing")
    lines.append("")
    lines.append(CAMPAIGN_FRAMING)
    lines.append("")

    if metabolite_entries:
        lines.append("## Metabolite arm — structure-oracle Top-1 accuracy (one number per dataset)")
        lines.append("")
        lines.append(
            "| Dataset | Arm | Top-1 (strict) | Top-1 (charge-normalized) | Scored n | Coverage | Fallback bucket |"
        )
        lines.append("|---|---|---|---|---|---|---|")
        for entry in metabolite_entries:
            lines.append(_metabolite_row(entry))
        lines.append("")

    if curie_entries:
        lines.append("## Gene/protein arm — CURIE-equality accuracy (one number per dataset)")
        lines.append("")
        lines.append("| Dataset | Arm | Top-1 accuracy | Scored n | Coverage | Precision | Recall | F1 |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for entry in curie_entries:
            lines.append(_curie_row(entry))
        lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.append("- No published same-set competitor exists for NECS or the backbones — no competitor figure is drawn.")
    lines.append("- Per-vocab breakdown is intentionally omitted (annotation-driven, not vocab-steered).")
    lines.append(f"- Reconciliation passed: {integrity.get('reconciliation_passed')}")
    lines.append(f"- Validation passed: {integrity.get('validation_passed')}")
    lines.append("")

    text = "\n".join(lines)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text)
    return text
