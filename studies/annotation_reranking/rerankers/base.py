"""Base Reranker protocol and shared registry for annotation-reranking study."""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from studies.annotation_reranking.models_data import Candidate, EvalCase


@runtime_checkable
class Reranker(Protocol):
    """Protocol all rerankers must satisfy.

    ``select`` carries optional case context so rerankers can use ground-truth
    signals (e.g. refmet_id) at inference time.  It returns a 2-tuple:
      - ``selected_id``: the winning CURIE (or None when candidates is empty).
      - ``review_flag``: a short label string when the call warrants human review,
        otherwise None.

    Deterministic rerankers (top1, rm_anchor) ignore ``case`` and always return
    ``(selected_id, None)``.  LLM and guard rerankers (source_weight_guard, Task 5+)
    may use ``case`` and may return non-None flags.

    This signature is the standard all future rerankers AND the orchestrator
    (Task 8) must follow.
    """

    name: str

    def select(
        self,
        candidates: "list[Candidate]",
        case: "EvalCase | None" = None,
    ) -> "tuple[str | None, str | None]":
        ...


REGISTRY: dict[str, Reranker] = {}


def register(r: Reranker) -> Reranker:
    REGISTRY[r.name] = r
    return r
