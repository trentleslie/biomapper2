"""Unit B — the KG-derived stability DESCRIPTOR (non-authoritative).

Verified against an independently hand-built fixture with known counts (NOT by reproducing this
session's scratch numbers, which would only prove determinism). The chemistry positive control runs on
REAL InChIKeys so the block2[:8] charge-invariant / stereo-sensitive claim is checked against actual
chemistry, not crafted strings. This descriptor must never gate — Unit C's KG-independent certificate is
the trust instrument.
"""

from __future__ import annotations

from studies.external_benchmarks.scorers.cross_cohort_overlap import (
    link_by_intersection,
    stability_descriptor_set,
)

# Real InChIKeys (glutamate family): block1 = WHUUTDBJXJRKMK; block2[:8] = VKHMYHEA for L, GSVOUGTG for D.
L_GLU_ACID = "WHUUTDBJXJRKMK-VKHMYHEASA-N"  # L-glutamic acid (neutral)
L_GLU_ANION = "WHUUTDBJXJRKMK-VKHMYHEASA-M"  # L-glutamate (charge form: only the final block differs)
D_GLU_ACID = "WHUUTDBJXJRKMK-GSVOUGTGSA-N"  # D-glutamic acid (stereoisomer: block2 differs)
UREA = "XSQUKJJJFZCRTK-UHFFFAOYSA-N"


def test_charge_forms_collapse_to_one_key():
    # acid vs anion of the same molecule share block1+block2[:8] -> one descriptor key (the whole point).
    acid = stability_descriptor_set("CHEBI:16015", {"INCHIKEY": [L_GLU_ACID]})
    anion = stability_descriptor_set("CHEBI:29987", {"INCHIKEY": [L_GLU_ANION]})
    assert acid == anion and len(acid) == 1


def test_stereoisomer_does_not_collapse():
    # Positive control: a real stereoisomer differs within block2[:8] -> a DISTINCT key (the descriptor
    # can fail to collapse; it is not charge-blind-everything).
    lglu = stability_descriptor_set("CHEBI:16015", {"INCHIKEY": [L_GLU_ACID]})
    dglu = stability_descriptor_set("CHEBI:15966", {"INCHIKEY": [D_GLU_ACID]})
    assert lglu != dglu and lglu.isdisjoint(dglu)


def test_independent_fixture_overlap_count():
    # Hand-built panels with KNOWN counts: glutamate(anion)<->glutamic-acid collapse; urea has no partner.
    necs = {
        "glutamate": stability_descriptor_set("CHEBI:29987", {"INCHIKEY": [L_GLU_ANION]}),
        "urea": stability_descriptor_set("CHEBI:16199", {"INCHIKEY": [UREA]}),
    }
    arivale = {"glutamic acid": stability_descriptor_set("CHEBI:16015", {"INCHIKEY": [L_GLU_ACID]})}
    ov = link_by_intersection(necs, arivale)
    assert ov.n_links == 1
    assert ov.links[0].a_name == "glutamate" and ov.links[0].b_name == "glutamic acid"
    assert ov.n_a_comparable == 2 and ov.n_b_comparable == 1


def test_no_inchikey_is_not_comparable():
    # A node with no InChIKey contributes no descriptor key (structurally uncomparable under this metric).
    assert stability_descriptor_set("CHEBI:16199", {"KEGG": ["C00086"]}) == frozenset()
