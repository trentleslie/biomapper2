"""Unit C — KG-independent certificate scorer (the TRUST metric). Pure/offline: keys passed directly.

Positive controls prove the certificate can FAIL: a wrong-molecule link is refuted, a stereoisomer is
refuted, and a link with no independent structure on a side is refused (never certified off the KG).
"""

from __future__ import annotations

from studies.external_benchmarks.scorers.cross_cohort_overlap import Link
from studies.external_benchmarks.scorers.independent_link_certificate_overlap import certify_links

L_GLU = "WHUUTDBJXJRKMK-VKHMYHEASA-N"  # L-glutamic acid
D_GLU = "WHUUTDBJXJRKMK-GSVOUGTGSA-N"  # D-glutamic acid (stereoisomer: block2 differs)
UREA = "XSQUKJJJFZCRTK-UHFFFAOYSA-N"  # urea (different connectivity)


def _link(a, b):
    return Link(a_name=a, b_name=b, shared=frozenset())


def test_agreeing_independent_structures_certify():
    ov = certify_links([_link("glutamate", "glutamic acid")], {"glutamate": L_GLU}, {"glutamic acid": L_GLU})
    assert ov.certified == 1 and ov.refuted == 0 and ov.refused == 0
    assert ov.certified_rate == 1.0


def test_wrong_molecule_link_is_refuted():
    # Positive control: connectivity disagrees -> refuted (the certificate can fail).
    ov = certify_links([_link("glutamate", "urea")], {"glutamate": L_GLU}, {"urea": UREA})
    assert ov.refuted == 1 and ov.certified == 0
    assert ov.certified_rate == 0.0


def test_stereoisomer_link_is_refuted():
    ov = certify_links([_link("l-glu", "d-glu")], {"l-glu": L_GLU}, {"d-glu": D_GLU})
    assert ov.refuted == 1 and ov.certified == 0


def test_missing_independent_structure_is_refused_and_excluded():
    # No independent structure on the cohort side -> refused, and excluded from the certified rate.
    ov = certify_links(
        [_link("glutamate", "mystery"), _link("glutamate", "glutamic acid")],
        {"glutamate": L_GLU},
        {"mystery": None, "glutamic acid": L_GLU},
    )
    assert ov.refused == 1 and ov.certified == 1
    assert ov.adjudicable == 1 and ov.certified_rate == 1.0  # refused not in the denominator


def test_empty_link_set_has_no_false_precision():
    ov = certify_links([], {}, {})
    assert ov.certified == 0 and ov.certified_rate is None
