"""Structure-comparison primitives (Unit 3).

Reusable RDKit operations the gold-repair classifier composes. Every primitive returns an
explicit ``None`` on unparseable/absent input — never a falsy default that would compare equal
to another failure — and the comparison helpers are tri-state (True / False / None).
"""

from __future__ import annotations

from studies.external_benchmarks.scorers import structure_compare as sc

_GLUCOSE = "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O"
_FRUCTOSE = "OCC1(O)OC[C@@H](O)[C@@H](O)[C@H]1O"  # C6H12O6 like glucose, different connectivity
_D_ALA = "C[C@H](C(=O)O)N"
_L_ALA = "C[C@@H](C(=O)O)N"
_ACETATE = "CC(=O)[O-]"
_ACETIC = "CC(=O)O"


def test_standard_inchikey_and_connectivity_happy():
    key = sc.standard_inchikey(_GLUCOSE)
    assert key is not None and key.startswith("WQZGKKKJIJFFOK")
    assert sc.connectivity(_GLUCOSE) == "WQZGKKKJIJFFOK"


def test_charge_neutralization_collapses_conjugate_pair():
    """Uncharger neutralizes a carboxylate to its acid — same canonical form."""
    assert sc.same_canonical(_ACETATE, _ACETIC) is True


def test_formula_identical_different_molecule_stays_distinct():
    """Glucose vs fructose: same formula, different molecule — canonicalization must NOT merge them.

    This is the over-merge control: if the tautomer canonicalizer collapsed these, a real
    wrong-molecule defect would be silently relabelled an encoding artifact.
    """
    assert sc.same_formula(_GLUCOSE, _FRUCTOSE) is True
    assert sc.same_connectivity(_GLUCOSE, _FRUCTOSE) is False
    assert sc.same_canonical(_GLUCOSE, _FRUCTOSE) is False


def test_stereo_only_difference():
    """D- vs L-alanine: same connectivity, different stereo layer."""
    assert sc.same_connectivity(_D_ALA, _L_ALA) is True
    assert sc.same_stereo(_D_ALA, _L_ALA) is False


def test_unparseable_returns_none_never_falsy():
    assert sc.parse("$$notsmiles$$") is None
    assert sc.standard_inchikey("$$notsmiles$$") is None
    assert sc.connectivity("$$notsmiles$$") is None
    assert sc.formula("$$notsmiles$$") is None


def test_empty_distinct_from_unparseable_and_comparisons_are_none():
    assert sc.parse("") is None
    # Two failures must NOT compare equal — comparison is undecidable (None), not True/False.
    assert sc.same_connectivity("$$bad$$", _GLUCOSE) is None
    assert sc.same_canonical(_GLUCOSE, "") is None
    assert sc.same_formula("", "$$bad$$") is None


def test_stereo_layer_none_stereo_molecule_self_equal():
    """A molecule with no stereocentres has a stable stereo layer that equals itself."""
    assert sc.same_stereo(_ACETIC, _ACETIC) is True
