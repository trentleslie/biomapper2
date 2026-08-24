"""External name/CID anchor selection (Unit 5, R2a) — pure/offline parts.

The live PubChem fetch is a supervised operator step and is not exercised here; the decision
logic (which vintage an independent resolution corroborates) and the fetch wiring (via an
injected stand-in resolver) are offline-testable.
"""

from __future__ import annotations

import pandas as pd

from studies.external_benchmarks.scorers.necs_gold_repair import (
    anchor_choice,
    build_repaired_gold,
    fetch_anchor_resolutions,
)

_CHOLINE_L = "CRBHXDCYXIISFC-UHFFFAOYAW"
_CHOLINE_M = "OEYIOHPDSNJKLS-UHFFFAOYSA-N"


def test_anchor_choice_corroborates_the_matching_vintage():
    assert anchor_choice(_CHOLINE_M, _CHOLINE_L, _CHOLINE_M) == "modern"
    assert anchor_choice(_CHOLINE_L, _CHOLINE_L, _CHOLINE_M) == "legacy"


def test_anchor_matching_neither_vintage_is_none_not_defaulted():
    assert anchor_choice("ZZZZZZZZZZZZZZ-YYYYYYYYYY-X", _CHOLINE_L, _CHOLINE_M) is None
    assert anchor_choice(None, _CHOLINE_L, _CHOLINE_M) is None


def test_fetch_uses_injected_resolver_and_omits_unresolved():
    df = pd.DataFrame([{
        "chemical_name": "choline", "gold_inchikey": _CHOLINE_L, "gold_smiles": "[O-]CC[N+](C)(C)C",
        "gold_inchikey_standard": _CHOLINE_M, "gold_smiles_standard": "C[N+](C)(C)CCO",
        "gold_formula": "C5H14NO", "gold_pubchem": "305",
    }])
    repaired = build_repaired_gold(df)
    # A stand-in resolver returning the modern-corroborating key (no network).
    resolved = fetch_anchor_resolutions(repaired, resolver=lambda name, cid: _CHOLINE_M)
    assert resolved == {"choline": _CHOLINE_M}
    # A resolver that fails leaves the map empty -> row stays pending downstream.
    assert fetch_anchor_resolutions(repaired, resolver=lambda name, cid: None) == {}
