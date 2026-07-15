"""Head-to-head assembly — BioMapper vs each incumbent tool, on the SAME rows, one metric.

Merges BioMapper's ``score_curie`` result and each competitor's ``score_competitor_run`` result
into a single directly-comparable structure and writes ``results.json``. The comparison is only
legitimate because every tool was scored by the identical rule on the identical rows/gold — so this
assembler ENFORCES that invariant fail-loud:

  - every tool's ``scored_denominator`` must equal BioMapper's (same held-out gold rows). A
    mismatch means a run silently changed the row set or gold -> ``HeadToHeadRowMismatchError``.
  - if BioMapper scored zero rows (``top1_accuracy is None``), there is nothing to compare ->
    ``HeadToHeadUnscorableError``. An unscorable head-to-head is never written as if it were a
    result.

One comparable metric (Top-1 CURIE-equality accuracy) is reported for every tool; coverage is
reported per tool honestly (a no-mapping is a miss, already folded into the score); protocol deltas
(``unsupported_targets`` / notes) ride alongside each competitor entry.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any

from ..config import CurieDatasetConfig
from . import ACCESS_NOTES

COMPARABLE_METRIC = "top1_accuracy"
BIOMAPPER_LABEL = "BioMapper"


class HeadToHeadRowMismatchError(RuntimeError):
    """A tool was scored on a different row/gold set than BioMapper — the comparison is invalid."""


class HeadToHeadUnscorableError(RuntimeError):
    """BioMapper scored zero rows — there is nothing to compare, so nothing is written."""


def _entry(tool: str, result: dict[str, Any]) -> dict[str, Any]:
    core = result["comparable_core"]
    cov = result["coverage"]
    stats = result.get("curie_stats", {})
    return {
        "tool": tool,
        "top1_accuracy": core["top1_accuracy"],
        "correct": core["correct"],
        "scored_denominator": core["scored_denominator"],
        "coverage_fraction": cov["fraction"],
        "n_predicted": cov["n_predicted"],
        "total": cov["total"],
        "precision": stats.get("precision"),
        "recall": stats.get("recall"),
        "f1": stats.get("f1"),
        "supported_targets": result.get("supported_targets"),
        "unsupported_targets": result.get("unsupported_targets"),
        "protocol_notes": result.get("protocol_notes", []),
    }


def assemble_head_to_head(
    *,
    config: CurieDatasetConfig,
    biomapper_result: dict[str, Any],
    competitor_results: list[dict[str, Any]],
    out_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build (and optionally write) the BioMapper-vs-competitors head-to-head for one backbone.

    ``biomapper_result`` is a ``score_curie`` output; ``competitor_results`` are
    ``score_competitor_run`` outputs (each carries its tool name + protocol deltas). Returns the
    assembled dict; writes ``results.json`` when ``out_path`` is given.
    """
    bm_core = biomapper_result["comparable_core"]
    scored = bm_core["scored_denominator"]
    if bm_core["top1_accuracy"] is None or scored == 0:
        raise HeadToHeadUnscorableError(
            f"{config.key}: BioMapper scored zero held-out-gold rows (scored_denominator={scored}); "
            f"refusing to write an unscorable head-to-head."
        )

    entries = [_entry(BIOMAPPER_LABEL, biomapper_result)]
    for result in competitor_results:
        tool = result.get("tool", "competitor")
        comp_scored = result["comparable_core"]["scored_denominator"]
        if comp_scored != scored:
            raise HeadToHeadRowMismatchError(
                f"{config.key}: {tool} scored {comp_scored} rows but BioMapper scored {scored}. A "
                f"controlled head-to-head requires the identical gold/row set — refusing to compare."
            )
        entries.append(_entry(tool, result))

    assembled = {
        "dataset": config.key,
        "arm": config.arm,
        "entity_type": config.entity_type,
        "input_type": config.input_type,
        "source_namespace": None,  # filled by the live driver (runner.source_namespace_for)
        "comparable_metric": COMPARABLE_METRIC,
        "scored_denominator": scored,
        "target_vocabs": list(config.target_vocabs),
        "gold_curie_columns": {ns: col for ns, col in config.gold_curie_columns},
        "tools": entries,
        "leaderboard": sorted(
            [(e["tool"], e["top1_accuracy"]) for e in entries],
            key=lambda t: (t[1] is not None, t[1] or 0.0),
            reverse=True,
        ),
        "api_access_notes": ACCESS_NOTES,
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "note": (
            "Controlled same-protocol head-to-head: every tool scored by the identical "
            "curie_scorer rule on the identical held-out-gold rows. A no-mapping is a miss (folded "
            "into accuracy/coverage), an outage is fail-loud, and target namespaces a tool cannot "
            "express are recorded as unsupported_targets (protocol deltas), not hidden."
        ),
    }
    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(assembled, indent=2, default=str))
    return assembled
