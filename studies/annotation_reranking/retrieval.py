"""Top-N candidate retrieval with equivalent_ids enrichment.

Calls KestrelHybridSearchAnnotator._kestrel_hybrid_search directly, bypassing
the production get_annotations path (which hardcodes limit=1).

The _raw_hybrid_search and _fetch_equivalent_ids module-level functions are the
seam patched by unit tests — keep them as thin wrappers so mock.patch.object
works correctly.

Note on Linker.get_equivalent_ids return shape:
    The real API returns dict[str, dict[str, list[str]]], i.e.
        {"CHEBI:15365": {"HMDB": ["HMDB0001879"], "RM": ["0001"]}}
    _fetch_equivalent_ids flattens this to dict[str, list[str]], i.e.
        {"CHEBI:15365": ["HMDB:HMDB0001879", "RM:0001"]}
    so that Candidate.equivalent_ids contains full CURIEs and has_refmet() works.
"""
from biomapper2.core.annotators.kestrel_hybrid import KestrelHybridSearchAnnotator
from biomapper2.core.linker import Linker
from studies.annotation_reranking.models_data import Candidate


def _raw_hybrid_search(text: str, category: str, prefixes, limit: int) -> dict:
    """Bypasses production get_annotations (which hardcodes limit=1) on purpose."""
    return KestrelHybridSearchAnnotator._kestrel_hybrid_search(text, category, prefixes, limit=limit)


def _fetch_equivalent_ids(ids: list[str]) -> dict[str, list[str]]:
    """Wrap Linker.get_equivalent_ids; return {curie: [flat equivalent CURIEs]}.

    Linker returns {curie: {prefix: [local_ids]}}, so we reconstruct full CURIEs
    by joining prefix + ":" + local_id.
    """
    nested = Linker.get_equivalent_ids(ids)
    result: dict[str, list[str]] = {}
    for curie, prefix_map in nested.items():
        flat: list[str] = []
        for prefix, local_ids in prefix_map.items():
            for local_id in local_ids:
                flat.append(f"{prefix}:{local_id}")
        result[curie] = flat
    return result


def fetch_candidates(name: str, category: str, top_n: int = 20) -> list[Candidate]:
    """Return up to top_n scored Kestrel candidates enriched with equivalent_ids."""
    raw = _raw_hybrid_search(name, category, None, limit=top_n).get(name, [])
    ids = [r["id"] for r in raw]
    equiv = _fetch_equivalent_ids(ids) if ids else {}
    return [
        Candidate(
            id=r["id"],
            score=float(r["score"]),
            name=r["name"],
            synonyms=r.get("synonyms", []),
            prefixes=r.get("prefixes", []),
            equivalent_ids=equiv.get(r["id"], []),
        )
        for r in raw
    ]
