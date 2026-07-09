"""Phase 0 decision gate for the annotation-reranking study.

Measures — BEFORE any model spend — two signals:

1. **Retrievability**: is the correct node even in the top-N candidate window?
   (Spike measured ~45/172 cases with the target absent at limit=200.
   Reranking cannot fix those.)

2. **Divergence**: among retrievable cases, how many does the
   ``source_weight_guard`` baseline flag for human review?  If the
   retrievable-AND-flagged set is tiny, an LLM has almost no room to add
   value → STOP and report before spending on the model matrix.

Running this module LIVE hits Kestrel and (for flagged cases) the layered
InChIKey resolver (MW/PubChem).  That is expected for the gate RUN and is
NOT done in CI (unit tests mock all network calls).

Usage (manual gate run)::

    python -m studies.annotation_reranking.phase0

or from Python::

    from studies.annotation_reranking.phase0 import run_phase0
    summary = run_phase0()
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Imports from sibling modules (do NOT redefine)
# ---------------------------------------------------------------------------
from studies.annotation_reranking.dataset import DEFAULT_CSV, dataset_sha256, load_eval_cases
from studies.annotation_reranking.regimes import classify_regime, target_id
from studies.annotation_reranking.rerankers import deterministic  # noqa: F401 — ensures REGISTRY is populated
from studies.annotation_reranking.rerankers.base import REGISTRY
from studies.annotation_reranking.retrieval import fetch_candidates

# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent
_DEFAULT_OUT_DIR = str(_HERE / "runs" / "phase0")

# Default CSV path — vendored at studies/annotation_reranking/data/chebi_disagreements_cat.csv
_DEFAULT_CSV = DEFAULT_CSV


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_phase0(
    csv_path: str = _DEFAULT_CSV,
    top_n: int = 200,
    out_dir: str | None = None,
) -> dict:
    """Run the Phase 0 gate and write ``phase0_regimes.json``.

    Parameters
    ----------
    csv_path:
        Path to the ChEBI disagreements CSV (172 rows).
    top_n:
        Number of Kestrel candidates to retrieve per compound.
    out_dir:
        Directory to write ``phase0_regimes.json``.  Defaults to
        ``studies/annotation_reranking/runs/phase0``.

    Returns
    -------
    dict
        The summary sub-dict (also embedded in the JSON output).
    """
    effective_out_dir = out_dir if out_dir is not None else _DEFAULT_OUT_DIR

    swg = REGISTRY["source_weight_guard"]
    sha = dataset_sha256(csv_path)
    cases = load_eval_cases(csv_path)

    # Tallies
    n_retrievable = 0
    n_not_retrieved = 0
    n_swg_disagrees = 0
    flag_counts: dict[str, int] = {
        "divergent_refmet": 0,
        "conflict_no_structure": 0,
        "none": 0,
    }

    per_case: list[dict] = []

    for case in cases:
        candidates = fetch_candidates(case.name, "metabolite", top_n)
        regime = classify_regime(case, candidates)

        if regime == "retrievable":
            n_retrievable += 1
            selected_id, review_flag = swg.select(candidates, case)

            # Count flag distribution (only among retrievable).
            # Any flag not in flag_counts (including None or future flags) collapses
            # to "none" — intentional: unknown flags should not crash the gate run.
            flag_key = review_flag if review_flag in flag_counts else "none"
            flag_counts[flag_key] += 1

            # Disagreement: SWG selected something other than the target
            tid = target_id(case)
            if selected_id != tid:
                n_swg_disagrees += 1
        else:
            n_not_retrieved += 1
            selected_id, review_flag = None, None

        per_case.append(
            {
                "name": case.name,
                "regime": regime,
                "target_id": target_id(case),
                "selected_id": selected_id,
                "review_flag": review_flag,
            }
        )

    summary = {
        "dataset_sha256": sha,
        "top_n": top_n,
        "total": len(cases),
        "retrievable": n_retrievable,
        "not_retrieved": n_not_retrieved,
        "n_swg_disagrees_correct": n_swg_disagrees,
        "flag_divergent_refmet": flag_counts["divergent_refmet"],
        "flag_conflict_no_structure": flag_counts["conflict_no_structure"],
        "flag_none": flag_counts["none"],
    }

    output = {"summary": summary, "per_case": per_case}

    # Write JSON
    out_path = Path(effective_out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    json_file = out_path / "phase0_regimes.json"
    with open(json_file, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2)

    # Print summary + path
    print("\n=== Phase 0 Summary ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"\nPhase 0 results written to: {json_file}")

    return summary


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_phase0()
