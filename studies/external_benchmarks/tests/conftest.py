"""Shared fixtures for the external-benchmarks tests.

Everything is network-isolated: fixtures build in-memory DataFrames / fake resolvers so
the suite runs offline and deterministically. No live Kestrel/MW/PubChem calls.
"""

from __future__ import annotations

import pandas as pd
import pytest

from studies.external_benchmarks.config import HAJJAR


@pytest.fixture
def hajjar_config():
    return HAJJAR


@pytest.fixture
def raw_hajjar_df():
    """A tiny stand-in for the Hajjar supplement table (raw column names).

    Five rows exercising the meaningful cases: a clean row, a row where the predicted
    ChEBI will differ from gold but share connectivity, a wrong-connectivity row, a row
    with no gold InChIKey (no-structure), and a row with SMILES for the RDKit check.
    """
    return pd.DataFrame(
        {
            "Metabolite name": ["D-Glucose", "L-Alanine", "Caffeine", "Mystery lipid", "Ethanol"],
            "ChEBI ID": ["CHEBI:4167", "CHEBI:16977", "CHEBI:27732", "CHEBI:99999", "CHEBI:16236"],
            "InChIKey": [
                "WQZGKKKJIJFFOK-GASJEMHNSA-N",  # glucose
                "QNAYBMKLOCPYGJ-REOHCLBHSA-N",  # L-alanine
                "RYYVLZVUVIJVGH-UHFFFAOYSA-N",  # caffeine
                "",  # no gold structure
                "LFQSCWFLJHTTHZ-UHFFFAOYSA-N",  # ethanol
            ],
            "SMILES": [
                "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
                "C[C@@H](C(=O)O)N",
                "Cn1cnc2c1c(=O)n(C)c(=O)n2C",
                "",
                "CCO",
            ],
        }
    )


class FakeOracle:
    """Test double for the KG structure oracle.

    ``kg_block`` returns the InChIKey first-block from the KG record only (None if the KG
    has no structure). ``resolved_block`` additionally consults the name fallback. The gap
    between them is exactly the fallback-segregation signal the scorer flags.
    """

    def __init__(self, kg_blocks: dict[str, str | None], fallback_blocks: dict[str, str | None] | None = None):
        self._kg = kg_blocks
        self._fb = fallback_blocks or {}

    def kg_block(self, node_id):
        return self._kg.get(node_id)

    def resolved_block(self, node_id):
        b = self._kg.get(node_id)
        if b is not None:
            return b
        return self._fb.get(node_id)


@pytest.fixture
def fake_oracle_factory():
    return FakeOracle
