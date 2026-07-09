"""Matrix orchestrator for the annotation-reranking study (Task 8).

Entry points
------------
build_manifest(csv_path, top_n, seeds, roster, hardware) -> dict
    Pure function; pins all reproducibility fields for a run.

score_case(case, candidates, reranker, model_label) -> RerankResult
    Pure function; handles all shadow paths (empty candidates, off-list
    None, exception from reranker, cost/latency seam for LLM rerankers).

run_matrix(csv_path, top_n=20, seeds=(0,1,2), out_dir=None, hardware="unspecified") -> str
    Full orchestration: load dataset, fetch candidates, shuffle per seed,
    score every (case × seed × reranker) triple, write results.jsonl +
    manifest.json to a timestamped directory, return the path.

Amendment notes (2026-07-08)
----------------------------
- classify_regime takes (case, candidates) — 2-arg form.
- reranker.select returns a 2-tuple (selected_id, review_flag).
- cost_usd and latency_s are read from reranker.last_cost_usd /
  reranker.last_latency_s AFTER select; defaults to 0.0 when absent.
"""
from __future__ import annotations

import datetime
import json
import os
import random
from typing import TYPE_CHECKING

from studies.annotation_reranking.dataset import dataset_sha256, load_eval_cases
from studies.annotation_reranking.models_data import RerankResult
from studies.annotation_reranking.regimes import classify_regime
from studies.annotation_reranking.retrieval import fetch_candidates
from studies.annotation_reranking.rerankers.base import REGISTRY

if TYPE_CHECKING:
    from studies.annotation_reranking.models_data import Candidate, EvalCase
    from studies.annotation_reranking.rerankers.base import Reranker


# ---------------------------------------------------------------------------
# build_manifest
# ---------------------------------------------------------------------------

def build_manifest(
    csv_path: str,
    top_n: int,
    seeds: tuple[int, ...] | list[int],
    roster: list,
    hardware: str,
) -> dict:
    """Return a dict that pins every reproducibility field for a run.

    Parameters
    ----------
    csv_path:
        Path to the eval CSV; used only for SHA-256 pinning (may not exist
        when called with a placeholder path — sha256 is None in that case).
    top_n:
        Candidate window size passed to fetch_candidates.
    seeds:
        RNG seeds used for candidate shuffles (position-bias control).
    roster:
        List of reranker/model config objects.  ``model_id`` attribute is
        used when present; str(obj) otherwise.  May be empty.
    hardware:
        Free-form hardware descriptor for the run host.
    """
    sha = dataset_sha256(csv_path) if os.path.exists(csv_path) else None
    models = [getattr(obj, "model_id", str(obj)) for obj in roster]
    quant_notes = {
        getattr(obj, "label", ""): getattr(obj, "quant_note", "")
        for obj in roster
    }
    return {
        "dataset_sha256": sha,
        "top_n": top_n,
        "seeds": list(seeds),
        "temperature": 0,
        "models": models,
        "quant_notes": quant_notes,
        "hardware": hardware,
    }


# ---------------------------------------------------------------------------
# score_case
# ---------------------------------------------------------------------------

def score_case(
    case: "EvalCase",
    candidates: "list[Candidate]",
    reranker: "Reranker",
    model_label: str | None,
) -> RerankResult:
    """Score a single (case, candidate-set) pair with *reranker*.

    Shadow-path rules
    -----------------
    - Empty candidates  → error="empty_candidates", is_correct=False, selected_id=None.
    - Reranker exception → error=str(e), is_correct=False, selected_id=None.
    - selected is None  → error="off_list", is_correct=False.
    - correct_id is None → is_correct=None (refmet_agreement; unscored).
    - Otherwise is_correct = (selected == case.correct_id).

    Cost/latency seam
    -----------------
    After calling select(), reads ``reranker.last_cost_usd`` and
    ``reranker.last_latency_s`` (both default to 0.0 when absent).  This lets
    the LLM reranker (Task 9) populate these per-call without changing the
    orchestrator.
    """
    regime = classify_regime(case, candidates)

    base_kwargs = dict(
        case_name=case.name,
        reranker=reranker.name,
        model=model_label,
        correct_id=case.correct_id,
        label_source=case.label_source,
        regime=regime,
        cost_usd=0.0,
        latency_s=0.0,
    )

    if not candidates:
        return RerankResult(
            selected_id=None,
            is_correct=False,
            error="empty_candidates",
            review_flag=None,
            **base_kwargs,
        )

    try:
        selected, review_flag = reranker.select(candidates, case)
    except Exception as exc:
        return RerankResult(
            selected_id=None,
            is_correct=False,
            error=str(exc),
            review_flag=None,
            **base_kwargs,
        )

    # Read cost/latency seam AFTER select (may have been set by LLM reranker).
    cost_usd = getattr(reranker, "last_cost_usd", 0.0)
    latency_s = getattr(reranker, "last_latency_s", 0.0)
    base_kwargs["cost_usd"] = cost_usd
    base_kwargs["latency_s"] = latency_s

    if selected is None:
        return RerankResult(
            selected_id=None,
            is_correct=False,
            error="off_list",
            review_flag=review_flag,
            **base_kwargs,
        )

    is_correct = None if case.correct_id is None else (selected == case.correct_id)

    return RerankResult(
        selected_id=selected,
        is_correct=is_correct,
        error=None,
        review_flag=review_flag,
        **base_kwargs,
    )


# ---------------------------------------------------------------------------
# run_matrix
# ---------------------------------------------------------------------------

def run_matrix(
    csv_path: str,
    top_n: int = 20,
    seeds: tuple[int, ...] | list[int] = (0, 1, 2),
    out_dir: str | None = None,
    hardware: str = "unspecified",
) -> str:
    """Run the full annotation-reranking matrix and write outputs to *out_dir*.

    Iterates every (case × seed × reranker) triple:
    - Candidates are shuffled per seed for position-bias counterbalancing.
    - Results are written as JSONL (one RerankResult per line).
    - A manifest.json pinning all reproducibility fields is written first.

    Parameters
    ----------
    csv_path:
        Path to the ChEBI disagreement CSV.
    top_n:
        Candidate window size for Kestrel retrieval.
    seeds:
        RNG seeds for candidate shuffles.
    out_dir:
        Output directory.  Defaults to
        ``studies/annotation_reranking/runs/<UTC-timestamp>``.
    hardware:
        Free-form descriptor for the run host (e.g. "A100-40G").

    Returns
    -------
    str
        Absolute path to *out_dir*.
    """
    if out_dir is None:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = os.path.join(
            os.path.dirname(__file__), "runs", stamp
        )

    os.makedirs(out_dir, exist_ok=True)

    # Write manifest before results so partial runs are still inspectable.
    manifest = build_manifest(
        csv_path=csv_path,
        top_n=top_n,
        seeds=seeds,
        roster=list(REGISTRY.values()),
        hardware=hardware,
    )
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)

    cases = load_eval_cases(csv_path)
    results_path = os.path.join(out_dir, "results.jsonl")

    with open(results_path, "w", encoding="utf-8") as fh:
        for case in cases:
            candidates = fetch_candidates(case.name, case.category, top_n=top_n)
            for seed in seeds:
                rng = random.Random(seed)
                shuffled = candidates[:]
                rng.shuffle(shuffled)  # position-bias control
                for reranker in REGISTRY.values():
                    result = score_case(case, shuffled, reranker, model_label=None)
                    fh.write(json.dumps(result.__dict__) + "\n")

    print(f"[run] results saved to {out_dir}")
    return out_dir
