"""Tests for studies/annotation_reranking/labels.py — Task 10.

TDD: tests written first (RED), then labels.py implemented (GREEN).
All network-facing functions are mocked — NO live calls in CI.
"""
from __future__ import annotations

from unittest.mock import patch, call

import pytest

from studies.annotation_reranking.models_data import EvalCase
from studies.annotation_reranking.labels import derive_label, derive_labels, name_block


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _case(
    name: str = "test_metabolite",
    refmet_id: str = "100",
    refmet_name: str = "RefMetName",
    biomapper_ids: list[str] | None = None,
    biomapper_name: str = "BioMapperName",
    correct_id: str | None = None,
    label_source: str = "refmet_agreement",
    inchikey_block_correct: str | None = None,
) -> EvalCase:
    return EvalCase(
        name=name,
        level="MS1",
        refmet_id=refmet_id,
        refmet_name=refmet_name,
        biomapper_ids=biomapper_ids if biomapper_ids is not None else ["CHEBI:200"],
        biomapper_name=biomapper_name,
        category="metabolite",
        correct_id=correct_id,
        label_source=label_source,
        inchikey_block_correct=inchikey_block_correct,
    )


# Block string constants used throughout tests.
BLOCK_REF = "AAAAAAAAAAAAAAA"   # analyte's true connectivity block
BLOCK_RM  = "BBBBBBBBBBBBBBB"   # RefMet node block
BLOCK_BIO = "CCCCCCCCCCCCCCC"   # BioMapper node block
BLOCK_SAME = "XXXXXXXXXXXXXZ0"  # shared block (rb == bb)


# ---------------------------------------------------------------------------
# Rule 1: hand-triaged wins
# ---------------------------------------------------------------------------

class TestHandTriagedWins:
    def test_biomapper_error_case_returned_unchanged(self):
        """Hand-triaged case (label_source='independent_biomapper_error') must not be modified."""
        case = _case(
            correct_id="CHEBI:999",
            label_source="independent_biomapper_error",
        )
        node_fn = lambda nid, nm: BLOCK_RM if "CHEBI:100" in nid else BLOCK_BIO
        name_fn = lambda nm: BLOCK_REF

        cid, src, ik = derive_label(case, name_block_fn=name_fn, node_block_fn=node_fn)

        assert cid == "CHEBI:999"
        assert src == "independent_biomapper_error"
        assert ik is None

    def test_refmet_error_case_returned_unchanged(self):
        """label_source='independent_refmet_error' → returned unchanged."""
        case = _case(
            correct_id="CHEBI:200",
            label_source="independent_refmet_error",
        )
        node_fn = lambda nid, nm: BLOCK_RM
        name_fn = lambda nm: BLOCK_REF

        cid, src, ik = derive_label(case, name_block_fn=name_fn, node_block_fn=node_fn)

        assert cid == "CHEBI:200"
        assert src == "independent_refmet_error"
        assert ik is None


# ---------------------------------------------------------------------------
# Rule 2: same connectivity → expert_needed
# ---------------------------------------------------------------------------

class TestSameConnectivity:
    def test_same_rb_and_bio_gives_expert_needed(self):
        """rb == bb → (None, 'expert_needed', ref), even if ref differs."""
        case = _case(refmet_id="100", biomapper_ids=["CHEBI:200"])
        # rb and bb are the same; ref is different.
        node_fn = lambda nid, nm: BLOCK_SAME  # both refmet and bio get same block
        name_fn = lambda nm: BLOCK_REF        # ref differs from BLOCK_SAME

        cid, src, ik = derive_label(case, name_block_fn=name_fn, node_block_fn=node_fn)

        assert cid is None
        assert src == "expert_needed"
        assert ik == BLOCK_REF  # ref is still resolved

    def test_same_connectivity_takes_priority_over_rule_3(self):
        """Rule 2 fires even when ref == rb (which would satisfy rule 3 refmet pick).

        This is the critical priority check: rb==bb==ref would look like a
        valid refmet pick under rule 3, but rule 2 must fire first.
        """
        case = _case(refmet_id="100", biomapper_ids=["CHEBI:200"])
        # All three blocks are identical — rule 3 'rb==ref' would fire if rule 2 didn't.
        ALL_SAME = "ZZZZZZZZZZZZZZ1"
        node_fn = lambda nid, nm: ALL_SAME
        name_fn = lambda nm: ALL_SAME

        cid, src, ik = derive_label(case, name_block_fn=name_fn, node_block_fn=node_fn)

        assert src == "expert_needed", "Rule 2 must override rule 3 when rb==bb"

    def test_rb_none_skips_rule_2(self):
        """If rb is None, rule 2 is skipped regardless of bio blocks."""
        case = _case(refmet_id="100", biomapper_ids=["CHEBI:200"])
        node_fn = lambda nid, nm: None  # rb=None, bio=None
        name_fn = lambda nm: None       # ref also None

        cid, src, ik = derive_label(case, name_block_fn=name_fn, node_block_fn=node_fn)

        # Falls through to rule 4.
        assert src == "refmet_agreement"
        assert ik is None


# ---------------------------------------------------------------------------
# Rule 3a: ref == rb only → refmet pick
# ---------------------------------------------------------------------------

class TestRefmetPick:
    def test_ref_matches_rb_not_bio_gives_refmet_curie(self):
        """ref==rb and no bio bb==ref → (refmet_curie, 'inchikey_connectivity', ref)."""
        case = _case(refmet_id="100", biomapper_ids=["CHEBI:200"])
        # rb == ref; bio differs
        node_fn = lambda nid, nm: BLOCK_REF if "CHEBI:100" in nid else BLOCK_BIO
        name_fn = lambda nm: BLOCK_REF

        cid, src, ik = derive_label(case, name_block_fn=name_fn, node_block_fn=node_fn)

        assert cid == "CHEBI:100"
        assert src == "inchikey_connectivity"
        assert ik == BLOCK_REF


# ---------------------------------------------------------------------------
# Rule 3b: ref == one bio bb only → bio pick
# ---------------------------------------------------------------------------

class TestBioMapperPick:
    def test_ref_matches_one_bio_gives_bio_id(self):
        """ref==bb for exactly one bio and rb!=ref → (that_bid, 'inchikey_connectivity', ref)."""
        case = _case(refmet_id="100", biomapper_ids=["CHEBI:200"])
        # rb differs from ref; bio matches ref
        node_fn = lambda nid, nm: BLOCK_RM if "CHEBI:100" in nid else BLOCK_REF
        name_fn = lambda nm: BLOCK_REF

        cid, src, ik = derive_label(case, name_block_fn=name_fn, node_block_fn=node_fn)

        assert cid == "CHEBI:200"
        assert src == "inchikey_connectivity"
        assert ik == BLOCK_REF


# ---------------------------------------------------------------------------
# Rule 3c: ref matches neither → refmet_agreement
# ---------------------------------------------------------------------------

class TestAmbiguous:
    def test_ref_matches_neither_gives_refmet_agreement(self):
        """ref differs from both rb and all bio blocks → (None, 'refmet_agreement', ref)."""
        case = _case(refmet_id="100", biomapper_ids=["CHEBI:200"])
        node_fn = lambda nid, nm: BLOCK_RM if "CHEBI:100" in nid else BLOCK_BIO
        name_fn = lambda nm: BLOCK_REF  # ref is a third distinct block

        cid, src, ik = derive_label(case, name_block_fn=name_fn, node_block_fn=node_fn)

        assert cid is None
        assert src == "refmet_agreement"
        assert ik == BLOCK_REF


# ---------------------------------------------------------------------------
# Rule 4: ref is None → refmet_agreement with ik=None
# ---------------------------------------------------------------------------

class TestRefNone:
    def test_ref_none_not_same_connectivity_gives_refmet_agreement_none(self):
        """ref=None and rb!=bio → (None, 'refmet_agreement', None)."""
        case = _case(refmet_id="100", biomapper_ids=["CHEBI:200"])
        node_fn = lambda nid, nm: BLOCK_RM if "CHEBI:100" in nid else BLOCK_BIO
        name_fn = lambda nm: None  # cannot resolve name

        cid, src, ik = derive_label(case, name_block_fn=name_fn, node_block_fn=node_fn)

        assert cid is None
        assert src == "refmet_agreement"
        assert ik is None


# ---------------------------------------------------------------------------
# name_block layer order: MW tried before PubChem
# ---------------------------------------------------------------------------

class TestNameBlockLayerOrder:
    def test_mw_tried_before_pubchem(self):
        """When MW returns None, PubChem is tried; result is the PubChem block."""
        with (
            patch(
                "studies.annotation_reranking.labels._block_from_mw",
                return_value=None,
            ) as mock_mw,
            patch(
                "studies.annotation_reranking.labels._block_from_pubchem",
                return_value="ABCDEFGHIJKLMNO",
            ) as mock_pc,
        ):
            # Clear the lru_cache so our patches are actually called.
            from studies.annotation_reranking.labels import name_block as nb
            nb.cache_clear()

            result = nb("test_compound_x")

        assert result == "ABCDEFGHIJKLMNO"
        mock_mw.assert_called_once_with("test_compound_x")
        mock_pc.assert_called_once_with("test_compound_x")

    def test_mw_wins_when_returns_block(self):
        """When MW returns a block, PubChem is never called."""
        with (
            patch(
                "studies.annotation_reranking.labels._block_from_mw",
                return_value="MWBLOCKXXXXXXXX",
            ) as mock_mw,
            patch(
                "studies.annotation_reranking.labels._block_from_pubchem",
                return_value="PUBCHEMBLOCK1234",
            ) as mock_pc,
        ):
            from studies.annotation_reranking.labels import name_block as nb
            nb.cache_clear()

            result = nb("some_metabolite")

        assert result == "MWBLOCKXXXXXXXX"
        mock_mw.assert_called_once_with("some_metabolite")
        mock_pc.assert_not_called()


# ---------------------------------------------------------------------------
# derive_labels — bulk mutation
# ---------------------------------------------------------------------------

class TestDeriveLabels:
    def test_mutates_and_returns_cases(self):
        """derive_labels over a 2-case list mutates each case in-place and returns the list.

        derive_labels calls derive_label with no injected functions, so it uses the
        module-level name_block (lru_cache-wrapped).  We patch _block_from_mw (the first
        layer inside name_block) in the labels namespace and clear the cache before the
        test so the patches are exercised by the real name_block call chain.
        """
        case1 = _case(
            name="metabolite_a",
            refmet_id="100",
            biomapper_ids=["CHEBI:200"],
            label_source="refmet_agreement",
        )
        case2 = _case(
            name="metabolite_b",
            refmet_id="300",
            biomapper_ids=["CHEBI:400"],
            label_source="refmet_agreement",
        )
        cases = [case1, case2]

        # case1: rb==BLOCK_RM, ref(name)==BLOCK_RM → rb==ref, no bio match → refmet pick
        # case2: rb==BLOCK_RM, ref(name)==BLOCK_REF, bio(CHEBI:400)==BLOCK_REF → bio pick
        def node_fn(nid: str, nm: str) -> str | None:
            if "CHEBI:100" in nid or "CHEBI:300" in nid:
                return BLOCK_RM   # refmet nodes for both cases
            if "CHEBI:200" in nid:
                return BLOCK_BIO  # bio of case1 differs from ref
            if "CHEBI:400" in nid:
                return BLOCK_REF  # bio of case2 matches ref
            return None

        def mw_name_fn(name: str) -> str | None:
            """Simulate the MW layer of name_block: returns the block for known names."""
            if name == "metabolite_a":
                return BLOCK_RM   # ref==rb → refmet pick for case1
            if name == "metabolite_b":
                return BLOCK_REF  # ref==bio bb → bio pick for case2
            return None

        # Clear the lru_cache so our _block_from_mw patch is actually called.
        name_block.cache_clear()

        with (
            patch("studies.annotation_reranking.labels.inchikey_block", side_effect=node_fn),
            patch("studies.annotation_reranking.labels._block_from_mw", side_effect=mw_name_fn),
            patch("studies.annotation_reranking.labels._block_from_pubchem", return_value=None),
        ):
            result = derive_labels(cases)

        # (a) returns the same list object
        assert result is cases

        # (b) case1: rb==BLOCK_RM, ref==BLOCK_RM → refmet pick
        assert case1.correct_id == "CHEBI:100"
        assert case1.label_source == "inchikey_connectivity"
        assert case1.inchikey_block_correct == BLOCK_RM

        # (b) case2: rb==BLOCK_RM, bio==BLOCK_REF, ref==BLOCK_REF → bio pick
        assert case2.correct_id == "CHEBI:400"
        assert case2.label_source == "inchikey_connectivity"
        assert case2.inchikey_block_correct == BLOCK_REF

    def test_derive_labels_returns_same_list_object(self):
        """derive_labels returns the same list (not a copy)."""
        cases = [_case(label_source="refmet_agreement")]
        node_fn = lambda nid, nm: None
        name_fn = lambda nm: None

        # Patch the default functions so no network calls occur.
        with (
            patch("studies.annotation_reranking.labels.inchikey_block", side_effect=node_fn),
            patch("studies.annotation_reranking.labels.name_block", side_effect=name_fn),
        ):
            result = derive_labels(cases)

        assert result is cases

    def test_derive_labels_hand_triaged_unchanged(self):
        """derive_labels must not overwrite hand-triaged cases."""
        case = _case(correct_id="CHEBI:777", label_source="independent_biomapper_error")
        node_fn = lambda nid, nm: BLOCK_BIO
        name_fn = lambda nm: BLOCK_REF

        with (
            patch("studies.annotation_reranking.labels.inchikey_block", side_effect=node_fn),
            patch("studies.annotation_reranking.labels.name_block", side_effect=name_fn),
        ):
            derive_labels([case])

        assert case.correct_id == "CHEBI:777"
        assert case.label_source == "independent_biomapper_error"
        assert case.inchikey_block_correct is None
