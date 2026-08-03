"""Unit 2 - NEUTRAL structure resolution (never BioMapper).

The model is asked to emit, per referent, any of: a direct InChIKey, a SMILES,
or a chemical name. We turn each into a full InChIKey using only third-party
resolvers, in this precedence:

1. ``inchikey``  - validate the 27-char pattern; use as-is (no lookup).
2. ``smiles``    - RDKit MolToInchiKey (OFFLINE, deterministic). This mirrors
                   exactly what the terminal agent would do under ``no-network``
                   (draw the structure, compute the key with RDKit), so it keeps
                   the naive probe a fair lower bound rather than a hash-recall
                   test.
3. ``name``      - PubChem PUG-REST name -> CID -> InChIKey (network). Cached.

Grading a BioMapper-adjacent task with BioMapper is circular; none of these
paths touch BioMapper. Every referent records which lane resolved it (or that it
was ungradeable); the unresolved-rate is reported, and ungradeable != failure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

# Full InChIKey: 14 upper-alpha (connectivity) '-' 10 upper-alpha (8 structure +
# standard-InChI flag + version) '-' 1 protonation char.
# e.g. WQZGKKKJIJFFOK-GASJEMHNSA-N
_INCHIKEY_RE = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")


class Lane(str, Enum):
    INCHIKEY = "inchikey_direct"
    SMILES = "smiles_rdkit"
    NAME = "name_pubchem"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class Resolved:
    """One emitted referent resolved (or not) to a full InChIKey."""

    inchikey: str | None
    lane: Lane
    raw: dict  # the {inchikey?, smiles?, name?} the model emitted, for audit


def is_valid_inchikey(value: str | None) -> bool:
    return bool(value) and bool(_INCHIKEY_RE.match(value.strip()))


def first_block(inchikey: str | None) -> str | None:
    """2-D connectivity skeleton (first InChIKey block). None if absent/blank.

    Kept local (not imported from the KG scorer) so this module has zero coupling
    to the BioMapper-facing scorers.
    """
    if not inchikey:
        return None
    s = str(inchikey).strip()
    if not s or s.lower() == "nan":
        return None
    return s.split("-")[0]


def smiles_to_inchikey(smiles: str) -> str | None:
    """Offline, deterministic. Returns None on an unparseable SMILES."""
    try:
        from rdkit import Chem
        from rdkit.rdBase import BlockLogs
    except ImportError:  # rdkit is a project dep; guard so the module imports bare
        return None
    with BlockLogs():
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None
        key = Chem.MolToInchiKey(mol)
    return key or None


class PubChemResolver:
    """name -> CID -> InChIKey via PUG-REST. Neutral third party; cached.

    Network-touching; injected so the offline test suite can pass a fake. Uses
    requests-cache (already a project dep) when available so repeated / re-run
    lookups are free and deterministic.
    """

    BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"

    def __init__(self, *, timeout: float = 20.0, session=None) -> None:
        self.timeout = timeout
        if session is not None:
            self._session = session
        else:
            try:
                import requests_cache

                self._session = requests_cache.CachedSession(
                    "pham_ambname_pubchem", backend="sqlite", expire_after=None
                )
            except ImportError:
                import requests

                self._session = requests.Session()

    def name_to_inchikey(self, name: str) -> str | None:
        import urllib.parse

        q = urllib.parse.quote(name.strip())
        url = f"{self.BASE}/compound/name/{q}/property/InChIKey/JSON"
        try:
            r = self._session.get(url, timeout=self.timeout)
            if r.status_code != 200:
                return None
            props = r.json()["PropertyTable"]["Properties"]
        except Exception:
            return None
        if not props:
            return None
        key = props[0].get("InChIKey")
        return key if is_valid_inchikey(key) else None


def resolve_referent(raw: dict, *, pubchem: PubChemResolver | None) -> Resolved:
    """Resolve one emitted referent via the neutral-lane precedence."""
    ik = raw.get("inchikey")
    if is_valid_inchikey(ik):
        return Resolved(inchikey=ik.strip(), lane=Lane.INCHIKEY, raw=raw)

    smiles = raw.get("smiles")
    if smiles:
        key = smiles_to_inchikey(smiles.strip())
        if is_valid_inchikey(key):
            return Resolved(inchikey=key, lane=Lane.SMILES, raw=raw)

    name = raw.get("name")
    if name and pubchem is not None:
        key = pubchem.name_to_inchikey(name)
        if is_valid_inchikey(key):
            return Resolved(inchikey=key, lane=Lane.NAME, raw=raw)

    return Resolved(inchikey=None, lane=Lane.UNRESOLVED, raw=raw)
