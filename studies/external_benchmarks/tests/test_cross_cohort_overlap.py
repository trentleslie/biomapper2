"""Unit 2 — cross-cohort overlap scorer (offline, mock CURIE sets, no mapper/KG)."""

from __future__ import annotations

from studies.external_benchmarks.scorers.cross_cohort_overlap import (
    curie_set,
    link_by_intersection,
)


def test_shared_curie_links_disjoint_does_not():
    a = {"glucose": curie_set("CHEBI:17234", "KEGG:C00031")}
    b = {"glc": curie_set("KEGG:C00031", None), "urea": curie_set("CHEBI:16199", None)}
    res = link_by_intersection(a, b)
    assert res.n_links == 1
    assert res.links[0].a_name == "glucose" and res.links[0].b_name == "glc"
    assert "KEGG:C00031" in res.links[0].shared


def test_canonicalization_positive_control():
    # KEGG.COMPOUND folds to KEGG → links; KEGG.GLYCAN is a different id space → does NOT link.
    a = {"m": curie_set("KEGG.COMPOUND:C00031", None)}
    b_link = {"n": curie_set("KEGG:C00031", None)}
    b_nolink = {"n": curie_set("KEGG.GLYCAN:G00031", None)}
    assert link_by_intersection(a, b_link).n_links == 1
    assert link_by_intersection(a, b_nolink).n_links == 0


def test_empty_curie_set_never_links():
    a = {"unresolved": curie_set("", None)}
    b = {"glc": curie_set("KEGG:C00031", None)}
    res = link_by_intersection(a, b)
    assert res.n_links == 0
    assert res.n_a_comparable == 0  # unresolved row is not comparable — a refusal candidate


def test_comparable_denominator_counts_resolved_rows_only():
    a = {"x": curie_set("CHEBI:1", None), "y": curie_set("", None)}
    b = {"p": curie_set("CHEBI:1", None), "q": curie_set("", "")}
    res = link_by_intersection(a, b)
    assert res.n_a_comparable == 1 and res.n_b_comparable == 1


def test_multiple_shared_curies_yield_one_link_with_all():
    a = {"m": curie_set("CHEBI:17234", "KEGG:C00031")}
    b = {"n": curie_set("CHEBI:17234", "KEGG:C00031")}
    res = link_by_intersection(a, b)
    assert res.n_links == 1
    assert res.links[0].shared == frozenset({"CHEBI:17234", "KEGG:C00031"})


def test_one_a_links_multiple_b():
    a = {"m": curie_set("CHEBI:1", None)}
    b = {"p": curie_set("CHEBI:1", None), "q": curie_set("CHEBI:1", None)}
    res = link_by_intersection(a, b)
    assert res.n_links == 2 and res.n_a_linked == 1 and res.n_b_linked == 2


def test_curie_set_splits_equivalents_and_drops_empties():
    s = curie_set("CHEBI:17234", "KEGG:C00031|PUBCHEM.COMPOUND:5793|")
    assert s == frozenset({"CHEBI:17234", "KEGG:C00031", "PUBCHEM:5793"})


def test_no_links_when_both_sides_empty():
    res = link_by_intersection({"a": curie_set("", None)}, {"b": curie_set(None, None)})
    assert res.n_links == 0 and res.n_a_linked == 0 and res.n_b_linked == 0
