"""Unit B4 — positive-control plant from known small-molecule conflations (pure/offline).

The plant is the gate's falsifiable self-test: it forces each empirically-known bad pair onto a shared
NON-STRUCTURAL CURIE (CHEBI/KEGG/PUBCHEM — an InChIKey would be stripped by ``curie_set``) so
``link_by_intersection`` links them, and the SAME PubChem oracle the arms use then ``refutes`` them
(different structures). If the plant carries no refuted link it is degenerate and the harness ABORTs
rather than trusting a gate that cannot detect a plant. Positive controls here must be able to fail.
"""

from __future__ import annotations

import json

import pytest

from studies.external_benchmarks.gate_live_plant import (
    build_plant_rows,
    load_known_conflations,
    verify_plant_refutes,
)


def _baseline_rows(names):
    return {n: {"chosen_kg_id": None, "kg_equivalent_ids": {}} for n in names}


def test_plant_links_and_refutes_a_known_conflation():
    # xylose vs glucose: same formula, different connectivity -> different PubChem blocks -> refuted.
    baseline = _baseline_rows(["D-Xylose", "D-Glucose"])
    a_rows, b_rows = build_plant_rows(baseline, [("D-Xylose", "D-Glucose")], shared_prefix="CHEBI")
    # both sides carry the SAME synthetic non-structural CURIE so the linker joins them
    assert a_rows["D-Xylose"]["chosen_kg_id"] == b_rows["D-Glucose"]["chosen_kg_id"]
    assert a_rows["D-Xylose"]["chosen_kg_id"].startswith("CHEBI:")
    oracle = {"D-Xylose": "XYLOSEBLOCK", "D-Glucose": "GLUCOSEBLOCK"}
    assert verify_plant_refutes(a_rows, b_rows, oracle, oracle) >= 1


def test_empty_known_set_raises_degenerate_plant():
    # Positive control: no known conflations -> no plant link -> raise (never a silent empty plant).
    with pytest.raises(ValueError, match="degenerate|no .*conflation"):
        build_plant_rows(_baseline_rows(["A", "B"]), [], shared_prefix="CHEBI")


def test_known_good_pair_does_not_refute_and_verify_raises():
    # A "known-good" pair (both names resolve to the SAME structure) yields 0 refuted -> verify raises,
    # proving the plant's refuted assertion can actually fail.
    baseline = _baseline_rows(["Caffeine", "Caffeine-dup"])
    a_rows, b_rows = build_plant_rows(baseline, [("Caffeine", "Caffeine-dup")], shared_prefix="CHEBI")
    same = {"Caffeine": "CAFBLOCK", "Caffeine-dup": "CAFBLOCK"}
    with pytest.raises(ValueError, match="refut"):
        verify_plant_refutes(a_rows, b_rows, same, same)


def test_structural_shared_prefix_is_rejected():
    # Edge: a shared id given as an InChIKey would be stripped by curie_set (would not link) -> reject.
    with pytest.raises(ValueError, match="non-structural|INCHIKEY|structural"):
        build_plant_rows(_baseline_rows(["A", "B"]), [("A", "B")], shared_prefix="INCHIKEY")


def test_names_absent_from_baseline_are_skipped():
    # Edge: a pair naming an analyte not in the baseline panel is skipped; a surviving pair still plants.
    baseline = _baseline_rows(["D-Xylose", "D-Glucose"])
    a_rows, b_rows = build_plant_rows(
        baseline,
        [("Ghost", "D-Glucose"), ("D-Xylose", "D-Glucose")],
        shared_prefix="CHEBI",
    )
    assert "Ghost" not in a_rows
    assert "D-Xylose" in a_rows and "D-Glucose" in b_rows


def test_all_pairs_absent_raises_degenerate():
    with pytest.raises(ValueError, match="degenerate|no .*conflation"):
        build_plant_rows(_baseline_rows(["A"]), [("Ghost1", "Ghost2")], shared_prefix="CHEBI")


def test_load_known_conflations_reads_refuted_pairs_json(tmp_path):
    path = tmp_path / "refuted_pairs.json"
    path.write_text(json.dumps([["D-Xylose", "D-Glucose"], ["A", "B"]]))
    pairs = load_known_conflations(path)
    assert ("D-Xylose", "D-Glucose") in pairs


def test_load_known_conflations_falls_back_to_curated_set():
    # No artifact -> a small curated fallback (documented: run the diagnosis first for the real set).
    pairs = load_known_conflations(None)
    assert len(pairs) >= 1
    assert all(isinstance(a, str) and isinstance(b, str) for a, b in pairs)
