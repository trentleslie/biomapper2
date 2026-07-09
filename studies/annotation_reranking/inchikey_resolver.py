"""InChIKey first-block (2-D connectivity) resolver for the annotation-reranking study.

Provides a layered, cached resolver that returns a metabolite node's InChIKey first block
(the 14-character connectivity skeleton before the first '-'), used:
  1. As a non-circular structural label source (independent of RM: annotations).
  2. As the connectivity signal for the source_weight_guard reranker (Task 4).

Layer order: KG → Metabolomics Workbench → PubChem (first non-None wins).
Every layer is timeout-guarded and returns None on any error — never raises.

# CONSOLIDATE: replace with core.resolver._connectivity_match once Phase 1b merges
"""

import functools
import logging

import requests

from biomapper2.core.linker import Linker

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 10  # seconds


# ---------------------------------------------------------------------------
# Private layer helpers — each is a patchable seam for unit tests
# ---------------------------------------------------------------------------


def _block_from_kg(node_id: str) -> str | None:
    """Layer 1: resolve via KG equivalent_ids (INCHIKEY prefix).

    Calls Linker.get_equivalent_ids([node_id], prefixes=["INCHIKEY"]) and returns
    the first block of the first INCHIKEY local_id found, or None on any failure.
    """
    try:
        result = Linker.get_equivalent_ids([node_id], prefixes=["INCHIKEY"])
        node_map = result.get(node_id, {})
        ik_ids = node_map.get("INCHIKEY", [])
        if not ik_ids:
            return None
        first_id = ik_ids[0]
        return first_id.split("-")[0] or None
    except Exception:
        logger.debug("_block_from_kg: error resolving %s", node_id, exc_info=True)
        return None


def _block_from_mw(name: str) -> str | None:
    """Layer 2: resolve via Metabolomics Workbench REST API.

    GET https://www.metabolomicsworkbench.org/rest/refmet/name/{name}/inchi_key
    Response body is the plain-text InChIKey.
    """
    try:
        url = f"https://www.metabolomicsworkbench.org/rest/refmet/name/{requests.utils.quote(name)}/inchi_key"
        resp = requests.get(url, timeout=_REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return None
        body = resp.text.strip()
        if not body or "-" not in body:
            return None
        return body.split("-")[0] or None
    except Exception:
        logger.debug("_block_from_mw: error resolving %s", name, exc_info=True)
        return None


def _block_from_pubchem(name: str) -> str | None:
    """Layer 3: resolve via PubChem PUG REST API.

    GET https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{name}/property/InChIKey/JSON
    Parses PropertyTable.Properties[0].InChIKey.
    """
    try:
        url = (
            f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
            f"{requests.utils.quote(name)}/property/InChIKey/JSON"
        )
        resp = requests.get(url, timeout=_REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return None
        data = resp.json()
        props = data.get("PropertyTable", {}).get("Properties", [])
        if not props:
            return None
        ik = props[0].get("InChIKey", "")
        if not ik or "-" not in ik:
            return None
        return ik.split("-")[0] or None
    except Exception:
        logger.debug("_block_from_pubchem: error resolving %s", name, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def _inchikey_block_impl(node_id: str, name: str) -> str | None:
    """Resolve a node's InChIKey first block (2-D connectivity skeleton).

    Tries layers in order: KG → Metabolomics Workbench → PubChem.
    Returns the first non-None result, or None if all layers miss.

    Args:
        node_id: KG CURIE (e.g. "CHEBI:15365")
        name: Human-readable metabolite name used for MW/PubChem fallback lookups.

    Returns:
        14-character InChIKey first block, or None if unresolvable.
    """
    block = _block_from_kg(node_id)
    if block is not None:
        return block

    block = _block_from_mw(name)
    if block is not None:
        return block

    return _block_from_pubchem(name)


# Result is cached by (node_id, name). functools sets __wrapped__ to _inchikey_block_impl
# automatically, so tests calling inchikey_block.__wrapped__(...) exercise the real body.
inchikey_block = functools.lru_cache(maxsize=2048)(_inchikey_block_impl)


def connectivity_match(id_a: str, name_a: str, id_b: str, name_b: str) -> bool | None:
    """Compare 2-D connectivity between two metabolite nodes.

    Returns:
        True  — both blocks resolved and are identical (same 2-D skeleton).
        False — both blocks resolved and differ.
        None  — at least one block could not be resolved.

    Note: stereoisomers and protonation states share the same first block and are
    considered matching here; positional/constitutional isomers differ and return False.

    # CONSOLIDATE: replace with core.resolver._connectivity_match once Phase 1b merges
    """
    block_a = inchikey_block(id_a, name_a)
    block_b = inchikey_block(id_b, name_b)
    if block_a is None or block_b is None:
        return None
    return block_a == block_b
