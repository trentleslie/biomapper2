"""Independent external resolver for the curator's HELD-OUT provided ids -> InChIKey first-block.

Oracle (b)'s GOLD side must NOT share infrastructure with the KG structure oracle that resolves
BioMapper's PREDICTION -- otherwise the "structural concordance" is circular (both sides resolved by
the same Kestrel KG). This resolves the curator's HMDB / PubChem provided id to an InChIKey first-
block via **PubChem PUG-REST**, an external source independent of the KG. It is:

  - CACHED (per (namespace, id); repeated ids across rows cost one call),
  - IPv4-FORCED (reuses the adapter's ``force_ipv4`` -- the desktop's IPv6->CDN route is flaky), and
  - FAIL-SOFT per id: any non-200 / network error / unparseable body yields ``None`` (cached) so the
    scorer marks that row ``needs-verification`` rather than silently dropping it or fabricating a
    block.

PubChem endpoints used (property/InChIKey, TXT for a single bare value):
  - PubChem CID:  ``/compound/cid/{cid}/property/InChIKey/TXT``
  - HMDB accession (xref RegistryID): ``/compound/xref/RegistryID/{hmdb}/property/InChIKey/TXT``
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ..adapters.metlinkr import force_ipv4

_PUG_REST = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"


def _first_block(inchikey: str | None) -> str | None:
    return inchikey.split("-")[0] if inchikey else None


class PubChemInChIKeyResolver:
    """Resolve a curator PubChem CID / HMDB accession -> InChIKey first-block via PUG-REST (external).

    Independent of the Kestrel KG oracle used for BioMapper's prediction (the whole point of oracle
    (b)'s independence). Cached + IPv4-forced + fail-soft (unresolved -> ``None``).
    """

    def __init__(self, *, timeout: float = 20.0, session: Any | None = None) -> None:
        import requests

        self._timeout = timeout
        self._session = session or requests.Session()
        self._cache: dict[str, str | None] = {}

    def _get_txt_inchikey(self, path: str) -> str | None:
        """GET a PUG-REST property/InChIKey/TXT path; return the first InChIKey block, or None.

        Fail-soft: a 404 (unknown id), any HTTP error, network failure, or empty body -> None.
        """
        url = f"{_PUG_REST}/{path}"
        try:
            with force_ipv4():
                resp = self._session.get(url, timeout=self._timeout)
            if resp.status_code != 200:
                return None
            first_line = resp.text.strip().splitlines()[0].strip() if resp.text.strip() else ""
            return _first_block(first_line) if first_line else None
        except Exception:
            return None

    def block_for_pubchem(self, cid: str) -> str | None:
        key = f"pubchem:{cid}"
        if key in self._cache:
            return self._cache[key]
        block = self._get_txt_inchikey(f"compound/cid/{quote(cid)}/property/InChIKey/TXT")
        self._cache[key] = block
        return block

    def block_for_hmdb(self, hmdb: str) -> str | None:
        key = f"hmdb:{hmdb}"
        if key in self._cache:
            return self._cache[key]
        block = self._get_txt_inchikey(f"compound/xref/RegistryID/{quote(hmdb)}/property/InChIKey/TXT")
        self._cache[key] = block
        return block
