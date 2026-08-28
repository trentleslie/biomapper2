"""Tests for the off-category audit, the module every number in this change depends on.

Why this file exists
--------------------
``studies/analysis/off_category_audit.py`` exists to make the category-validator's numbers
trustworthy, and it shipped with zero test coverage. A review then found that
``refusal_provably_costless`` counted ``CORRECT_BUT_REFUSED`` -- the exact outcome the audit is
built to detect -- as costless, contradicting the note printed beside the value. On the refusal
populations the error was invisible only because that verdict happened to be zero; the first suite
to refuse a genuinely correct compound would have absorbed it into the safety figure and made the
headline claim self-confirming.

An unmeasured measuring instrument is the problem. These tests cover the pure functions directly,
and the first class below pins the arithmetic that failed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "studies" / "analysis"))
sys.path.insert(0, str(REPO_ROOT / "src"))

# Fixtures duck-type the audit's declared params: category constants are frozensets passed
# where set[str] is annotated, and fake gold rows are plain dicts passed where a Series is.
# Runtime accepts both; the type widening is fixture noise, scoped to this file.
# pyright: reportArgumentType=false

from off_category_audit import (  # noqa: E402
    ACCEPTANCE_ROOT,
    EXPECTED_ACCEPTANCE_SET,
    adjudicate,
    first_block,
    gold_curies,
    inchikey_blocks,
    is_failure_open,
    is_off_category,
    namespace_composition,
    node_equivalent_curies,
    node_has_chemical_identifier,
    normalize_local_id,
)

from biomapper2.core.annotators.base import is_on_category  # noqa: E402

CHEMICAL = EXPECTED_ACCEPTANCE_SET


def _row(
    *,
    dataset: str = "ds",
    categories: list[str] | None = None,
    gold_inchikey: str | None = None,
    node_blocks: list[str] | None = None,
    gold: list[str] | None = None,
    node_ids: list[str] | None = None,
    chemical_id: bool = True,
) -> dict:
    """One adjudication row, in the shape build_adjudication_row emits."""
    return {
        "dataset": dataset,
        "file": "f.tsv",
        "input_name": "n",
        "chosen_kg_id": "X:1",
        "namespace": "X",
        "node_name": "node",
        "categories": categories if categories is not None else ["biolink:Protein"],
        "gold_inchikey": gold_inchikey,
        "node_inchikey_blocks": node_blocks or [],
        "gold_curies": gold or [],
        "node_equivalent_curies": node_ids or [],
        "node_has_chemical_identifier": chemical_id,
    }


class TestRefusalProvablyCostless:
    """The regression that motivated this file.

    ``refusal_provably_costless`` must mean exactly what its note says: WRONG_AND_REFUSED plus rows
    whose committed node is not a compound at all. A correct compound that got refused is the one
    thing that is never costless.
    """

    def test_correct_but_refused_is_not_counted_costless(self):
        rows = [
            # CORRECT_BUT_REFUSED: gold block IS among the node's blocks. Never costless.
            _row(gold_inchikey="AAAAAAAAAAAAAA-BBBBBBBBFV-N", node_blocks=["AAAAAAAAAAAAAA"]),
            # WRONG_AND_REFUSED: both resolvable, disjoint. Costless.
            _row(gold_inchikey="CCCCCCCCCCCCCC-BBBBBBBBFV-N", node_blocks=["DDDDDDDDDDDDDD"]),
            # UNRESOLVABLE, node carries no chemical identifier at all. Costless.
            _row(chemical_id=False),
        ]
        out = adjudicate(rows, "test")
        assert out["counts"]["CORRECT_BUT_REFUSED"] == 1
        assert out["counts"]["WRONG_AND_REFUSED"] == 1
        assert out["unresolvable_reasons"]["node_carries_no_chemical_identifier"] == 1
        # The bug returned 3 here (adjudicable 2 + 1), silently absorbing the correct-but-refused row.
        assert out["refusal_provably_costless"]["n"] == 2, (
            "CORRECT_BUT_REFUSED must never be counted as a costless refusal -- it is the failure "
            "this audit exists to surface"
        )

    def test_costless_count_matches_its_own_printed_definition(self):
        """Whatever the population, n must equal WRONG_AND_REFUSED + no-chemical-identifier."""
        rows = (
            [_row(gold_inchikey="AAAAAAAAAAAAAA-X-N", node_blocks=["AAAAAAAAAAAAAA"])] * 4
            + [_row(gold_inchikey="CCCCCCCCCCCCCC-X-N", node_blocks=["DDDDDDDDDDDDDD"])] * 3
            + [_row(chemical_id=False)] * 2
            + [_row(chemical_id=True)] * 5  # UNRESOLVABLE, but node IS a compound: NOT costless
        )
        out = adjudicate(rows, "test")
        reasons = out["unresolvable_reasons"]
        expected = out["counts"]["WRONG_AND_REFUSED"] + reasons["node_carries_no_chemical_identifier"]
        assert out["refusal_provably_costless"]["n"] == expected == 5

    def test_an_unresolvable_row_whose_node_is_a_compound_is_not_costless(self):
        """The honest 'we cannot tell' bucket must stay outside the safety number."""
        out = adjudicate([_row(chemical_id=True)], "test")
        assert out["counts"]["UNRESOLVABLE"] == 1
        assert out["refusal_provably_costless"]["n"] == 0


class TestAdjudicateVerdicts:
    def test_inchikey_axis_takes_precedence_and_uses_set_membership(self):
        """Mirrors shipped D2 semantics: gold matches ANY of the node's blocks, not keys[0]."""
        out = adjudicate(
            [_row(gold_inchikey="BBBBBBBBBBBBBB-X-N", node_blocks=["AAAAAAAAAAAAAA", "BBBBBBBBBBBBBB"])],
            "test",
        )
        assert out["counts"]["CORRECT_BUT_REFUSED"] == 1
        assert out["gold_source_counts"]["inchikey_first_block"] == 1

    def test_falls_back_to_gold_database_id_when_no_inchikey(self):
        out = adjudicate([_row(gold=["CHEBI:123"], node_ids=["CHEBI:123", "HMDB:9"])], "test")
        assert out["counts"]["CORRECT_BUT_REFUSED"] == 1
        assert out["gold_source_counts"]["gold_database_id"] == 1

    def test_gold_id_axis_disjoint_is_wrong_not_unresolvable(self):
        out = adjudicate([_row(gold=["CHEBI:123"], node_ids=["CHEBI:999"])], "test")
        assert out["counts"]["WRONG_AND_REFUSED"] == 1

    @pytest.mark.parametrize(
        ("row", "expected_reason"),
        [
            (_row(chemical_id=False), "node_carries_no_chemical_identifier"),
            (_row(chemical_id=True), "row_has_no_gold_structure_or_id"),
            (_row(chemical_id=True, gold=["CHEBI:1"]), "gold_present_but_node_not_comparable"),
        ],
    )
    def test_all_three_unresolvable_reasons_are_reachable(self, row, expected_reason):
        out = adjudicate([row], "test")
        assert out["unresolvable_reasons"].get(expected_reason) == 1

    def test_empty_population_does_not_divide_by_zero(self):
        out = adjudicate([], "test")
        assert out["n_population"] == 0
        assert out["refusal_provably_costless"]["pct_of_population"] == 0.0


class TestAuditMirrorsTheShippedValidator:
    """The audit must classify rows the same way the guard does, or it measures a different thing."""

    @pytest.mark.parametrize(
        "categories",
        [
            ["biolink:SmallMolecule"],
            ["biolink:Drug", "biolink:SmallMolecule"],
            ["biolink:ChemicalEntity"],
            ["biolink:MolecularMixture"],
            ["biolink:PhenotypicFeature"],
            ["biolink:Protein"],
            ["biolink:Polypeptide"],
            ["biolink:MolecularActivity"],
            ["biolink:Pathway"],
            ["biolink:NamedThing"],
            ["biolink:Entity"],
            ["biolink:NamedThing", "biolink:Pathway"],
            [],
        ],
    )
    def test_is_off_category_is_the_exact_complement_of_is_on_category(self, categories):
        node = {"categories": categories}
        assert is_off_category(node, CHEMICAL) is not is_on_category({"categories": categories}, CHEMICAL)

    def test_missing_categories_key_is_treated_as_on_category_by_both(self):
        assert is_off_category({}, CHEMICAL) is False
        assert is_on_category({}, CHEMICAL) is True

    @pytest.mark.parametrize(
        ("categories", "expected"),
        [
            ([], True),
            (["biolink:NamedThing"], True),
            (["biolink:Entity"], True),
            (["biolink:NamedThing", "biolink:Entity"], True),
            (["biolink:NamedThing", "biolink:Pathway"], False),
            (["biolink:SmallMolecule"], False),
        ],
    )
    def test_is_failure_open_matches_the_pure_sentinel_rule(self, categories, expected):
        assert is_failure_open({"categories": categories}) is expected

    def test_acceptance_root_expands_to_the_pinned_set(self):
        assert ACCEPTANCE_ROOT == "biolink:ChemicalEntity"
        assert "biolink:SmallMolecule" in EXPECTED_ACCEPTANCE_SET
        assert "biolink:Protein" not in EXPECTED_ACCEPTANCE_SET


class TestEquivalentIdHelpers:
    @pytest.mark.parametrize(
        "equivalents",
        [
            ["INCHIKEY:AAAAAAAAAAAAAA-BBBBBBBBFV-N", "CHEBI:1"],
            {"INCHIKEY": ["AAAAAAAAAAAAAA-BBBBBBBBFV-N"], "CHEBI": ["1"]},
        ],
    )
    def test_inchikey_blocks_handles_both_response_shapes(self, equivalents):
        """Live Kestrel returns a flat CURIE list; the grouped shape must not silently yield {}."""
        assert inchikey_blocks({"equivalent_ids": equivalents}) == {"AAAAAAAAAAAAAA"}

    def test_inchikey_blocks_collects_every_key_not_just_the_first(self):
        node = {"equivalent_ids": ["INCHIKEY:AAAAAAAAAAAAAA-X-N", "INCHIKEY:BBBBBBBBBBBBBB-Y-M"]}
        assert inchikey_blocks(node) == {"AAAAAAAAAAAAAA", "BBBBBBBBBBBBBB"}

    def test_node_equivalent_curies_normalizes_case_and_shape(self):
        flat = node_equivalent_curies({"equivalent_ids": ["chebi:1", "HMDB:HMDB0000001"]})
        grouped = node_equivalent_curies({"equivalent_ids": {"chebi": ["1"], "HMDB": ["HMDB0000001"]}})
        assert flat == grouped
        assert "CHEBI:1" in flat

    def test_node_has_chemical_identifier_distinguishes_compounds_from_concepts(self):
        assert node_has_chemical_identifier({"equivalent_ids": ["CHEBI:1"]}) is True
        assert node_has_chemical_identifier({"equivalent_ids": ["INCHIKEY:AAAAAAAAAAAAAA-X-N"]}) is True
        assert node_has_chemical_identifier({"equivalent_ids": ["UMLS:C1", "NCBIGene:7132"]}) is False
        assert node_has_chemical_identifier({"equivalent_ids": []}) is False

    def test_first_block_takes_the_connectivity_layer_only(self):
        assert first_block("AAAAAAAAAAAAAA-BBBBBBBBFV-N") == "AAAAAAAAAAAAAA"
        assert first_block(None) is None

    def test_normalize_local_id_is_idempotent_on_prefixed_ids(self):
        once = normalize_local_id("CHEBI", "CHEBI:1")
        assert normalize_local_id("CHEBI", once) == once


class TestNamespaceComposition:
    def test_prices_only_the_non_canonical_on_category_population(self):
        rows = (
            [_row() | {"namespace": "CHEBI"}] * 3
            + [_row() | {"namespace": "UNII"}] * 2
            + [_row() | {"namespace": "LM"}]
            + [_row() | {"namespace": "UMLS"}]
        )
        out = namespace_composition(rows)
        assert out["n_on_category"] == 7
        assert out["whitelist_cost_all_namespaces"] == 4  # UNII x2 + LM + UMLS
        assert out["whitelist_cost_excluding_LM_and_UMLS"] == 2
        assert out["by_namespace"]["UNII"] == 2

    def test_canonical_namespace_matching_is_case_insensitive(self):
        out = namespace_composition([_row() | {"namespace": "chebi"}])
        assert out["whitelist_cost_all_namespaces"] == 0


class TestGoldCurieExtraction:
    def test_reads_configured_gold_columns_and_prefixes_them(self):
        row = {"gold_chebi": "1234", "gold_hmdb": "HMDB0000001", "unrelated": "x"}
        out = gold_curies(row, set(row))
        assert "CHEBI:1234" in out
        assert "HMDB:HMDB0000001" in out

    def test_ignores_absent_and_null_gold_columns(self):
        assert gold_curies({"gold_chebi": None}, {"gold_chebi"}) == set()
        assert gold_curies({}, set()) == set()
