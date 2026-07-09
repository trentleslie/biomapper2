"""Unit tests for the InChIKey first-block resolver.

All network is mocked — no live calls in CI.
Verifies layer ordering (KG → MW → PubChem), first-block extraction, caching bypass semantics,
and the connectivity_match tri-state.
"""

from unittest.mock import MagicMock, patch

import pytest

from studies.annotation_reranking.inchikey_resolver import (
    _block_from_kg,
    _block_from_mw,
    _block_from_pubchem,
    connectivity_match,
    inchikey_block,
)

_BLOCK = "ABCDEFGHIJKLMN"
_FULL_IK = "ABCDEFGHIJKLMN-OPQRSTUVWX-Y"


class TestLayerOrdering:
    def test_kg_hit_skips_mw_and_pubchem(self):
        """KG returning a block must short-circuit MW and PubChem (never called)."""
        with (
            patch(
                "studies.annotation_reranking.inchikey_resolver._block_from_kg",
                return_value=_BLOCK,
            ) as mock_kg,
            patch(
                "studies.annotation_reranking.inchikey_resolver._block_from_mw",
                return_value=MagicMock(),
            ) as mock_mw,
            patch(
                "studies.annotation_reranking.inchikey_resolver._block_from_pubchem",
                return_value=MagicMock(),
            ) as mock_pc,
        ):
            result = inchikey_block.__wrapped__("CHEBI:1", "x")
            assert result == _BLOCK
            mock_kg.assert_called_once_with("CHEBI:1")
            mock_mw.assert_not_called()
            mock_pc.assert_not_called()

    def test_kg_miss_falls_through_to_mw(self):
        """KG miss (None) must call MW; PubChem must NOT be called when MW succeeds."""
        with (
            patch(
                "studies.annotation_reranking.inchikey_resolver._block_from_kg",
                return_value=None,
            ),
            patch(
                "studies.annotation_reranking.inchikey_resolver._block_from_mw",
                return_value=_BLOCK,
            ) as mock_mw,
            patch(
                "studies.annotation_reranking.inchikey_resolver._block_from_pubchem",
                return_value=MagicMock(),
            ) as mock_pc,
        ):
            result = inchikey_block.__wrapped__("CHEBI:1", "glucose")
            assert result == _BLOCK
            mock_mw.assert_called_once_with("glucose")
            mock_pc.assert_not_called()

    def test_mw_miss_falls_through_to_pubchem(self):
        """Both KG and MW miss (None) — result must come from PubChem."""
        with (
            patch(
                "studies.annotation_reranking.inchikey_resolver._block_from_kg",
                return_value=None,
            ),
            patch(
                "studies.annotation_reranking.inchikey_resolver._block_from_mw",
                return_value=None,
            ),
            patch(
                "studies.annotation_reranking.inchikey_resolver._block_from_pubchem",
                return_value=_BLOCK,
            ) as mock_pc,
        ):
            result = inchikey_block.__wrapped__("CHEBI:1", "glucose")
            assert result == _BLOCK
            mock_pc.assert_called_once_with("glucose")

    def test_all_miss_returns_none(self):
        """All three layers returning None → inchikey_block returns None."""
        with (
            patch(
                "studies.annotation_reranking.inchikey_resolver._block_from_kg",
                return_value=None,
            ),
            patch(
                "studies.annotation_reranking.inchikey_resolver._block_from_mw",
                return_value=None,
            ),
            patch(
                "studies.annotation_reranking.inchikey_resolver._block_from_pubchem",
                return_value=None,
            ),
        ):
            result = inchikey_block.__wrapped__("CHEBI:99", "unknown-compound")
            assert result is None


class TestFirstBlockExtraction:
    def test_first_block_extraction(self):
        """_block_from_kg must split on '-' and return the connectivity block only."""
        full_ik = "ABCDEFGHIJKLMN-OPQRSTUVWX-Y"
        with patch(
            "studies.annotation_reranking.inchikey_resolver.Linker.get_equivalent_ids",
            return_value={"CHEBI:1": {"INCHIKEY": [full_ik]}},
        ):
            result = _block_from_kg("CHEBI:1")
        assert result == "ABCDEFGHIJKLMN"


class TestConnectivityMatch:
    def test_connectivity_match_true_false_none(self):
        """connectivity_match tri-state: True (same block), False (different), None (unresolvable)."""
        side_effects = {
            ("CHEBI:A", "aspirin"): "BSYNRYMUTXBXSQ",
            ("CHEBI:B", "aspirin-b"): "BSYNRYMUTXBXSQ",
            ("CHEBI:C", "ibuprofen"): "HEFNNWSXXWATRW",
            ("CHEBI:D", "unknown"): None,
        }

        def fake_block(node_id, name):
            return side_effects.get((node_id, name))

        with patch(
            "studies.annotation_reranking.inchikey_resolver.inchikey_block",
            side_effect=fake_block,
        ):
            # same block → True
            assert connectivity_match("CHEBI:A", "aspirin", "CHEBI:B", "aspirin-b") is True
            # different blocks → False
            assert connectivity_match("CHEBI:A", "aspirin", "CHEBI:C", "ibuprofen") is False
            # one unresolvable → None
            assert connectivity_match("CHEBI:A", "aspirin", "CHEBI:D", "unknown") is None
