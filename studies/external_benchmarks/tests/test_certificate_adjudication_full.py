"""Tests for the full per-name certificate re-adjudication (Units 1-5).

Offline + deterministic: the PubChem-facing tests inject a fake ``fetch`` (the conftest autouse
network-deny backstop guarantees no live call escapes). The reconciliation gate runs against the
pinned artifact when it is present on disk, and skips (loudly) otherwise so CI without the run data
still exercises the pure logic.
"""

from __future__ import annotations

import json

import pytest

from studies.external_benchmarks import certificate_adjudication_full as caf

# --------------------------------------------------------------------------------------------------
# Unit 1: reconciliation gate (against the pinned run, when present)
# --------------------------------------------------------------------------------------------------
_HAVE_RUN = (
    caf.PINNED_RUN_DIR.exists()
    and (caf.PINNED_RUN_DIR / "certificate_adjudication.json").exists()
    and caf.PINNED_REFMET_CACHE.exists()
    and caf.PINNED_GOLD_TSV.exists()
)


@pytest.mark.skipif(not _HAVE_RUN, reason="pinned ab_lipid_oracle run/inputs not on disk")
def test_reconciliation_gate_exact():
    """Full-emit per (pair, group, verdict) counts + refused_species_lipid reconcile CELL-FOR-CELL
    with the shipped certificate_adjudication.json; the 6 truncated examples are a subset of the
    full lists. Any mismatch fails loudly (proves the pinned env inputs are the right ones)."""
    full = caf.build_full(caf.PINNED_RUN_DIR, caf.PINNED_REFMET_CACHE, caf.PINNED_GOLD_TSV)
    artifact = json.loads((caf.PINNED_RUN_DIR / "certificate_adjudication.json").read_text())
    ok, table = caf.reconcile(full, artifact)
    mismatches = [r for r in table if not r["match"]]
    assert ok, f"reconciliation mismatches: {mismatches}"
    # spot anchors from the plan
    by = {(r["pair"], r["group"], r["verdict"]): r["full"] for r in table}
    assert by[("arivale", "monti_only", "certified")] == 4
    assert by[("xuetal", "biomapper_only", "certified")] == 14
    assert by[("arivale", "overlap", "refuted")] == 58
    assert by[("xuetal", "overlap", "refuted")] == 1
    # examples are a subset of the full lists
    for cohort in ("arivale", "xuetal"):
        for g in ("overlap", "biomapper_only", "monti_only"):
            for v in ("certified", "refuted", "refused"):
                ex = {e["name"] for e in artifact[cohort]["examples"][g][v]}
                got = {r["name"] for r in full[cohort][g][v]}
                assert ex <= got, f"{cohort}/{g}/{v}: examples not a subset of full emit"


@pytest.mark.skipif(not _HAVE_RUN, reason="pinned ab_lipid_oracle run/inputs not on disk")
def test_target_selection_counts_and_blocks():
    """Unit 2: selected rows carry a necs_block + partner_block by construction; species-lipids
    are dropped; pre-exclusion target totals match the artifact bucket counts."""
    full = caf.build_full(caf.PINNED_RUN_DIR, caf.PINNED_REFMET_CACHE, caf.PINNED_GOLD_TSV)
    rows, dropped = caf.select_targets(full)
    for r in rows:
        assert caf.is_valid_block(r["necs_block"]) or r["necs_block"] == "4000" or r["necs_block"]
        assert r["partner_block"], "every selected row must carry a partner_block"
        assert not caf.ca.is_species_level_lipid(r["necs_name"])
    # pre-exclusion totals: overlap-refuted(58+1) + monti_only-cert(4+6) + biomapper_only-cert(3+14)
    assert len(rows) + len(dropped) == (58 + 1) + (4 + 6) + (3 + 14)


# --------------------------------------------------------------------------------------------------
# Unit 3: block-shape guard + PubChem resolution (mocked)
# --------------------------------------------------------------------------------------------------
def test_block_shape_guard():
    assert caf.is_valid_block("BSYNRYMUTXBXSQ")
    assert not caf.is_valid_block("4000")
    assert not caf.is_valid_block("")
    assert not caf.is_valid_block("BSYNRYMUTXBXS")   # 13 chars
    assert not caf.is_valid_block("bsynrymutxbxsq")  # lowercase


def _prop_body(props):
    return json.dumps({"PropertyTable": {"Properties": props}})


def test_pubchem_single_cid_resolves():
    def fetch(url, timeout=20):
        return 200, _prop_body([{"CID": 2244, "InChIKey": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N", "MolecularFormula": "C9H8O4"}])
    cache = {}
    res = caf.pubchem_lookup("aspirin", cache, fetch=fetch)
    assert res["status"] == "resolved"
    assert res["block"] == "BSYNRYMUTXBXSQ"
    assert res["formula"] == "C9H8O4"
    assert res["review"] is False


def test_pubchem_multi_cid_flags_review_no_autopick():
    """Multiple CIDs with DIFFERENT first blocks -> multi, review flag, no auto-pick."""
    def fetch(url, timeout=20):
        return 200, _prop_body([
            {"CID": 1, "InChIKey": "AAAAAAAAAAAAAA-UHFFFAOYSA-N", "MolecularFormula": "C6H12O6"},
            {"CID": 2, "InChIKey": "BBBBBBBBBBBBBB-UHFFFAOYSA-N", "MolecularFormula": "C6H12O6"},
        ])
    cache = {}
    res = caf.pubchem_lookup("ambiguous", cache, fetch=fetch)
    assert res["status"] == "multi"
    assert res["review"] is True
    assert "block" not in res  # no auto-pick
    assert len(res["candidates"]) == 2


def test_pubchem_404_unresolvable():
    def fetch(url, timeout=20):
        return 404, ""
    cache = {}
    res = caf.pubchem_lookup("not a real compound", cache, fetch=fetch)
    assert res["status"] == "unresolvable"
    assert res["review"] is True


def test_pubchem_error_unresolvable():
    def fetch(url, timeout=20):
        raise TimeoutError("boom")
    cache = {}
    res = caf.pubchem_lookup("whatever", cache, fetch=fetch)
    assert res["status"] == "unresolvable"
    assert res["review"] is True


def test_warm_cache_determinism_no_network():
    """A warm cache returns without calling fetch (offline-deterministic reruns)."""
    def fetch_once(url, timeout=20):
        return 200, _prop_body([{"CID": 5, "InChIKey": "CCCCCCCCCCCCCC-UHFFFAOYSA-N", "MolecularFormula": "CH4"}])
    cache = {}
    first = caf.pubchem_lookup("methane", cache, fetch=fetch_once)

    def fetch_boom(url, timeout=20):
        raise AssertionError("network must not be touched on a warm cache")
    second = caf.pubchem_lookup("methane", cache, fetch=fetch_boom)
    assert first == second
    # normalization: different casing/whitespace hits the same cache key
    third = caf.pubchem_lookup("  METHANE ", cache, fetch=fetch_boom)
    assert third == first


# --------------------------------------------------------------------------------------------------
# Unit 4: classification
# --------------------------------------------------------------------------------------------------
def _resolved(block, formula):
    return {"status": "resolved", "block": block, "formula": formula, "review": False}


def test_classify_false_refutation():
    pc = _resolved("RCNSAJSGRJSBKK", "C33H34N4O6")
    cls, review = caf.classify("refuted", pc, pc)  # same name -> same PubChem hit
    assert cls == "false-refutation"


def test_classify_real_disagreement():
    a = _resolved("AAAAAAAAAAAAAA", "C10H10")
    b = _resolved("BBBBBBBBBBBBBB", "C20H20")
    cls, review = caf.classify("refuted", a, b)
    assert cls == "real-disagreement"


def test_classify_convention_difference_acid_anion():
    """4-hydroxyphenylacetate acid vs anion: same formula, different first block -> convention."""
    acid = _resolved("XQXPVVBIMDBYFF", "C8H8O3")
    anion = _resolved("XQXPVVBIMDBYFC", "C8H8O3")  # different block, identical formula
    cls, review = caf.classify("refuted", acid, anion)
    assert cls == "convention-difference"


def test_classify_l3_guard_block_match_formula_mismatch():
    """Ledger L3: first-block match with a DIFFERING formula routes to review, never auto-agree."""
    a = _resolved("ZZZZZZZZZZZZZZ", "C5H14NO")
    b = _resolved("ZZZZZZZZZZZZZZ", "C5H13NO")  # same block, different formula (charge/tautomer)
    cls, review = caf.classify("refuted", a, b)
    assert cls == "review-l3-formula-mismatch"
    assert review is True
    # also for the certified bucket
    cls2, _ = caf.classify("certified", a, b)
    assert cls2 == "review-l3-formula-mismatch"


def test_classify_certified_confirmed_and_spurious():
    same = _resolved("CWLQUGTUXBXTLF", "C6H11NO2")
    assert caf.classify("certified", same, same)[0] == "confirmed-genuine"
    a = _resolved("AAAAAAAAAAAAAA", "C10H10")
    b = _resolved("BBBBBBBBBBBBBB", "C20H20")
    assert caf.classify("certified", a, b)[0] == "spurious-certification"


def test_classify_unresolvable():
    ok = _resolved("AAAAAAAAAAAAAA", "C10H10")
    bad = {"status": "unresolvable", "review": True}
    assert caf.classify("refuted", ok, bad) == ("unresolvable", True)
    assert caf.classify("certified", bad, ok) == ("unresolvable", True)


# --------------------------------------------------------------------------------------------------
# Unit 3+5: adjudicate honours the gold block-shape guard; outputs are endpoint-scrubbed
# --------------------------------------------------------------------------------------------------
def test_adjudicate_nonstandard_gold_block_routes_review():
    """A gold block of ``4000`` is non-comparable -> review, never string-compared."""
    rows = [{"pair": "arivale", "group": "overlap", "verdict": "refuted",
             "necs_name": "beta-hydroxyisovalerate", "partner_name": "beta-hydroxyisovalerate",
             "necs_block": "4000", "partner_block": "AXFYFNCPONWUHW"}]

    def fetch(url, timeout=20):
        return 200, _prop_body([{"CID": 9, "InChIKey": "AXFYFNCPONWUHW-UHFFFAOYSA-N", "MolecularFormula": "C5H10O3"}])
    cache = {}
    out = caf.adjudicate(rows, cache, fetch=fetch)
    assert out[0]["classification"] == "review-nonstandard-gold-block"
    assert out[0]["review_flag"] is True


def test_endpoint_leak_assertion():
    caf.assert_no_endpoint_leak("perfectly clean output")
    for bad in ("http://127.0.0.1:8008/api/v1/map/batch", "treatment_api", "baseline_api"):
        with pytest.raises(AssertionError):
            caf.assert_no_endpoint_leak(bad)


def test_write_table_scrubs_and_roundtrips(tmp_path):
    rows = [{
        "pair": "xuetal", "group": "monti_only", "verdict": "certified",
        "necs_name": "maltose", "partner_name": "maltose",
        "necs_block": "GUBGYTABKSRVRQ", "partner_block": "GUBGYTABKSRVRQ",
        "pubchem_necs_block": "GUBGYTABKSRVRQ", "pubchem_partner_block": "GUBGYTABKSRVRQ",
        "formula_necs": "C12H22O11", "formula_partner": "C12H22O11",
        "classification": "confirmed-genuine", "review_flag": False,
    }]
    p = caf.write_table(rows, tmp_path / "t.csv")
    text = p.read_text()
    assert "127.0.0.1" not in text
    header = text.splitlines()[0].split(",")
    assert header == caf.TABLE_COLUMNS
