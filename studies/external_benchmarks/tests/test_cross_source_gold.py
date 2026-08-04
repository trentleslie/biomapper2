import pandas as pd
import pytest

from studies.external_benchmarks.scorers.cross_source_gold import (
    KRAKEN_INGEST_SOURCES,
    assert_gold_resolution_complete,
    gold_resolution_report,
    independence_audit,
    resolve_gold_inchikey_blocks,
)


class _FakeResolver:
    def __init__(self, mapping):
        self._m = mapping
        self.calls = 0

    def block_for_pubchem(self, cid):
        self.calls += 1
        return self._m.get(cid)


def test_resolves_gold_block_from_pubchem_cid():
    df = pd.DataFrame({"held_out_pubchem": ["452110", "9547069", ""], "gold_inchikey": ["", "", ""]})
    resolver = _FakeResolver({"452110": "KILNVBDSWZSGLL", "9547069": "AAAAAAAAAAAAAA"})
    out = resolve_gold_inchikey_blocks(df, resolver, pubchem_col="held_out_pubchem", out_col="gold_inchikey")
    assert out["gold_inchikey"].tolist() == ["KILNVBDSWZSGLL", "AAAAAAAAAAAAAA", ""]


def test_unresolvable_cid_stays_blank_fail_soft():
    df = pd.DataFrame({"held_out_pubchem": ["999"], "gold_inchikey": [""]})
    out = resolve_gold_inchikey_blocks(df, _FakeResolver({}), pubchem_col="held_out_pubchem", out_col="gold_inchikey")
    assert out["gold_inchikey"].tolist() == [""]


def test_audit_passes_for_disjoint_non_kraken_gold():
    audit = independence_audit(
        binding_source="kestrel-kg",
        gold_source="PubChem",
        lipidmaps_rest_fired=False,
        dialect_breakdown={"SwissLipids": 900, "Goslin": 600},
    )
    assert audit["disjoint"] is True
    assert audit["gold_is_kraken_ingest_source"] is False
    assert "nomenclature-standard" in audit["residual_caveat"].lower()


def test_audit_raises_when_gold_is_kraken_ingest_source():
    assert "LIPIDMAPS" in KRAKEN_INGEST_SOURCES
    with pytest.raises(ValueError, match="Kraken ingest"):
        independence_audit(
            binding_source="kestrel-kg",
            gold_source="LIPIDMAPS",
            lipidmaps_rest_fired=False,
            dialect_breakdown={},
        )


def test_audit_raises_when_binding_equals_gold():
    with pytest.raises(ValueError, match="disjoint"):
        independence_audit(
            binding_source="PubChem",
            gold_source="PubChem",
            lipidmaps_rest_fired=False,
            dialect_breakdown={},
        )


def test_gold_resolution_report_counts_retained_and_resolved():
    # Two rows carry a held-out CID (retained); one resolved, one did not. A blank-CID row is not retained.
    df = pd.DataFrame(
        {
            "held_out_pubchem": ["452110", "9547069", ""],
            "gold_inchikey": ["KILNVBDSWZSGLL", "", ""],
        }
    )
    r = gold_resolution_report(df, pubchem_col="held_out_pubchem", gold_col="gold_inchikey")
    assert r["retained"] == 2
    assert r["resolved"] == 1
    assert r["unresolved"] == 1
    assert r["completeness"] == pytest.approx(0.5)
    assert r["unresolved_cids"] == ["9547069"]


def test_assert_gold_resolution_fails_closed_below_floor():
    df = pd.DataFrame({"held_out_pubchem": ["1", "2"], "gold_inchikey": ["AAA", ""]})
    r = gold_resolution_report(df, pubchem_col="held_out_pubchem", gold_col="gold_inchikey")
    with pytest.raises(ValueError, match="gold resolution incomplete"):
        assert_gold_resolution_complete(r, min_completeness=0.90)


def test_assert_gold_resolution_passes_when_complete():
    df = pd.DataFrame({"held_out_pubchem": ["1", "2"], "gold_inchikey": ["AAA", "BBB"]})
    r = gold_resolution_report(df, pubchem_col="held_out_pubchem", gold_col="gold_inchikey")
    assert_gold_resolution_complete(r, min_completeness=0.90)  # 1.0 >= floor, no raise


def test_assert_gold_resolution_raises_on_empty_eligible_population():
    df = pd.DataFrame({"held_out_pubchem": ["", ""], "gold_inchikey": ["", ""]})
    r = gold_resolution_report(df, pubchem_col="held_out_pubchem", gold_col="gold_inchikey")
    with pytest.raises(ValueError, match="empty eligible population"):
        assert_gold_resolution_complete(r)
