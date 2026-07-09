"""Tests for source-weighted small-molecule ChEBI resolution (no live APIs)."""

from unittest.mock import MagicMock

import pandas as pd

from biomapper2.core.resolver import Resolver


def _resolver(conn_result):
    """Resolver whose connectivity_match returns a fixed value; small-molecule=True."""
    r = Resolver(linker=MagicMock(), biolink_client=MagicMock())
    r.structure_resolver = MagicMock()
    r.structure_resolver.connectivity_match.return_value = conn_result
    r._is_small_molecule = lambda category: category == "biolink:SmallMolecule"
    return r


ASSIGNED = {"metabolomics-workbench": {"CHEBI:refmet": ["RM:1"]}}  # RefMet-anchored node
# BioMapper's node wins the naive vote (more supporting curies).
KG_IDS = {"CHEBI:bmp": ["a", "b"], "CHEBI:refmet": ["RM:1"]}


def test_same_connectivity_flips_to_refmet_silently():
    chosen, flag = _resolver(True)._choose_best_kg_id(KG_IDS, ASSIGNED, "biolink:SmallMolecule")
    assert (chosen, flag) == ("CHEBI:refmet", None)


def test_different_connectivity_flips_to_refmet_with_flag():
    chosen, flag = _resolver(False)._choose_best_kg_id(KG_IDS, ASSIGNED, "biolink:SmallMolecule")
    assert (chosen, flag) == ("CHEBI:refmet", "divergent_refmet")


def test_no_inchikey_keeps_majority_with_flag():
    chosen, flag = _resolver(None)._choose_best_kg_id(KG_IDS, ASSIGNED, "biolink:SmallMolecule")
    assert (chosen, flag) == ("CHEBI:bmp", "conflict_no_structure")


def test_no_conflict_refmet_equals_majority_unchanged():
    kg = {"CHEBI:refmet": ["a", "b"]}
    chosen, flag = _resolver(False)._choose_best_kg_id(kg, ASSIGNED, "biolink:SmallMolecule")
    assert (chosen, flag) == ("CHEBI:refmet", None)


def test_non_metabolite_unchanged():
    r = _resolver(False)
    r._is_small_molecule = lambda category: False
    chosen, flag = r._choose_best_kg_id(KG_IDS, ASSIGNED, "biolink:Disease")
    assert (chosen, flag) == ("CHEBI:bmp", None)  # plain majority, byte-identical


def test_no_refmet_vote_unchanged():
    chosen, flag = _resolver(False)._choose_best_kg_id(KG_IDS, {"other": {"CHEBI:x": ["c"]}}, "biolink:SmallMolecule")
    assert (chosen, flag) == ("CHEBI:bmp", None)


def test_empty_returns_none():
    assert _resolver(False)._choose_best_kg_id({}, ASSIGNED, "biolink:SmallMolecule") == (None, None)


def test_resolve_series_carries_review_field():
    r = _resolver(False)
    entity = pd.Series({"kg_ids": KG_IDS, "kg_ids_provided": {}, "kg_ids_assigned": ASSIGNED})
    out = r.resolve(entity, category="biolink:SmallMolecule")
    assert out["chosen_kg_id"] == "CHEBI:refmet"
    assert out["chosen_kg_id_review"] == "divergent_refmet"
