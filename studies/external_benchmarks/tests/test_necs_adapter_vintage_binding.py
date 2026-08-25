"""NECS adapter vintage binding (Unit 2).

The MOESM5 file ships TWO annotation vintages whose headers collide only by case:
legacy ``INCHIKEY``/``SMILES`` and modern ``inchi_key``/``smiles`` (+ ``formula``,
``exactmass``). The old ``_resolve_column`` lower-cased headers into a dict where the LAST
colliding column won, so ``gold_smiles`` silently bound the *modern* ``smiles`` while
``gold_inchikey`` bound the *legacy* ``INCHIKEY`` — a cross-vintage pairing. These tests pin
each logical role to its intended physical column so that regression is caught.
"""

from __future__ import annotations

import pandas as pd

from studies.external_benchmarks.adapters.necs_metabolon import build_card, build_input_df
from studies.external_benchmarks.config import NECS

# Legacy and modern carry DISTINCT strings so the binding is observable, not inferred.
_LEGACY_SMILES = "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O"
_MODERN_SMILES = "OC[C@@H]1OC(O)[C@@H](O)[C@H](O)[C@H]1O"
_LEGACY_KEY = "WQZGKKKJIJFFOK-GASJEMHNSA-N"  # two-block legacy form in the real file
_MODERN_KEY = "WQZGKKKJIJFFOK-DVKNGEFBSA-N"  # standard three-block form


def _two_vintage_df() -> pd.DataFrame:
    """A frame carrying both vintages, as the real MOESM5 does."""
    return pd.DataFrame(
        {
            "CHEMICAL_NAME": ["glucose", "caffeine"],
            "INCHIKEY": [_LEGACY_KEY, "RYYVLZVUVIJVGH-UHFFFAOYAK"],
            "SMILES": [_LEGACY_SMILES, "Cn1cnc2c1c(=O)n(C)c(=O)n2C"],
            "inchi_key": [_MODERN_KEY, "RYYVLZVUVIJVGH-UHFFFAOYSA-N"],
            "smiles": [_MODERN_SMILES, "Cn1cnc2n(C)c(=O)n(C)c(=O)c12"],
            "formula": ["C6H12O6", "C8H10N4O2"],
            "exactmass": ["180.0634", "194.0804"],
        }
    )


def test_gold_smiles_binds_legacy_not_modern():
    """THE FIX: gold_smiles must pair with the legacy gold_inchikey, not the modern smiles."""
    out = build_input_df(_two_vintage_df(), NECS)
    assert out["gold_smiles"].iloc[0] == _LEGACY_SMILES
    assert out["gold_smiles"].iloc[0] != _MODERN_SMILES
    assert out["gold_inchikey"].iloc[0] == _LEGACY_KEY


def test_modern_vintage_columns_are_bound():
    """The classifier needs the modern vintage addressable separately."""
    out = build_input_df(_two_vintage_df(), NECS)
    assert out["gold_inchikey_standard"].iloc[0] == _MODERN_KEY
    assert out["gold_smiles_standard"].iloc[0] == _MODERN_SMILES
    assert out["gold_formula"].iloc[0] == "C6H12O6"
    assert out["gold_exactmass"].iloc[0] == "180.0634"


def test_binding_follows_header_not_position_positive_control():
    """Swapping the two SMILES columns must swap the binding — proves it reads the header."""
    df = _two_vintage_df()
    df = df.rename(columns={"SMILES": "_tmp", "smiles": "SMILES"}).rename(columns={"_tmp": "smiles"})
    out = build_input_df(df, NECS)
    # gold_smiles follows the "SMILES" header, which now holds the modern string.
    assert out["gold_smiles"].iloc[0] == _MODERN_SMILES
    assert out["gold_smiles_standard"].iloc[0] == _LEGACY_SMILES


def test_single_smiles_delivery_still_binds():
    """A delivery with only one SMILES column (older Metabolon) binds it unambiguously."""
    df = _two_vintage_df().drop(columns=["smiles", "inchi_key", "formula", "exactmass"])
    out = build_input_df(df, NECS)
    assert out["gold_smiles"].iloc[0] == _LEGACY_SMILES
    assert out["gold_smiles_standard"].iloc[0] == ""  # modern absent -> honest empty
    assert out["gold_formula"].iloc[0] == ""


def test_card_reports_both_vintages_distinctly():
    """Coverage must distinguish the two SMILES columns, not collapse them to one number."""
    card = build_card(_two_vintage_df(), "deadbeef", NECS)
    cov = card["coverage"]
    assert cov["SMILES"]["n"] == 2  # legacy
    assert cov["smiles"]["n"] == 2  # modern
    assert cov["formula"]["n"] == 2
