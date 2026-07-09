"""Retrievability + divergence tagging for the annotation-reranking study.

Provides per-case regime classification used by the Phase 0 gate and the
orchestrator (Task 8).

Functions
---------
target_id(case) -> str
    The node a reranker must select to be considered correct.

is_retrievable(case, candidates) -> bool
    True iff target_id(case) appears in the candidate list.

classify_regime(case, candidates) -> str
    Returns "retrievable" or "not_retrieved".
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from studies.annotation_reranking.models_data import Candidate, EvalCase


def target_id(case: "EvalCase") -> str:
    """Return the CURIE the reranker must pick to be correct.

    Priority:
      1. ``case.correct_id`` if set (independently adjudicated).
      2. ``f"CHEBI:{case.refmet_id.strip()}"`` — RefMet's node, matching the
         spike's recall measurement baseline.
    """
    if case.correct_id is not None:
        return case.correct_id
    return f"CHEBI:{case.refmet_id.strip()}"


def is_retrievable(case: "EvalCase", candidates: "list[Candidate]") -> bool:
    """Return True iff the target node appears in *candidates*."""
    tid = target_id(case)
    return any(c.id == tid for c in candidates)


def classify_regime(case: "EvalCase", candidates: "list[Candidate]") -> str:
    """Classify this (case, candidate-set) pair into a regime tag.

    Returns
    -------
    "retrievable"
        The target node is present in the candidate window; reranking may help.
    "not_retrieved"
        The target node is absent; reranking cannot fix this case.
    """
    return "retrievable" if is_retrievable(case, candidates) else "not_retrieved"
