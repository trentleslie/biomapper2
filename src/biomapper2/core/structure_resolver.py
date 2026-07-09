"""Layered InChIKey-connectivity resolution for the resolver's source-weighting rule.

Resolves each node's InChIKey first block (the 2-D structural skeleton) in order: KG
``get-nodes`` -> Metabolomics Workbench by name -> PubChem by name. All external calls are
guarded by a timeout and return ``None`` on any error rather than raising (mirroring
:meth:`Linker.get_equivalent_ids`), so a lookup failure degrades to "unresolvable" and the
caller flags the feature for review instead of committing a wrong choice.
"""

import logging
from typing import Any
from urllib.parse import quote

import requests_cache

from ..config import (
    CACHE_DIR,
    MW_INCHIKEY_URL,
    PUBCHEM_INCHIKEY_URL,
    STRUCTURE_LOOKUP_TIMEOUT_S,
)
from .linker import Linker


class StructureResolver:
    """Adjudicates whether two KG nodes share InChIKey connectivity (2-D structure)."""

    def __init__(self, linker: Linker) -> None:
        self.linker = linker
        self._session = requests_cache.CachedSession(str(CACHE_DIR / "structure_http"))
        self._name_cache: dict[str, str | None] = {}  # inchikey block by node name (per process)

    def connectivity_match(self, node_a: str, node_b: str) -> bool | None:
        """True if both nodes resolve to the same first InChIKey block, False if they
        resolve and differ, None if either is unresolvable across all layers."""
        records = self.linker.get_node_records([node_a, node_b])
        block_a = self.inchikey_block(node_a, (records.get(node_a) or {}).get("name"), records)
        block_b = self.inchikey_block(node_b, (records.get(node_b) or {}).get("name"), records)
        if block_a is None or block_b is None:
            return None
        return block_a == block_b

    def inchikey_block(self, node_id: str, node_name: str | None, records: dict[str, Any] | None = None) -> str | None:
        """First InChIKey block for a node: KG record -> MW by name -> PubChem by name."""
        records = records if records is not None else self.linker.get_node_records([node_id])
        keys = ((records.get(node_id) or {}).get("equivalent_ids") or {}).get("INCHIKEY") or []
        if keys:
            return self._first_block(keys[0])
        if not node_name:
            return None
        if node_name in self._name_cache:
            return self._name_cache[node_name]
        try:
            key = self._fetch_mw_inchikey(node_name) or self._fetch_pubchem_inchikey(node_name)
            block = self._first_block(key) if key else None
        except Exception:
            logging.warning("Structure lookup failed for '%s'; treating as unresolvable", node_name, exc_info=True)
            block = None
        self._name_cache[node_name] = block
        return block

    @staticmethod
    def _first_block(inchikey: str | None) -> str | None:
        return inchikey.split("-")[0] if inchikey else None

    def _fetch_mw_inchikey(self, name: str) -> str | None:
        """Metabolomics Workbench: GET /rest/refmet/name/{name}/inchi_key."""
        url = f"{MW_INCHIKEY_URL}/{quote(name)}/inchi_key"
        resp = self._session.get(url, timeout=STRUCTURE_LOOKUP_TIMEOUT_S)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            key = data.get("inchi_key")
            return key if key and key != "-" else None
        return None

    def _fetch_pubchem_inchikey(self, name: str) -> str | None:
        """PubChem: GET /rest/pug/compound/name/{name}/property/InChIKey/JSON."""
        url = f"{PUBCHEM_INCHIKEY_URL}/{quote(name)}/property/InChIKey/JSON"
        resp = self._session.get(url, timeout=STRUCTURE_LOOKUP_TIMEOUT_S)
        resp.raise_for_status()
        data = resp.json()
        props = data.get("PropertyTable", {}).get("Properties", [])
        if props and props[0].get("InChIKey"):
            return props[0]["InChIKey"]
        return None
