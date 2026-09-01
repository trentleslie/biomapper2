"""Units B3 + A4 — PubChem-by-name source-tagged oracle + runtime disjointness guard — pure/offline.

The oracle resolves EVERY name to ``(block, source)`` via PubChem-by-name (the disjoint side). Lipid
sum-composition names cannot be adjudicated by name, so they are honestly ``(None, "refused")`` — the
gate is scoped small-molecule-adjudicable and the A1 tripwire guards the lipid path. A4's disjointness
guard forces to ``refused`` any link whose ORACLE source equals the CANDIDATE resolver source for that
name, so the certificate can never be graded by the treatment's own structure source (the circular
case). Every guard carries a positive control that must fire.
"""

from __future__ import annotations

from studies.external_benchmarks.gate_live_oracle import (
    enforce_disjoint,
    independent_block,
    is_sum_composition_lipid,
    oracle_by_name,
    to_block_map,
)


class FakeResolver:
    """Test double for ``PubChemInChIKeyResolver`` — no network."""

    def __init__(self, blocks: dict[str, str | None]):
        self._blocks = blocks
        self.calls: list[str] = []

    def block_for_name(self, name: str) -> str | None:
        self.calls.append(name)
        return self._blocks.get(name)


def test_small_molecule_resolves_to_pubchem_block():
    resolver = FakeResolver({"D-Glucose": "WQZGKKKJIJFFOK"})
    assert independent_block("D-Glucose", resolver) == ("WQZGKKKJIJFFOK", "pubchem")


def test_lipid_shorthand_is_refused_without_calling_pubchem():
    resolver = FakeResolver({"PC(34:1)": "SHOULD_NOT_BE_USED"})
    assert independent_block("PC(34:1)", resolver) == (None, "refused")
    assert resolver.calls == []  # sum-composition lipids never hit the by-name oracle


def test_unresolvable_name_is_refused_fail_soft():
    # 404 / timeout in the resolver surfaces as None -> refused (counts-only), never a fabricated block.
    resolver = FakeResolver({"Mystery": None})
    assert independent_block("Mystery", resolver) == (None, "refused")


def test_is_sum_composition_lipid_detects_chain_unsat_shorthand():
    assert is_sum_composition_lipid("PC(34:1)")
    assert is_sum_composition_lipid("TG(16:0_18:1_18:2)")
    assert is_sum_composition_lipid("SM(d18:1/16:0)")
    assert not is_sum_composition_lipid("D-Glucose")
    assert not is_sum_composition_lipid("caffeine")


def test_oracle_by_name_builds_source_tagged_map():
    resolver = FakeResolver({"D-Glucose": "WQZGKKKJIJFFOK", "PC(34:1)": None})
    sourced = oracle_by_name(["D-Glucose", "PC(34:1)"], resolver)
    assert sourced["D-Glucose"] == ("WQZGKKKJIJFFOK", "pubchem")
    assert sourced["PC(34:1)"] == (None, "refused")


def test_enforce_disjoint_forces_refused_when_sources_match():
    # A4 positive control: oracle source == candidate resolver source for that name -> block dropped
    # to None (=> refused). The certificate can never grade a link with the candidate's own source.
    sourced = {"self_graded": ("BLOCKX", "kg"), "ok": ("BLOCKY", "pubchem")}
    candidate_source = {"self_graded": "kg", "ok": "kg"}
    blocks = enforce_disjoint(sourced, candidate_source)
    assert blocks == {"self_graded": None, "ok": "BLOCKY"}


def test_to_block_map_strips_source_tags():
    sourced = {"a": ("B1", "pubchem"), "b": (None, "refused")}
    assert to_block_map(sourced) == {"a": "B1", "b": None}
