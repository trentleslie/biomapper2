"""Unit 2 - NEUTRAL sum-composition reference + structure normalisation.

Two neutral, third-party paths — NEVER BioMapper (grading a BioMapper-adjacent task
with BioMapper is circular):

* NAME -> species-level components + sum formula, via **pygoslin** (the LIPID MAPS
  shorthand grammar). This is the answer key at the resolution the shorthand
  specifies, and the basis of the gold-quality gate.
* STRUCTURE -> molecular formula + InChIKey, via **RDKit** (offline, deterministic).
  This mirrors exactly what a ``no-network`` terminal agent would do with the model's
  proposed SMILES.

Both external libs are imported lazily and injected as callables, so this module (and
the offline test suite) imports and is testable without pygoslin/rdkit installed. The
pure helpers (``normalize_formula``, ``first_block``, ``is_valid_inchikey``) carry the
logic that the tests pin.

NOTE — pygoslin API surface: the exact accessor names on ``LipidAdduct`` (sum formula,
species string, ``LipidSpeciesInfo`` carbon/double-bond counts) are validated against
the installed pygoslin at run time; ``default_goslin_parse`` is best-effort and
degrades to ``parsed=False`` (row => ungradeable) on any accessor mismatch. Confirm the
parse-coverage rate printed by the run before trusting it (a run-prereq, see the spec).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_INCHIKEY_RE = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")
# Element token in a molecular formula, e.g. "C60", "H102", "O6", "N".
_ELEM_RE = re.compile(r"([A-Z][a-z]?)(\d*)")


@dataclass(frozen=True)
class ShorthandParse:
    """The neutral species-level reading of one shorthand (pygoslin)."""

    name: str
    parsed: bool
    lipid_class: str | None = None
    total_carbons: int | None = None
    total_double_bonds: int | None = None
    formula: str | None = None  # normalised Hill string
    species_string: str | None = None


# --- pure helpers -------------------------------------------------------------


def is_valid_inchikey(value: str | None) -> bool:
    return bool(value) and bool(_INCHIKEY_RE.match(value.strip()))


def first_block(inchikey: str | None) -> str | None:
    """2-D connectivity skeleton (first InChIKey block). None if absent/blank."""
    if not inchikey:
        return None
    s = str(inchikey).strip()
    if not s or s.lower() == "nan":
        return None
    return s.split("-")[0]


def normalize_formula(formula: str | None) -> str | None:
    """Canonicalise a molecular formula to a comparable Hill string.

    Strips charge annotations and whitespace, sums element counts, re-serialises in
    Hill order (C, H, then alphabetical). Makes ``C60H102O6``, ``C60 H102 O6`` and a
    charge-suffixed variant compare equal at the composition level. Returns None if no
    element tokens are found.
    """
    if not formula:
        return None
    # drop anything after a charge marker and any brackets/whitespace
    core = re.sub(r"[\[\]\s]", "", str(formula))
    core = re.split(r"[+\-]", core)[0] if core and core[0].isalpha() else core
    counts: dict[str, int] = {}
    found = False
    for elem, num in _ELEM_RE.findall(core):
        if not elem:
            continue
        found = True
        counts[elem] = counts.get(elem, 0) + (int(num) if num else 1)
    if not found:
        return None
    parts: list[str] = []
    for e in ("C", "H"):
        if e in counts:
            parts.append(e + (str(counts[e]) if counts[e] != 1 else ""))
    for e in sorted(k for k in counts if k not in ("C", "H")):
        parts.append(e + (str(counts[e]) if counts[e] != 1 else ""))
    return "".join(parts)


# --- injectable external adapters (lazy imports) ------------------------------


def default_formula_from_smiles(smiles: str) -> str | None:
    """RDKit: SMILES -> normalised molecular formula. None on unparseable SMILES."""
    try:
        from rdkit import Chem
        from rdkit.Chem import rdMolDescriptors
        from rdkit.rdBase import BlockLogs
    except ImportError:
        return None
    with BlockLogs():
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None
        raw = rdMolDescriptors.CalcMolFormula(mol)
    return normalize_formula(raw)


def default_inchikey_from_smiles(smiles: str) -> str | None:
    """RDKit: SMILES -> full InChIKey. None on unparseable SMILES."""
    try:
        from rdkit import Chem
        from rdkit.rdBase import BlockLogs
    except ImportError:
        return None
    with BlockLogs():
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None
        key = Chem.MolToInchiKey(mol)
    return key or None


# Neutral head-group SMARTS for the common glycero/phospho/glycerolipid classes.
# Chemistry only (no BioMapper). Keyed by a normalised class token; used ONLY as a
# secondary collision signal (formula-pass that fails this => same formula, wrong class).
# Uncovered classes return None (no signal), never a hard fail.
CLASS_SMARTS: dict[str, str] = {
    "pc": "[N+](C)(C)(C)CCOP",           # phosphocholine head
    "pe": "NCCOP(=O)(O)O",                # phosphoethanolamine head
    "ps": "OC(=O)C(N)COP",                # phosphoserine head
    "pg": "OCC(O)COP(=O)(O)O",            # phosphoglycerol head
    "pi": "OC1C(O)C(O)C(O)C(O)C1OP",      # phosphoinositol head (ring)
    "pa": "OP(=O)(O)OCC(O)CO",            # phosphatidic acid glycerol-phosphate
    "tg": "C(COC(=O))(OC(=O))COC(=O)",    # glycerol tri-ester backbone
    "dg": "C(CO)(OC(=O))COC(=O)",         # glycerol di-ester backbone
    "mg": "OCC(O)COC(=O)",                # glycerol mono-ester backbone
    "cer": "C(CO)(NC(=O))C(O)",           # ceramide sphingoid+amide core
    "sm": "[N+](C)(C)(C)CCOP(=O)([O-])OCC(NC(=O))C(O)",  # sphingomyelin
    "fa": "C(=O)O",                       # carboxylic acid (weak; fatty acid)
}


def class_backbone_ok(smiles: str, lipid_class: str | None, *, matcher=None) -> bool | None:
    """Secondary: does the model's structure contain the class-defining substructure?

    Returns True/False when the class is covered by ``CLASS_SMARTS``, else None (no
    signal). ``matcher`` is injectable for offline tests; default uses RDKit.
    """
    if not smiles or not lipid_class:
        return None
    key = re.sub(r"[^a-z]", "", lipid_class.strip().lower())
    smarts = CLASS_SMARTS.get(key)
    if smarts is None:
        return None
    fn = matcher or _default_smarts_match
    return fn(smiles, smarts)


def _default_smarts_match(smiles: str, smarts: str) -> bool | None:
    try:
        from rdkit import Chem
        from rdkit.rdBase import BlockLogs
    except ImportError:
        return None
    with BlockLogs():
        mol = Chem.MolFromSmiles(smiles)
        patt = Chem.MolFromSmarts(smarts)
        if mol is None or patt is None:
            return None
        return mol.HasSubstructMatch(patt)


def default_goslin_parse(name: str) -> ShorthandParse:
    """pygoslin: shorthand -> species-level components + sum formula (neutral).

    Best-effort against the installed pygoslin; any import/parse/accessor failure
    degrades to ``parsed=False`` so the row is treated as ungradeable rather than
    silently mis-scored.
    """
    try:
        from pygoslin.parser.Parser import LipidParser
        from pygoslin.domain.LipidLevel import LipidLevel
    except ImportError:
        return ShorthandParse(name=name, parsed=False)
    try:
        adduct = LipidParser().parse(name)
    except Exception:
        return ShorthandParse(name=name, parsed=False)
    if adduct is None:
        return ShorthandParse(name=name, parsed=False)

    formula = None
    for meth in ("get_sum_formula", "sum_formula"):
        fn = getattr(adduct, meth, None)
        if callable(fn):
            try:
                formula = fn()
                break
            except Exception:
                formula = None
    species = None
    try:
        species = adduct.get_lipid_string(LipidLevel.SPECIES)
    except Exception:
        species = None

    lipid = getattr(adduct, "lipid", None)
    lipid_class = None
    total_c = None
    total_db = None
    if lipid is not None:
        info = getattr(lipid, "info", None)
        if info is not None:
            total_c = getattr(info, "num_carbon", None)
            db = getattr(info, "double_bonds", None)
            # double_bonds may be an int or an object with a count
            total_db = db if isinstance(db, int) else getattr(db, "num_double_bonds", None)
    # pygoslin's headgroup accessor is version-dependent and often None here; the class
    # token is the reliable prefix of the SPECIES string (e.g. "TG 57:6" -> "TG",
    # "Hex(4)-HexNAc-Cer 36:1;O2" -> "Hex(4)-HexNAc-Cer").
    if species:
        lipid_class = species.split(" ")[0] or None

    return ShorthandParse(
        name=name,
        parsed=True,
        lipid_class=lipid_class,
        total_carbons=total_c,
        total_double_bonds=total_db,
        formula=normalize_formula(formula),
        species_string=species,
    )
