"""NECS repaired-gold column + per-row provenance (Unit 5, offline core).

The repair is a TOTAL function over every row, not a patch over the disagreeing subset. Each row
records the rule applied and the state reached. Offline-resolvable tiers (kind_a, corrupt,
completeness, agree, single-vintage) get a repaired key now; needs-anchor tiers (kind_b,
stereo_conflict) are marked ``pending_anchor`` — never defaulted to a vintage — and resolved later
by the (gated) external name/CID pass via ``apply_anchor_resolutions``.
"""

from __future__ import annotations

import pandas as pd

from studies.external_benchmarks.scorers import structure_compare as sc
from studies.external_benchmarks.scorers.necs_gold_repair import (
    apply_anchor_resolutions,
    build_repaired_gold,
    pending_anchor_names,
)

_CHOLINE_L_KEY = "CRBHXDCYXIISFC-UHFFFAOYAW"
_CHOLINE_L_SMI = "[O-]CC[N+](C)(C)C"
_CHOLINE_M_KEY = "OEYIOHPDSNJKLS-UHFFFAOYSA-N"
_CHOLINE_M_SMI = "C[N+](C)(C)CCO"


def _frame(rows: list[dict]) -> pd.DataFrame:
    cols = [
        "chemical_name",
        "gold_inchikey",
        "gold_smiles",
        "gold_inchikey_standard",
        "gold_smiles_standard",
        "gold_formula",
    ]
    return pd.DataFrame([{c: r.get(c, "") for c in cols} for r in rows])


def test_kind_a_row_resolves_offline_to_self_consistent_vintage():
    # cortisone: legacy key wrong, arbiter=modern -> repaired takes the modern key.
    df = _frame(
        [
            dict(
                chemical_name="cortisone",
                gold_inchikey="IWIJFUQFXLWZIA-UHFFFAOYAP",
                gold_smiles="C[C@]12CCC(=O)C=C1CCC1C2C(=O)C[C@]2(C)C1CCC2(O)C(=O)CO",
                gold_inchikey_standard="MFYSYFVPBJMHGN-ZPOLXVRWSA-N",
                gold_smiles_standard="C[C@@]12CCC(=O)C=C1CC[C@H]1[C@H]2C(=O)C[C@]2(C)[C@@H]1CCC2(O)C(=O)CO",
                gold_formula="C21H28O5",
            )
        ]
    )
    out = build_repaired_gold(df)
    assert out["repair_state"].iloc[0] == "resolved_offline"
    assert out["repaired_inchikey"].iloc[0] == "MFYSYFVPBJMHGN-ZPOLXVRWSA-N"
    assert out["repair_rule"].iloc[0]  # non-empty provenance


def test_agreeing_row_passes_through_to_standard_form():
    key_l, smi = sc.standard_inchikey("CCO"), "CCO"
    df = _frame(
        [
            dict(
                chemical_name="ethanol",
                gold_inchikey=key_l,
                gold_smiles=smi,
                gold_inchikey_standard=key_l,
                gold_smiles_standard=smi,
                gold_formula="C2H6O",
            )
        ]
    )
    out = build_repaired_gold(df)
    assert out["repair_state"].iloc[0] == "agreed"
    assert out["repaired_inchikey"].iloc[0] == key_l


def test_kind_b_row_is_pending_anchor_never_defaulted():
    df = _frame(
        [
            dict(
                chemical_name="choline",
                gold_inchikey=_CHOLINE_L_KEY,
                gold_smiles=_CHOLINE_L_SMI,
                gold_inchikey_standard=_CHOLINE_M_KEY,
                gold_smiles_standard=_CHOLINE_M_SMI,
                gold_formula="C5H14NO",
            )
        ]
    )
    out = build_repaired_gold(df)
    assert out["repair_state"].iloc[0] == "pending_anchor"
    assert out["repaired_inchikey"].iloc[0] == ""  # NOT defaulted to either vintage
    assert "choline" in pending_anchor_names(out)


def test_single_vintage_and_no_gold_rows():
    df = _frame(
        [
            dict(chemical_name="legacy_only", gold_inchikey="AAAAAAAAAAAAAA-BBBBBBBBBB", gold_smiles="CCO"),
            dict(
                chemical_name="modern_only",
                gold_inchikey_standard="CCCCCCCCCCCCCC-DDDDDDDDDD-E",
                gold_smiles_standard="CCC",
            ),
            dict(chemical_name="x-99999"),  # UNNAMED / no gold
        ]
    )
    out = build_repaired_gold(df).set_index("chemical_name")
    assert out.loc["legacy_only", "repair_state"] == "legacy_only"
    assert out.loc["modern_only", "repair_state"] == "modern_only"
    assert out.loc["x-99999", "repair_state"] == "no_gold"


def test_repair_is_total_states_partition_the_frame():
    df = _frame(
        [
            dict(
                chemical_name="a",
                gold_inchikey=sc.standard_inchikey("CCO"),
                gold_smiles="CCO",
                gold_inchikey_standard=sc.standard_inchikey("CCO"),
                gold_smiles_standard="CCO",
            ),
            dict(
                chemical_name="choline",
                gold_inchikey=_CHOLINE_L_KEY,
                gold_smiles=_CHOLINE_L_SMI,
                gold_inchikey_standard=_CHOLINE_M_KEY,
                gold_smiles_standard=_CHOLINE_M_SMI,
            ),
            dict(chemical_name="x-1"),
        ]
    )
    out = build_repaired_gold(df)
    assert out["repair_state"].notna().all()
    assert (out["repair_state"] != "").all()
    assert len(out) == 3  # every input row emitted exactly once


def test_apply_anchor_resolutions_fills_pending_from_map():
    df = _frame(
        [
            dict(
                chemical_name="choline",
                gold_inchikey=_CHOLINE_L_KEY,
                gold_smiles=_CHOLINE_L_SMI,
                gold_inchikey_standard=_CHOLINE_M_KEY,
                gold_smiles_standard=_CHOLINE_M_SMI,
                gold_formula="C5H14NO",
            )
        ]
    )
    repaired = build_repaired_gold(df)
    anchor_map = {"choline": _CHOLINE_M_KEY}  # external pass decided modern is right
    resolved = apply_anchor_resolutions(repaired, anchor_map)
    assert resolved["repair_state"].iloc[0] == "resolved_anchor"
    assert resolved["repaired_inchikey"].iloc[0] == _CHOLINE_M_KEY


def test_apply_anchor_unresolved_name_stays_pending():
    df = _frame(
        [
            dict(
                chemical_name="choline",
                gold_inchikey=_CHOLINE_L_KEY,
                gold_smiles=_CHOLINE_L_SMI,
                gold_inchikey_standard=_CHOLINE_M_KEY,
                gold_smiles_standard=_CHOLINE_M_SMI,
            )
        ]
    )
    repaired = build_repaired_gold(df)
    resolved = apply_anchor_resolutions(repaired, {})  # anchor returned nothing
    assert resolved["repair_state"].iloc[0] == "pending_anchor"  # never silently defaulted
    assert resolved["repaired_inchikey"].iloc[0] == ""


def test_positive_control_bad_modern_key_flips_precedence():
    """A row whose MODERN key contradicts its own modern SMILES must resolve toward LEGACY —
    proving precedence is computed from self-consistency, not hardcoded to the modern vintage."""
    df = _frame(
        [
            dict(
                chemical_name="rigged",
                gold_inchikey=sc.standard_inchikey("CCO"),
                gold_smiles="CCO",
                gold_inchikey_standard="WRONGKEYXXXXXX-ZZZZZZZZZZ",
                gold_smiles_standard="CCC",
                gold_formula="",
            )
        ]
    )
    out = build_repaired_gold(df)
    assert out["repair_state"].iloc[0] == "resolved_offline"
    assert out["repaired_inchikey"].iloc[0] == sc.standard_inchikey("CCO")  # the legacy (correct) key
