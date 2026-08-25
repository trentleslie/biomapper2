"""NECS gold-disagreement classifier (Unit 4).

Splits each key-vs-key disagreement by KIND first (a key contradicting its own SMILES = the key
is the defect, offline-resolvable; vs both keys self-consistent = the structures genuinely differ,
needs the external anchor), using the file's own SMILES — never a key-to-key comparison. The four
known-answer rows are the acceptance test and correct the August audit: cortisone /
gamma-glutamylvaline are Kind A (bad legacy key), choline / xylose are Kind B (needs anchor). A
classifier that reproduces the old "cortisone = formula-confirmed defect from SMILES" or
"xylose = connectivity defect" verdicts is WRONG.
"""

from __future__ import annotations

from studies.external_benchmarks.scorers import structure_compare as sc
from studies.external_benchmarks.scorers.necs_gold_repair import classify_row

# Real MOESM5 values (public small-molecule structures, not the licensed panel).
_CORTISONE = dict(
    legacy_key="IWIJFUQFXLWZIA-UHFFFAOYAP",
    legacy_smiles="C[C@]12CCC(=O)C=C1CCC1C2C(=O)C[C@]2(C)C1CCC2(O)C(=O)CO",
    modern_key="MFYSYFVPBJMHGN-ZPOLXVRWSA-N",
    modern_smiles="C[C@@]12CCC(=O)C=C1CC[C@H]1[C@H]2C(=O)C[C@]2(C)[C@@H]1CCC2(O)C(=O)CO",
    formula="C21H28O5",
)
_GAMMA = dict(
    legacy_key="SITLTJHOQZFJGG-UUEFVBAFBQ",
    legacy_smiles="O=C(N[C@H]([C@@](O)=O)C(C)C)CC[C@@H]([C@](O)=O)N",
    modern_key="AQAKHZVPOOGUCK-XPUUQOCRSA-N",
    modern_smiles="CC(C)[C@@H](NC(=O)CC[C@@H](N)C(O)=O)C(O)=O",
    formula="C10H18N2O5",
)
_CHOLINE = dict(
    legacy_key="CRBHXDCYXIISFC-UHFFFAOYAW",
    legacy_smiles="[O-]CC[N+](C)(C)C",
    modern_key="OEYIOHPDSNJKLS-UHFFFAOYSA-N",
    modern_smiles="C[N+](C)(C)CCO",
    formula="C5H14NO",
)
_XYLOSE = dict(
    legacy_key="PYMYPHUHKUWMLA-WISUUJSJBP",
    legacy_smiles="O=C[C@@H]([C@H]([C@@H](CO)O)O)O",
    modern_key="SRBFZHDQGSBBOR-IOVATXLUSA-N",
    modern_smiles="O[C@@H]1COC(O)[C@H](O)[C@H]1O",
    formula="C5H10O5",
)


def test_cortisone_is_kind_a_bad_legacy_key():
    r = classify_row(**_CORTISONE)
    assert r["kind"] == "kind_a_bad_key"
    assert r["arbiter"] == "modern"  # the legacy key is the defect; trust modern (its own SMILES)
    assert r["offline_resolved"] is True


def test_gamma_glutamylvaline_is_kind_a_not_a_from_smiles_defect():
    r = classify_row(**_GAMMA)
    assert r["kind"] == "kind_a_bad_key"
    assert r["arbiter"] == "modern"


def test_choline_is_kind_b_needs_anchor_not_wrong_molecule():
    """The retracted verdict (choline = wrong molecule) must NOT reappear; Uncharger can't fix
    quaternary N, so this MUST route to the external anchor, not be offline-classified."""
    r = classify_row(**_CHOLINE)
    assert r["kind"] == "kind_b_structure"
    assert r["offline_resolved"] is False


def test_xylose_is_kind_b_needs_anchor_not_connectivity_defect():
    r = classify_row(**_XYLOSE)
    assert r["kind"] == "kind_b_structure"
    assert r["offline_resolved"] is False


def test_corrupt_legacy_cell_resolves_to_modern():
    r = classify_row(
        legacy_key="4000",
        legacy_smiles="",
        modern_key=_XYLOSE["modern_key"],
        modern_smiles=_XYLOSE["modern_smiles"],
        formula="C5H10O5",
    )
    assert r["kind"] == "corrupt"
    assert r["arbiter"] == "modern"
    assert r["offline_resolved"] is True


def test_unparseable_smiles_is_undecidable_with_reason():
    r = classify_row(
        legacy_key="AAAAAAAAAAAAAA-BBBBBBBBBB",
        legacy_smiles="$$bad$$",
        modern_key="CCCCCCCCCCCCCC-DDDDDDDDDD",
        modern_smiles="$$bad$$",
        formula="",
    )
    assert r["kind"] == "undecidable"
    assert "smiles" in r["reason"].lower()


def test_stereo_completeness_prefers_stereo_specified_vintage():
    """Same connectivity, one vintage specifies stereo and the other does not -> completeness,
    resolved offline toward the stereo-complete side."""
    legacy_smiles = "C[C@@H](N)C(O)=O"  # L-alanine, stereo specified
    modern_smiles = "CC(N)C(O)=O"  # alanine, stereo unspecified
    r = classify_row(
        legacy_key=sc.standard_inchikey(legacy_smiles),
        legacy_smiles=legacy_smiles,
        modern_key=sc.standard_inchikey(modern_smiles),
        modern_smiles=modern_smiles,
        formula="C3H7NO2",
    )
    assert r["kind"] == "completeness"
    assert r["arbiter"] == "legacy"  # the stereo-specified vintage
    assert r["offline_resolved"] is True


def test_positive_control_every_kind_reachable():
    """A fixture with one row per kind must produce a nonzero count in each — a classifier that
    can only emit one bucket is indistinguishable from a broken one."""
    from studies.external_benchmarks.scorers.necs_gold_repair import classify_rows

    rows = [
        _CORTISONE,
        _CHOLINE,
        dict(
            legacy_key="4000",
            legacy_smiles="",
            modern_key=_XYLOSE["modern_key"],
            modern_smiles=_XYLOSE["modern_smiles"],
            formula="",
        ),
        dict(
            legacy_key="AAAAAAAAAAAAAA-BBBBBBBBBB",
            legacy_smiles="$$bad$$",
            modern_key="CCCCCCCCCCCCCC-DDDDDDDDDD",
            modern_smiles="$$bad$$",
            formula="",
        ),
    ]
    kinds = {classify_row(**r)["kind"] for r in rows}
    assert {"kind_a_bad_key", "kind_b_structure", "corrupt", "undecidable"} <= kinds
    # classify_rows returns a per-kind tally usable as the classifier_positive_control
    tally = classify_rows(rows)["kind_counts"]
    assert all(tally.get(k, 0) >= 1 for k in ("kind_a_bad_key", "kind_b_structure", "corrupt", "undecidable"))
