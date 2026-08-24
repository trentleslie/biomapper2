"""Resolver/oracle set-returning InChIKey path (fixes the keys[0] artifact at the source)."""

from __future__ import annotations

from biomapper2.core.structure_resolver import StructureResolver
from studies.external_benchmarks.oracle import KGStructureOracle


class _FakeLinker:
    def __init__(self, records):
        self._records = records

    def get_node_records(self, ids):
        return {i: self._records.get(i) for i in ids if i in self._records}


def test_inchikey_blocks_unions_the_full_kg_list():
    recs = {
        "CHEBI:15756": {
            "name": "hexadecanoic acid",
            "equivalent_ids": {
                # keys[0] is the anion; the neutral parent (IPCS...) is at position 3.
                "INCHIKEY": [
                    "BILPUZXRUDPOOF-UHFFFAOYSA-M",
                    "XXOTHERAAAAAAA-UHFFFAOYSA-N",
                    "IPCSVZSSVZVIGE-UHFFFAOYSA-N",
                ]
            },
        }
    }
    resolver = StructureResolver(_FakeLinker(recs))
    blocks = resolver.inchikey_blocks("CHEBI:15756", "hexadecanoic acid", recs)
    assert blocks == {"BILPUZXRUDPOOF", "XXOTHERAAAAAAA", "IPCSVZSSVZVIGE"}
    # The singular strict path still returns only keys[0]'s block (unchanged).
    assert resolver.inchikey_block("CHEBI:15756", "hexadecanoic acid", recs) == "BILPUZXRUDPOOF"


def test_inchikey_blocks_empty_when_no_kg_inchikey_and_no_name_hit():
    recs = {"CHEBI:X": {"name": None, "equivalent_ids": {}}}
    resolver = StructureResolver(_FakeLinker(recs))
    # No KG InChIKey and no name to resolve -> empty set (never a spurious block).
    assert resolver.inchikey_blocks("CHEBI:X", None, recs) == set()


def test_oracle_resolved_blocks_delegates_to_resolver():
    recs = {
        "CHEBI:15756": {
            "name": "hexadecanoic acid",
            "equivalent_ids": {"INCHIKEY": ["BILPUZXRUDPOOF-UHFFFAOYSA-M", "IPCSVZSSVZVIGE-UHFFFAOYSA-N"]},
        }
    }
    linker = _FakeLinker(recs)
    oracle = KGStructureOracle(StructureResolver(linker), linker)
    assert oracle.resolved_blocks("CHEBI:15756") == {"BILPUZXRUDPOOF", "IPCSVZSSVZVIGE"}
    # strict oracle path unchanged: keys[0] only.
    assert oracle.resolved_block("CHEBI:15756") == "BILPUZXRUDPOOF"
