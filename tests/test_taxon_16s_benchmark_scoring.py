"""Scorer port and fail-closed checkpoint for the 16S taxon benchmark (16S plan U4).

The scorer is ported test-first against recorded vault rows: each fixture row is a real KRAKEN top hit
for a real panel label, with the vault scorer's stored category and the NCBI lineages it used.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from studies.analysis.taxon_16s_benchmark import (
    CATEGORIES,
    acceptable,
    checkpoint_verdict,
    score_hit,
    score_rows,
    tally,
)

_FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "taxon_16s_scorer_rows.json").read_text())


def test_fixture_covers_every_category():
    assert len(_FIXTURE["rows"]) >= 12
    assert {r["expected"] for r in _FIXTURE["rows"]} == set(CATEGORIES)


@pytest.mark.parametrize("row", _FIXTURE["rows"], ids=lambda r: f"{r['id']}-{r['expected']}")
def test_score_hit_reproduces_the_vault_category(row):
    hit = row["hit"]
    got = score_hit(hit["id"] if hit else None, (hit or {}).get("equivalent_ids"), row["truth"], _FIXTURE["lineage"])
    assert got == row["expected"]


# ---------------------------------------------------------------------------------------- edge cases

_LINEAGE = {
    "100": {"taxid": "200", "name": "Old", "rank": "genus", "lineage": ["1", "2"]},  # merged alias 100 -> 200
    "200": {"taxid": "200", "name": "Current", "rank": "genus", "lineage": ["1", "2"]},
    "9606": {"taxid": "9606", "name": "Homo sapiens", "rank": "species", "lineage": ["1", "2759"]},
}


def test_merged_taxid_is_correct_under_equivalence_and_stale_under_strict():
    truth = {"cat": "a", "targets": ["200"]}
    category = score_hit("NCBITaxon:100", None, truth, _LINEAGE)
    assert category == "CORRECT-STALE-ID"
    assert acceptable(category, truth, strict=False) is True
    assert acceptable(category, truth, strict=True) is False


def test_current_hit_for_a_merged_target_is_also_equivalent():
    truth = {"cat": "a", "targets": ["100"]}
    assert score_hit("NCBITaxon:200", None, truth, _LINEAGE) == "CORRECT-STALE-ID"


def test_abstention_on_a_no_node_row_is_acceptable():
    truth = {"cat": "c", "targets": []}
    assert acceptable(score_hit(None, None, truth, _LINEAGE), truth, strict=True)


def test_non_ncbi_commit_is_a_duplicate_node():
    assert score_hit("UMLS:C1080666", {"UMLS": ["C1080666"]}, {"cat": "a", "targets": ["171552"]}, {}) == "DUP/NON-NCBI"


def _row(rid, chosen=None, faulted=False, cat="a", source="s1"):
    return (
        {
            "id": rid,
            "source": source,
            "label": rid,
            "n_units": 1,
            "reads": 0.0,
            "chosen": chosen,
            "equivalents": None,
            "faulted": faulted,
            "route": None,
        },
        {"cat": cat, "targets": ["200"] if cat == "a" else []},
    )


def _scored(specs):
    rows, truth = [], {}
    for spec in specs:
        row, rec = _row(*spec)
        rows.append(row)
        truth[row["id"]] = rec
    return score_rows(rows, truth, _LINEAGE, homonym_side={"55087"})


def test_faulted_row_is_excluded_not_counted_as_no_hit():
    scored = _scored([("r1", "NCBITaxon:200"), ("r2", None, True)])
    t = tally(scored)["ALL"]
    assert t["faulted"] == 1
    assert t["n_scored"] == 1
    assert "NO-HIT" not in t["category"]


def test_eukaryote_commit_is_counted():
    scored = _scored([("r1", "NCBITaxon:9606")])
    assert tally(scored)["ALL"]["eukaryote_commits"] == 1


# ---------------------------------------------------------------------------------------- error path


def test_checkpoint_refuses_on_a_shrunk_population():
    scored = _scored([("r1", "NCBITaxon:200"), ("r2", None, True)])
    verdict = checkpoint_verdict(scored, tally(scored), panel_size=5)
    assert verdict["status"] == "REFUSED"


def test_checkpoint_refuses_on_an_empty_population():
    assert checkpoint_verdict([], tally([]), panel_size=0)["status"] == "REFUSED"


def test_checkpoint_counts_faulted_rows_out_of_the_expected_population():
    scored = _scored([("r1", "NCBITaxon:200"), ("r2", None, True), ("r3", None, False, "c")])
    verdict = checkpoint_verdict(scored, tally(scored), panel_size=3)
    assert verdict["status"] == "MET"


def test_checkpoint_not_met_on_a_eukaryote_commit():
    scored = _scored([("r1", "NCBITaxon:200"), ("r2", "NCBITaxon:9606")])
    verdict = checkpoint_verdict(scored, tally(scored), panel_size=2)
    assert verdict["status"] == "NOT_MET"
    assert verdict["met"]["eukaryote_or_homonym_commits"] is False
