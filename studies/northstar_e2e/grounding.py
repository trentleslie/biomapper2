"""Downstream grounding: resolved KG node -> KEGG.COMPOUND -> candidate pathways.

biomapper2 exposes no graph-traversal endpoint (verified on fork/dev: live Kestrel
endpoints are canonicalize / get-nodes / *-search only). So the "Kraken query" for
this slice is: chosen_kg_id -> Kestrel get-nodes KEGG.COMPOUND equivalents -> pinned
KEGG membership -> candidate pathways, carrying provenance so the interpreter can be
held to conclusions traceable to the annotated data (spec §5, provenance tracing).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import pandas as pd


class KestrelEquivalents(Protocol):
    def kegg_compounds_for(self, kg_node_ids: list[str]) -> dict[str, list[str]]:
        """Map each KG node id to its KEGG compound C-numbers (may be empty)."""
        ...


@dataclass(frozen=True)
class GroundedPathways:
    candidate_pathways: tuple[str, ...]
    provenance: dict[str, list[str]]  # pathway id -> [chosen_kg_id, ...]


def _clean_ids(mapped_df: pd.DataFrame, chosen_col: str) -> list[str]:
    ids: list[str] = []
    for v in mapped_df.get(chosen_col, pd.Series([], dtype=object)):
        if v is None:
            continue
        s = str(v).strip()
        if s and s.lower() != "nan":
            ids.append(s)
    return ids


def ground_pathways(
    mapped_df: pd.DataFrame,
    chosen_col: str,
    kestrel: KestrelEquivalents,
    membership: dict[str, tuple[str, ...]],
) -> GroundedPathways:
    node_ids = _clean_ids(mapped_df, chosen_col)
    kegg_by_node = kestrel.kegg_compounds_for(node_ids) if node_ids else {}
    provenance: dict[str, list[str]] = {}
    for node_id in node_ids:
        for cpd in kegg_by_node.get(node_id, []):
            for path in membership.get(cpd, ()):  # only compounds we can trace
                provenance.setdefault(path, [])
                if node_id not in provenance[path]:
                    provenance[path].append(node_id)
    return GroundedPathways(
        candidate_pathways=tuple(sorted(provenance)),
        provenance=provenance,
    )


class LinkerKestrel:
    """Live KestrelEquivalents backed by biomapper2's linker get-nodes call."""

    def __init__(self, linker: Any):
        self._linker = linker

    def kegg_compounds_for(self, kg_node_ids: list[str]) -> dict[str, list[str]]:
        # linker.get_equivalent_ids -> {curie: {prefix: [local_id, ...]}}
        equiv = self._linker.get_equivalent_ids(kg_node_ids, prefixes=["KEGG.COMPOUND"])
        out: dict[str, list[str]] = {}
        for curie, groups in equiv.items():
            out[curie] = list(groups.get("KEGG.COMPOUND", []))
        return out
