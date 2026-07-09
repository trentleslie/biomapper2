"""Deterministic rerankers for the annotation-reranking study.

Contains:
  - Top1Reranker: always pick the highest-scoring candidate.
  - RmAnchorReranker: prefer RM-bearing candidates; fall back to highest score.
  - SourceWeightGuardReranker: primary metabolite baseline — the rule the LLM
      must beat.  Compares the resolver majority vote against the RefMet anchor
      using 2-D InChIKey connectivity.

All rerankers implement the Reranker protocol from `base.py`:
  select(candidates, case=None) -> (selected_id, review_flag)

REGISTRY entries are available for orchestration by name.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from studies.annotation_reranking.inchikey_resolver import connectivity_match
from studies.annotation_reranking.rerankers.base import register

if TYPE_CHECKING:
    from studies.annotation_reranking.models_data import Candidate, EvalCase


class Top1Reranker:
    """Select the candidate with the highest score.

    Ignores ``case``.  Always returns ``(selected_id, None)``.
    """

    name = "top1"

    def select(
        self,
        candidates: list[Candidate],
        case: EvalCase | None = None,
    ) -> tuple[str | None, str | None]:
        if not candidates:
            return None, None
        return max(candidates, key=lambda c: c.score).id, None


class RmAnchorReranker:
    """Prefer RefMet-bearing candidates; fall back to highest score.

    Among multiple RM-bearing candidates, choose the lexicographically smallest
    CURIE for a deterministic, reproducible tie-break.

    Ignores ``case``.  Always returns ``(selected_id, None)``.
    """

    name = "rm_anchor"

    def select(
        self,
        candidates: list[Candidate],
        case: EvalCase | None = None,
    ) -> tuple[str | None, str | None]:
        if not candidates:
            return None, None
        rm = [c for c in candidates if c.has_refmet()]
        if rm:
            return min(rm, key=lambda c: c.id).id, None
        return max(candidates, key=lambda c: c.score).id, None


class SourceWeightGuardReranker:
    """Primary metabolite baseline — the rule the LLM must beat.

    Algorithm (Revision 2026-07-08):
      1. ``majority`` = highest-scoring candidate (proxy for resolver vote).
      2. If ``case`` is None or ``case.refmet_id`` is empty → return majority,
         no flag.
      3. Build ``refmet_curie = f"CHEBI:{case.refmet_id}"`` and look it up in
         candidates.
      4. If refmet not found, or refmet IS majority → return majority, no flag.
      5. Run ``connectivity_fn(refmet.id, refmet.name, majority.id, majority.name)``:
         - True  → same molecule, silently prefer refmet.
         - False → error-prone bucket, prefer refmet + flag "divergent_refmet".
         - None  → unresolvable, keep majority + flag "conflict_no_structure".

    Inject ``connectivity_fn`` for testability (never hit the real network in
    unit tests).  The module-level REGISTRY entry uses the real
    ``connectivity_match`` from inchikey_resolver.
    """

    name = "source_weight_guard"

    def __init__(
        self,
        connectivity_fn: Callable[[str, str, str, str], bool | None],
    ) -> None:
        self._match = connectivity_fn

    def select(
        self,
        candidates: list[Candidate],
        case: EvalCase | None = None,
    ) -> tuple[str | None, str | None]:
        if not candidates:
            return None, "empty_candidates"

        majority = max(candidates, key=lambda c: c.score)

        if case is None or not case.refmet_id:
            return majority.id, None

        refmet_curie = f"CHEBI:{case.refmet_id}"
        refmet = next((c for c in candidates if c.id == refmet_curie), None)

        if refmet is None or refmet.id == majority.id:
            return majority.id, None

        same = self._match(refmet.id, refmet.name, majority.id, majority.name)
        if same is True:
            return refmet.id, None
        if same is False:
            return refmet.id, "divergent_refmet"
        return majority.id, "conflict_no_structure"


# ---------------------------------------------------------------------------
# Register instances — deterministic rerankers use no arguments.
# source_weight_guard uses the real connectivity_match for production use;
# tests construct SourceWeightGuardReranker with a mock fn directly.
# ---------------------------------------------------------------------------

register(Top1Reranker())
register(RmAnchorReranker())
register(SourceWeightGuardReranker(connectivity_match))
