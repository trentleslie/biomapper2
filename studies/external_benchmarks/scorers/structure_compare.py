"""Structure-comparison primitives for the NECS gold repair (Unit 3).

Reusable, independently testable RDKit operations the gold-repair classifier composes, so the
classifier holds decision logic rather than RDKit mechanics.

Every primitive returns an explicit ``None`` on unparseable/absent input — never ``""`` or a
falsy default that would compare equal to another failure. The comparison helpers are tri-state:
``True`` / ``False`` / ``None`` (undecidable, because a side could not be parsed).

CAVEATS proven on the NECS known-answer rows (do NOT treat canonicalization as an arbiter of
molecular identity):
  * ``Uncharger`` cannot neutralize quaternary ammonium (choline stays cationic).
  * ``TautomerEnumerator`` does NOT collapse ring-chain sugar interconversion (xylose) and CAN
    over-merge genuine regioisomers (gamma-glutamylvaline).
So ``same_canonical`` is a corroborating signal, not the decider for Kind-B rows; the classifier
uses an independent name/CID anchor for those.
"""

from __future__ import annotations

from rdkit import Chem, RDLogger
from rdkit.Chem import rdMolDescriptors
from rdkit.Chem.MolStandardize import rdMolStandardize

RDLogger.DisableLog("rdApp.*")

_TAUTOMER = rdMolStandardize.TautomerEnumerator()
_UNCHARGER = rdMolStandardize.Uncharger()


def parse(smiles: str | None) -> Chem.Mol | None:
    """SMILES -> Mol, or None if absent/blank/unparseable (never raises)."""
    if smiles is None:
        return None
    s = str(smiles).strip()
    if not s:
        return None
    return Chem.MolFromSmiles(s)


def _key(mol: Chem.Mol | None) -> str | None:
    if mol is None:
        return None
    try:
        return Chem.MolToInchiKey(mol)
    except Exception:
        return None


def standard_inchikey(smiles: str | None) -> str | None:
    """Full standard three-block InChIKey from a SMILES, or None."""
    return _key(parse(smiles))


def connectivity(smiles: str | None) -> str | None:
    """First block (connectivity layer) of the standard InChIKey, or None."""
    key = standard_inchikey(smiles)
    return key.split("-")[0] if key else None


def stereo_layer(smiles: str | None) -> str | None:
    """Second block (stereo/sp3 layer) of the standard InChIKey, or None."""
    key = standard_inchikey(smiles)
    parts = key.split("-") if key else []
    return parts[1] if len(parts) > 1 else None


def formula(smiles: str | None) -> str | None:
    """Hill molecular formula, or None."""
    mol = parse(smiles)
    return rdMolDescriptors.CalcMolFormula(mol) if mol is not None else None


def canonical_mol(smiles: str | None) -> Chem.Mol | None:
    """Uncharge then tautomer-canonicalize, so protonation/tautomer encoding is normalized away.

    Returns None on parse or canonicalization failure. NOT a molecular-identity arbiter (see
    module docstring caveats).
    """
    mol = parse(smiles)
    if mol is None:
        return None
    try:
        return _TAUTOMER.Canonicalize(_UNCHARGER.uncharge(mol))
    except Exception:
        return None


def canonical_connectivity(smiles: str | None) -> str | None:
    """Connectivity block of the uncharged, tautomer-canonicalized structure, or None."""
    return connectivity(Chem.MolToSmiles(canonical_mol(smiles))) if canonical_mol(smiles) else None


def _tri(a: str | None, b: str | None) -> bool | None:
    """Equality that is None (undecidable) if either side is None — never silently equal."""
    if a is None or b is None:
        return None
    return a == b


def same_connectivity(a: str | None, b: str | None) -> bool | None:
    return _tri(connectivity(a), connectivity(b))


def same_stereo(a: str | None, b: str | None) -> bool | None:
    return _tri(stereo_layer(a), stereo_layer(b))


def same_formula(a: str | None, b: str | None) -> bool | None:
    return _tri(formula(a), formula(b))


def same_canonical(a: str | None, b: str | None) -> bool | None:
    """Same connectivity AFTER uncharge + tautomer canonicalization (encoding normalized away)."""
    return _tri(canonical_connectivity(a), canonical_connectivity(b))
