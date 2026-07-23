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

    def resolved_blocks(self, node_id: str) -> set[str]:
        """All KG-asserted InChIKey first-blocks for the prediction (the full equivalence set).

        Fixes the ``keys[0]`` artifact: a scorer can test whether gold is a member of the chosen
        node's KG-asserted structural equivalents rather than matching one arbitrarily-ordered
        representation (see ``StructureResolver.inchikey_blocks``).
        """
        recs = self._records(node_id)
        name = (recs.get(node_id) or {}).get("name")
        return self.resolver.inchikey_blocks(node_id, name, recs)

    def neutral_block(self, node_id: str) -> str | None:
        """Charge/protonation-normalized first-block of the prediction.

        Neutralizes the KG record's SMILES (RDKit ``Uncharger``) before hashing; when the record
        carries no SMILES to neutralize, falls back to the strict resolved block (can't neutralize
        a hash). Powers the charge-normalized accuracy variant.
        """
        from .scorers.structure_oracle_scorer import neutralize_first_block

        rec = self._records(node_id).get(node_id) or {}
        smiles = rec.get("smiles") or (rec.get("equivalent_ids") or {}).get("SMILES")
        if isinstance(smiles, (list, tuple)) and smiles:
            smiles = smiles[0]
        block = neutralize_first_block(smiles) if smiles else None
        return block if block is not None else self.resolved_block(node_id)
