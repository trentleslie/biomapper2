"""Non-circular auto-labeling of the RefMet<->BioMapper ChEBI disagreements.

The label is **InChIKey first-block connectivity** — the 2-D structural skeleton of
the compound named in the assay. It is resolved *independently* of both RefMet's and
BioMapper's ID assignment (query name -> Metabolomics Workbench / PubChem) and of the
signals a reranker/agent scores on, which is what keeps the eval non-circular.

Given the query's first block and the candidate nodes' first blocks, :func:`adjudicate`
picks the connectivity-matching node or defers to a human:

* exactly one candidate node shares the query's block -> that node is gold (``inchikey_auto``)
* two-or-more distinct nodes share it -> stereo/charge/positional variant that connectivity
  cannot separate -> ``expert`` (this is the >=100-pair long-pole)
* no candidate matches, or the query is unresolvable -> ``expert``

This module is pure (no I/O); the live resolution lives in ``build_gold_set.py`` and
reuses :class:`biomapper2.core.structure_resolver.StructureResolver` (Phase 1b) rather
than reimplementing the layered lookup.
"""

from __future__ import annotations

from dataclasses import dataclass, field

INCHIKEY_AUTO = "inchikey_auto"
EXPERT = "expert"


@dataclass(frozen=True)
class Candidate:
    """One candidate KG node for a disagreement pair.

    ``arm`` is ``"A"`` (the RefMet-assigned node) or ``"B"`` (BioMapper-assigned); a
    BioMapper ambiguous set (``"27596|50599"``) expands to several arm-``B`` candidates.
    ``block`` is the resolved InChIKey first block, or ``None`` if unresolvable.
    """

    arm: str
    curie: str
    block: str | None


@dataclass
class Adjudication:
    gold_curie: str | None
    adjudication_method: str  # INCHIKEY_AUTO | EXPERT
    difficulty_flag: str
    matched_arms: list[str] = field(default_factory=list)


def adjudicate(query_block: str | None, candidates: list[Candidate]) -> Adjudication:
    """Decide the gold node from the query's connectivity and the candidates'."""
    if query_block is None:
        return Adjudication(None, EXPERT, "query_unresolvable")

    matches = [c for c in candidates if c.block is not None and c.block == query_block]
    match_curies = sorted({c.curie for c in matches})
    matched_arms = sorted({c.arm for c in matches})

    if len(match_curies) == 1:
        return Adjudication(match_curies[0], INCHIKEY_AUTO, "connectivity_match", matched_arms)
    if not match_curies:
        return Adjudication(None, EXPERT, "no_candidate_matches_query")
    # >1 distinct node shares the query's 2-D skeleton — connectivity can't disambiguate.
    return Adjudication(None, EXPERT, "ambiguous_shared_connectivity", matched_arms)


def eligibility(method: str, retrievable: bool) -> list[str]:
    """Which consumer tracks a labeled row is ready for.

    * ``tier1``  — hard-case accuracy slice (any auto-labeled row).
    * ``ablation``/``tbench`` — additionally require the gold node to be retrievable in the
      candidate window; a node absent from the window belongs to a retrieval track, not a
      resolution/reranking eval.

    Expert-residual rows are not yet eligible for any track; they await human adjudication.
    """
    if method != INCHIKEY_AUTO:
        return []
    if retrievable:
        return ["tier1", "ablation", "tbench"]
    return ["tier1"]


def rm_blinded_view(query_name: str, candidate_curies: list[str], refmet_name: str | None) -> dict:
    """Candidate view with RefMet identity stripped (same control the ablation uses).

    Removes which candidate came from RefMet and the RefMet canonical name so an
    agent/reranker cannot win by pattern-matching the RefMet-derived fields.
    """
    return {
        "query_name": query_name,
        "candidates": sorted(set(candidate_curies)),
        "note": "arm identity and RefMet canonical name withheld; candidates shuffled by CURIE",
    }
