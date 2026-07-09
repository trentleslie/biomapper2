"""LLM reranker for the annotation-reranking study.

Provides:
  - build_prompt(candidates, blind_rm) -> str
      Serializes candidates into a prompt.  When blind_rm=True, strips any
      equivalent_ids entries starting with "RM:" so the model cannot key on
      the RefMet anchor feature.

  - parse_selection(text, candidates) -> str | None
      Extracts the first CHEBI CURIE from the model's text response that is
      present in the candidate list.  Returns None for off-list or malformed
      responses.

  - LlmReranker(model_name, call_fn, blind_rm)
      Wraps build_prompt + parse_selection with an injected call_fn so tests
      can stub the LLM without real API calls.

      Protocol (Revision 2026-07-08): select() returns (selected_id, None).
      LLM rerankers never emit a review flag.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from studies.annotation_reranking.models_data import Candidate, EvalCase

_INSTRUCTION = (
    "You are matching a metabolite query to the single best knowledge-graph node.\n"
    "Choose exactly one candidate. Respond with ONLY its CHEBI CURIE (e.g. CHEBI:12345)."
)


def _serialize(c: "Candidate", blind_rm: bool) -> str:
    # Blinding removes RM: anchor ids from equivalent_ids only.
    # c.name is the KG/ChEBI node's own name from Kestrel hybrid-search —
    # retained as a legitimate reranking signal (it is NOT a RefMet-specific
    # field and stripping it would cripple the reranker).
    # Note: residual name-similarity between a candidate name and the query is
    # an inherent, un-blindable signal — documented as a study limitation, not
    # a leak to strip.
    equiv = [e for e in c.equivalent_ids if not (blind_rm and e.startswith("RM:"))]
    return f"- {c.id} | name={c.name} | score={c.score} | equivalent_ids={equiv}"


def build_prompt(candidates: "list[Candidate]", blind_rm: bool) -> str:
    """Build the LLM prompt from a list of candidates.

    When blind_rm=True, strips RM: entries from equivalent_ids so the model
    cannot key on the RefMet anchor.  The candidate name field is always
    included — see _serialize for the rationale.
    """
    lines = "\n".join(_serialize(c, blind_rm) for c in candidates)
    return f"{_INSTRUCTION}\n\nCandidates:\n{lines}\n\nAnswer with one CURIE:"


def parse_selection(text: str, candidates: "list[Candidate]") -> str | None:
    """Extract the winning CURIE from the model's response.

    Scans for CHEBI:\\d+ tokens in order of appearance and returns the first
    that is present in the candidate list.  Returns None if no in-list CURIE
    is found (off-list hallucination or unrecognised format).
    """
    ids = {c.id for c in candidates}
    for m in re.findall(r"CHEBI:\d+", text):
        if m in ids:
            return m
    return None


class LlmReranker:
    """LLM-based reranker with injected call_fn for testability.

    Parameters
    ----------
    model_name:
        Identifier string (e.g. "sonnet", "opus") used to construct `.name`
        and forwarded to call_fn.
    call_fn:
        Callable ``(model_name: str, prompt: str) -> str`` that returns the
        model's raw text response.  Injected so tests can stub without real
        API calls.
    blind_rm:
        When True, strip RM: entries from the prompt (RM-blinding condition).

    Protocol (Revision 2026-07-08)
    --------------------------------
    ``select(candidates, case=None) -> tuple[str | None, str | None]``
    LLM rerankers never emit a review flag, so the second element is always
    None.  Returns ``(None, None)`` when candidates is empty.
    """

    def __init__(self, model_name: str, call_fn, blind_rm: bool) -> None:
        self.model_name = model_name
        self.call_fn = call_fn   # (model_name, prompt) -> str
        self.blind_rm = blind_rm
        self.name = f"llm:{model_name}{'/blind' if blind_rm else ''}"

    def select(
        self,
        candidates: "list[Candidate]",
        case: "EvalCase | None" = None,
    ) -> tuple[str | None, str | None]:
        if not candidates:
            return None, None
        prompt = build_prompt(candidates, self.blind_rm)
        text = self.call_fn(self.model_name, prompt)
        return parse_selection(text, candidates), None
