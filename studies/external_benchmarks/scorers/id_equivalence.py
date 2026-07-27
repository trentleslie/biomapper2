"""Independent ID-equivalence judge for the name-hit ID-concordance qualifier.

Judges whether the curator's gold identifier and BioMapper's chosen identifier denote the same
chemical STRUCTURE, using a source built INDEPENDENTLY of BioMapper's Kestrel/Kraken KG — the
resolution-path-vs-scoring-path circularity guard: a tool that contributes to BioMapper's answer
can never also grade it. The judge is UniChem (EBI): cross-references computed from Standard InChI
across community resources (ChEBI/HMDB/PubChem/KEGG/...), sharing no infrastructure with the
resolver. It NEVER consults a row's own ``kg_equivalent_ids``.

Two independent variants, both reported BESIDE (never replacing) the strict exact-ID concordance:
  (a) UniChem-UCI equivalence  — gold and prediction resolve to the SAME UniChem Compound Id (UCI,
      standard-InChIKey based; stereo/charge must agree), OR the gold CURIE is a member of the
      prediction's UniChem cross-reference ``sources`` set.
  (b) InChIKey first-block bridge — each id resolved to an InChIKey first-block (UniChem's
      standardInchiKey, falling back to the reused ``PubChemInChIKeyResolver``) and compared on
      2-D connectivity only. Lenient; ≈ the 78-80% structure-concordance ceiling.

Discipline mirrors ``independent_inchikey.PubChemInChIKeyResolver``: CACHED per unique id
(disk-backed JSON — EBI throttles), IPv4-FORCED (``adapters.metlinkr.force_ipv4``), browser
User-Agent (EBI 403s the default requests UA), FAIL-SOFT to ``None`` on any non-200 / network /
parse error (row -> needs-verification, never fabricated or dropped).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from ..adapters.metlinkr import force_ipv4
from .curie_scorer import normalize_curie

_UNICHEM = "https://www.ebi.ac.uk/unichem/api/v1"
_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
# Our canonical CURIE prefixes (post normalize_curie) -> UniChem source short names.
_PREFIX_TO_UNICHEM: dict[str, str] = {
    "CHEBI": "chebi",
    "HMDB": "hmdb",
    "PUBCHEM": "pubchem",
    "KEGG": "kegg_ligand",
}


def _first_block(inchikey: str | None) -> str | None:
    if not inchikey:
        return None
    s = str(inchikey).strip()
    return s.split("-")[0] if s else None


def _pick(d: dict[str, Any], *candidates: str) -> Any:
    """First present, non-None candidate key from a dict (tolerant to UniChem key spellings)."""
    for k in candidates:
        if k in d and d[k] is not None:
            return d[k]
    return None


class UniChemClient:
    """UniChem 2.0 REST client: source registry + compound cross-reference lookup.

    ``lookup(curie)`` returns ``{"uci", "block", "sources"}`` (sources as normalized CURIEs) or
    ``None`` (fail-soft). Cached per CURIE; disk-backed when ``cache_path`` is given.
    """

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        session: Any | None = None,
        cache_path: str | Path | None = None,
    ) -> None:
        import requests

        self._timeout = timeout
        self._session = session or requests.Session()
        self._headers = {"User-Agent": _BROWSER_UA, "Content-Type": "application/json"}
        self._cache_path = Path(cache_path) if cache_path else None
        self._cache: dict[str, dict[str, Any] | None] = {}
        if self._cache_path and self._cache_path.exists():
            try:
                self._cache = json.loads(self._cache_path.read_text())
            except (ValueError, OSError):
                self._cache = {}
        self._src_ids: dict[str, int] | None = None

    # -- source registry -------------------------------------------------------------------
    def _source_ids(self) -> dict[str, int]:
        if self._src_ids is not None:
            return self._src_ids
        out: dict[str, int] = {}
        try:
            with force_ipv4():
                resp = self._session.get(
                    f"{_UNICHEM}/sources/", timeout=self._timeout, headers=self._headers
                )
            if resp.status_code == 200:
                body = resp.json()
                for src in body.get("sources", body if isinstance(body, list) else []):
                    short = _pick(src, "shortName", "name", "sourceName")
                    sid = _pick(src, "id", "sourceID", "src_id")
                    if short is not None and sid is not None:
                        out[str(short).lower()] = int(sid)
        except Exception:
            out = {}
        self._src_ids = out
        return out

    # -- compound lookup -------------------------------------------------------------------
    def _post_compounds(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        try:
            with force_ipv4():
                resp = self._session.post(
                    f"{_UNICHEM}/compounds",
                    json=payload,
                    timeout=self._timeout,
                    headers=self._headers,
                )
            if resp.status_code != 200:
                return None
            body = resp.json()
        except Exception:
            return None
        compounds = body.get("compounds") if isinstance(body, dict) else None
        if not compounds:
            return None
        c = compounds[0]
        uci = _pick(c, "uci", "UCI")
        block = _first_block(_pick(c, "standardInchiKey", "standardInChIKey", "inchikey"))
        sources: list[str] = []
        for s in _pick(c, "sources") or []:
            short = _pick(s, "shortName", "name", "src")
            local = _pick(s, "compoundId", "src_compound_id", "srcCompoundId")
            if short is None or local is None:
                continue
            prefix = {v: k for k, v in _PREFIX_TO_UNICHEM.items()}.get(str(short).lower())
            if prefix is None:
                continue
            norm = normalize_curie(f"{prefix}:{local}")
            if norm is not None:
                sources.append(norm)
        return {"uci": None if uci is None else str(uci), "block": block, "sources": sources}

    def lookup(self, curie: str) -> dict[str, Any] | None:
        """Resolve one CURIE to ``{uci, block, sources}`` (fail-soft ``None``); cached per CURIE."""
        norm = normalize_curie(curie)
        if norm is None:
            return None
        if norm in self._cache:
            return self._cache[norm]
        prefix, _, local = norm.partition(":")
        prefix = prefix.upper()
        rec: dict[str, Any] | None
        if prefix == "INCHIKEY":
            rec = self._post_compounds({"type": "inchikey", "compound": local})
        else:
            short = _PREFIX_TO_UNICHEM.get(prefix)
            sid = self._source_ids().get(short) if short else None
            rec = None if sid is None else self._post_compounds(
                {"type": "sourceID", "compound": local, "sourceID": sid}
            )
        self._cache[norm] = rec
        self._flush()
        return rec

    def _flush(self) -> None:
        if self._cache_path is None:
            return
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(json.dumps(self._cache))
        except OSError:
            pass

    def cache_stats(self) -> dict[str, int]:
        resolved = sum(1 for v in self._cache.values() if v is not None)
        return {"cached": len(self._cache), "resolved": resolved, "unresolved": len(self._cache) - resolved}


class IdEquivalenceJudge(Protocol):
    """Independent judge: are gold and prediction the same structure? None = needs-verification."""

    def uci_equivalent(self, gold: set[str], predicted: set[str]) -> bool | None: ...
    def block_equivalent(self, gold: set[str], predicted: set[str]) -> bool | None: ...


class UniChemIdEquivalenceJudge:
    """UniChem-backed judge. Variant (a) = UCI/sources; variant (b) = InChIKey first-block bridge.

    ``pubchem_resolver`` (optional) is the reused ``PubChemInChIKeyResolver`` — the fallback block
    source for ids UniChem cannot resolve (variant b only). It never touches the resolution path:
    it grades already-produced ids, never a name.
    """

    def __init__(self, client: UniChemClient, *, pubchem_resolver: Any | None = None) -> None:
        self._client = client
        self._pubchem = pubchem_resolver

    def uci_equivalent(self, gold: set[str], predicted: set[str]) -> bool | None:
        g_recs = [self._client.lookup(c) for c in gold]
        p_recs = [self._client.lookup(c) for c in predicted]
        g_ucis = {r["uci"] for r in g_recs if r and r.get("uci")}
        for r in p_recs:  # same UCI across namespaces
            if r and r.get("uci") and r["uci"] in g_ucis:
                return True
        # Cross-reference membership — symmetric: either the gold CURIE is in the prediction's
        # UniChem sources set, OR the prediction CURIE is in the gold's sources set. Both directions
        # are drawn from the SAME independent UniChem cross-references, so equivalence is symmetric;
        # checking both makes the verdict robust to which lookup resolved (fail-soft ordering).
        gold_norm = {c for c in (normalize_curie(x) for x in gold) if c is not None}
        pred_norm = {c for c in (normalize_curie(x) for x in predicted) if c is not None}
        for r in p_recs:  # gold ∈ prediction's cross-reference sources
            if r and any(s in gold_norm for s in r.get("sources", [])):
                return True
        for r in g_recs:  # prediction ∈ gold's cross-reference sources
            if r and any(s in pred_norm for s in r.get("sources", [])):
                return True
        if any(r is None for r in g_recs + p_recs):
            return None  # no positive match and something failed -> needs-verification
        return False

    def block_equivalent(self, gold: set[str], predicted: set[str]) -> bool | None:
        g_blocks, g_incomplete = self._blocks(gold)
        p_blocks, p_incomplete = self._blocks(predicted)
        if g_blocks & p_blocks:
            return True
        if g_incomplete or p_incomplete:
            return None
        return False

    def _blocks(self, curies: set[str]) -> tuple[set[str], bool]:
        blocks: set[str] = set()
        incomplete = False
        for c in curies:
            b = self._block_for(c)
            if b is None:
                incomplete = True
            else:
                blocks.add(b)
        return blocks, incomplete

    def _block_for(self, curie: str) -> str | None:
        rec = self._client.lookup(curie)
        if rec and rec.get("block"):
            return rec["block"]
        norm = normalize_curie(curie)
        if norm is None:
            return None
        prefix, _, local = norm.partition(":")
        prefix = prefix.upper()
        if prefix == "INCHIKEY":
            return _first_block(local)
        if self._pubchem is not None:
            if prefix == "PUBCHEM":
                return self._pubchem.block_for_pubchem(local)
            if prefix == "HMDB":
                return self._pubchem.block_for_hmdb(local)
        return None
