"""Production structure oracle: wraps the real StructureResolver for the scorers.

Exposes the two-method ``StructureOracle`` protocol the scorer/verify/validate layers
consume. ``kg_block`` is the KG-record-only path (used to detect fallback); ``resolved_block``
is the full layered path (KG -> Metabolomics Workbench -> PubChem by name). Only BioMapper's
*prediction* is ever passed here — the gold InChIKey is never resolved, preserving oracle
independence.
"""

from __future__ import annotations

from typing import Any


class KGStructureOracle:
    def __init__(self, resolver: Any, linker: Any) -> None:
        self.resolver = resolver
        self.linker = linker

    def _records(self, node_id: str) -> dict[str, Any]:
        return self.linker.get_node_records([node_id])

    def kg_block(self, node_id: str) -> str | None:
        recs = self._records(node_id)
        keys = ((recs.get(node_id) or {}).get("equivalent_ids") or {}).get("INCHIKEY") or []
        if not keys:
            return None
        return str(keys[0]).split("-")[0]

    def resolved_block(self, node_id: str) -> str | None:
        recs = self._records(node_id)
        name = (recs.get(node_id) or {}).get("name")
        return self.resolver.inchikey_block(node_id, name, recs)
