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
    assert isinstance(out, pd.Series)  # single entity -> Series (narrows type for the asserts below)
    assert out["chosen_kg_id"] == "CHEBI:refmet"
    assert out["chosen_kg_id_review"] == "divergent_refmet"


# --------------------------- Deterministic RefMet pick (D4) ---------------------------
# RefMet contributing >1 KG node is itself a signal, so the pick must not depend on dict insertion
# order (which follows API response order). Counted over the pinned baseline: 8,814 rows carry a
# metabolomics-workbench vote and 0 contributed more than one node, so this is a provable no-op on
# every A/B row — reproducibility hardening, not a behaviour change. It is a *determinism* fix, not a
# correctness one: lexicographic order is still chemically arbitrary, hence the warning.

MULTI_ASSIGNED_A = {"metabolomics-workbench": {"CHEBI:refmet_b": ["RM:2"], "CHEBI:refmet_a": ["RM:1"]}}
MULTI_ASSIGNED_B = {"metabolomics-workbench": {"CHEBI:refmet_a": ["RM:1"], "CHEBI:refmet_b": ["RM:2"]}}


def test_multi_node_refmet_pick_is_order_independent():
    """Two insertion orders of the same RefMet node set must resolve to the same node."""
    kg = {"CHEBI:bmp": ["a", "b"], "CHEBI:refmet_a": ["RM:1"], "CHEBI:refmet_b": ["RM:2"]}
    first = _resolver(True)._choose_best_kg_id(kg, MULTI_ASSIGNED_A, "biolink:SmallMolecule")
    second = _resolver(True)._choose_best_kg_id(kg, MULTI_ASSIGNED_B, "biolink:SmallMolecule")
    assert first == second == ("CHEBI:refmet_a", None)


def test_multi_node_refmet_is_warned_so_it_can_be_surfaced():
    """The multi-node case does not occur in today's data; if it appears it needs a real tiebreak rule."""
    import logging

    kg = {"CHEBI:bmp": ["a", "b"], "CHEBI:refmet_a": ["RM:1"], "CHEBI:refmet_b": ["RM:2"]}
    logger = logging.getLogger()
    records = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    logger.addHandler(handler)
    try:
        _resolver(True)._choose_best_kg_id(kg, MULTI_ASSIGNED_A, "biolink:SmallMolecule")
    finally:
        logger.removeHandler(handler)
    assert any(r.levelno >= logging.WARNING for r in records)


def test_single_node_refmet_emits_no_warning():
    """The common case (1 node) must stay silent — no new log noise on 8,814 baseline rows."""
    import logging

    logger = logging.getLogger()
    records = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    logger.addHandler(handler)
    try:
        _resolver(True)._choose_best_kg_id(KG_IDS, ASSIGNED, "biolink:SmallMolecule")
    finally:
        logger.removeHandler(handler)
    assert not [r for r in records if r.levelno >= logging.WARNING]


def test_agreement_check_uses_the_deterministic_pick():
    """`refmet_nodes[0] == majority` short-circuits; with >1 node that test must also be order-free."""
    kg = {"CHEBI:refmet_a": ["a", "b"], "CHEBI:refmet_b": ["RM:2"]}
    r = _resolver(False)
    assert r._choose_best_kg_id(kg, MULTI_ASSIGNED_A, "biolink:SmallMolecule") == ("CHEBI:refmet_a", None)
    r.structure_resolver.connectivity_match.assert_not_called()
