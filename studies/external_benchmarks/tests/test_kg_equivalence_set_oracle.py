"""Multi-InChIKey (KG-equivalence-set) structure-oracle scoring.

Root cause (Hajjar-100 confirmation, 2026-07-22): a Kestrel KG node returns a *multi-valued*
``equivalent_ids["INCHIKEY"]`` list (neutral parent, conjugate anion, salt, stereoisomers), but the
oracle scored only ``keys[0]``. When ``keys[0]`` is an anion/salt whose first-block differs from
gold — while the gold InChIKey sits elsewhere in the list — the row is a false miss (12/19 Hajjar
misses were exactly this).

The fix is ADDITIVE: the strict ``keys[0]`` number is preserved unchanged; a new
``comparable_core_kg_equivalence_set`` counts a hit when gold's first-block is a member of the
CHOSEN node's own KG-asserted InChIKey set. It is only as trustworthy as the KG's equivalence
assertions (a match means "BioMapper chose a node the KG asserts is structurally equivalent to
gold"), so it is reported BESIDE the strict number, never as a silent replacement.
"""

from __future__ import annotations

import pandas as pd
import pytest

from studies.external_benchmarks.config import HAJJAR
from studies.external_benchmarks.scorers.structure_oracle_scorer import score_structure_oracle


class _FakeSetOracle:
    """Fake oracle exposing strict single-block (keys[0]) AND the full KG equivalence set per node."""

    def __init__(self, strict: dict[str, str | None], blocks: dict[str, set[str]]):
        self._strict = strict
        self._blocks = blocks

    def kg_block(self, node_id):
        return self._strict.get(node_id)

    def resolved_block(self, node_id):
        return self._strict.get(node_id)

    def resolved_blocks(self, node_id) -> set[str]:
        return self._blocks.get(node_id, set())


def _one_row(gold_block_key: str = "IPCSVZSSVZVIGE-UHFFFAOYSA-N"):
    return pd.DataFrame(
        {
            HAJJAR.name_column: ["hexadecanoic acid"],
            HAJJAR.gold_inchikey_column: [gold_block_key],
            "chosen_kg_id": ["CHEBI:15756"],
        }
    )


def test_strict_misses_but_equivalence_set_catches():
    # keys[0] is the anion block (BILP...), so strict misses; gold's block (IPCS...) is elsewhere
    # in the node's equivalence set, so the multi-InChIKey variant recovers it.
    gold_block = "IPCSVZSSVZVIGE"
    oracle = _FakeSetOracle(
        strict={"CHEBI:15756": "BILPUZXRUDPOOF"},  # anion first-block (keys[0]) != gold
        blocks={"CHEBI:15756": {"BILPUZXRUDPOOF", gold_block, "SALTXXXXXXXXXX"}},
    )
    result = score_structure_oracle(_one_row(), HAJJAR, oracle, vocab="CHEBI")
    strict = result["comparable_core"]
    eq = result["comparable_core_kg_equivalence_set"]
    assert strict["scored_denominator"] == 1 and strict["correct"] == 0  # strict still misses
    assert eq is not None
    assert eq["scored_denominator"] == 1 and eq["correct"] == 1  # recovered
    assert eq["top1_accuracy"] == pytest.approx(1.0)
    assert result["per_row"][0]["kg_equivalence_set_correct"] is True


def test_equivalence_set_does_not_inflate_on_wrong_entity():
    # Anti-inflation guardrail: the chosen node is a genuinely wrong entity — gold's block is NOT
    # in its equivalence set — so the multi-InChIKey variant must ALSO miss (no free recovery).
    oracle = _FakeSetOracle(
        strict={"CHEBI:15756": "BILPUZXRUDPOOF"},
        blocks={"CHEBI:15756": {"BILPUZXRUDPOOF", "WRONGAAAAAAAAA", "WRONGBBBBBBBBB"}},
    )
    result = score_structure_oracle(_one_row(), HAJJAR, oracle, vocab="CHEBI")
    eq = result["comparable_core_kg_equivalence_set"]
    assert eq["scored_denominator"] == 1 and eq["correct"] == 0
    assert result["per_row"][0]["kg_equivalence_set_correct"] is False


def test_equivalence_set_core_is_none_without_capability():
    # An oracle that does not expose resolved_blocks (older oracle / other scorers) -> the new core
    # is None and the strict number is unchanged. Purely additive, back-compatible.
    class _StrictOnly:
        def kg_block(self, node_id):
            return "BILPUZXRUDPOOF"

        def resolved_block(self, node_id):
            return "BILPUZXRUDPOOF"

    result = score_structure_oracle(_one_row(), HAJJAR, _StrictOnly(), vocab="CHEBI")
    assert result["comparable_core_kg_equivalence_set"] is None
    assert result["comparable_core"]["correct"] == 0
    assert "kg_equivalence_set_correct" in result["per_row"][0]
    assert result["per_row"][0]["kg_equivalence_set_correct"] is None


def test_equivalence_set_is_superset_of_strict_never_below():
    # Monotonicity invariant: the strict block is always a member of the set, so the equivalence-set
    # correct count can only be >= strict. Here strict already hits; the set must also hit.
    gold = "IPCSVZSSVZVIGE"
    oracle = _FakeSetOracle(
        strict={"CHEBI:15756": gold},  # keys[0] already == gold
        blocks={"CHEBI:15756": {gold, "OTHERAAAAAAAAA"}},
    )
    result = score_structure_oracle(_one_row(), HAJJAR, oracle, vocab="CHEBI")
    assert result["comparable_core"]["correct"] == 1
    assert result["comparable_core_kg_equivalence_set"]["correct"] == 1
    assert (
        result["comparable_core_kg_equivalence_set"]["correct"] >= result["comparable_core"]["correct"]
    )


def test_strict_number_identical_with_and_without_set_capability():
    # The strict comparable_core must be byte-identical whether or not the oracle exposes the set —
    # proves the addition never silently moves the published strict number.
    strict_oracle = _FakeSetOracle(
        strict={"CHEBI:15756": "BILPUZXRUDPOOF"},
        blocks={"CHEBI:15756": {"BILPUZXRUDPOOF", "IPCSVZSSVZVIGE"}},
    )

    class _StrictOnly:
        def kg_block(self, node_id):
            return "BILPUZXRUDPOOF"

        def resolved_block(self, node_id):
            return "BILPUZXRUDPOOF"

    with_set = score_structure_oracle(_one_row(), HAJJAR, strict_oracle, vocab="CHEBI")["comparable_core"]
    without = score_structure_oracle(_one_row(), HAJJAR, _StrictOnly(), vocab="CHEBI")["comparable_core"]
    assert with_set == without
