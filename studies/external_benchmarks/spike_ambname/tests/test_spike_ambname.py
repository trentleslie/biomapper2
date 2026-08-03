"""Offline tests for the deterministic spike units.

Network-isolated (fake PubChem) and money-free (no probe calls). Exercises: the
seed-42 guard, subset draw reproducibility + agreement/stratum filtering, the
neutral-resolver lane precedence + InChIKey validation, and both scoring variants
at both granularities.
"""

from __future__ import annotations

import json

import pytest

from studies.external_benchmarks.spike_ambname import resolve, run_spike, score, subset


# ---- fixtures: a tiny fake artifact ------------------------------------------

# NAD referents (real first-blocks, from the run artifact); the 'thymidine mono-
# phosphate' family is fabricated but self-consistent for the scoring tests.
GLU = "WQZGKKKJIJFFOK-GASJEMHNSA-N"
NADH = "BOPGDPNILDQYTO-NNYOXOHSSA-L"
NADP = "BAWFJGJZGIEFAR-NNYOXOHSSA-M"


@pytest.fixture
def fake_artifact(tmp_path):
    (tmp_path / "pubchem_crosscheck.json").write_text(
        json.dumps(
            {
                "agree_a": {"agrees": True},
                "agree_b": {"agrees": True},
                "agree_lipid": {"agrees": True},
                "disagree_c": {"agrees": False},
            }
        )
    )
    rows = [
        "metabolite_name,gold_referent_inchikeys,gold_referent_ids,gold_metanetx_ids,referent_count,stratum",
        f"agree_a,{NADH}|{NADP},x,y,2,non_lipid",
        f"agree_b,{GLU},x,y,1,non_lipid",
        f"agree_lipid,{GLU},x,y,1,lipid",
        f"disagree_c,{GLU},x,y,1,non_lipid",
    ]
    (tmp_path / "pham-disambiguation_stratified_subsample.csv").write_text("\n".join(rows) + "\n")
    (tmp_path / "dataset_card.json").write_text(json.dumps({"source_sha256": "deadbeef"}))
    return tmp_path


# ---- subset ------------------------------------------------------------------

def test_subset_restricts_to_nonlipid_agreements(fake_artifact):
    sub = subset.draw_subset(seed=7, n=10, stratum="non_lipid", artifact=fake_artifact)
    names = {c.name for c in sub.cases}
    assert names == {"agree_a", "agree_b"}  # lipid + disagreement excluded
    assert sub.pool_size == 2


def test_subset_seed_reproducible(fake_artifact):
    a = subset.draw_subset(seed=7, n=2, stratum=None, artifact=fake_artifact)
    b = subset.draw_subset(seed=7, n=2, stratum=None, artifact=fake_artifact)
    assert [c.name for c in a.cases] == [c.name for c in b.cases]


def test_seed_42_is_rejected(fake_artifact):
    with pytest.raises(ValueError, match="seed=42"):
        run_spike.run(seed=42, artifact=fake_artifact)


# ---- resolve -----------------------------------------------------------------

def test_inchikey_validation():
    assert resolve.is_valid_inchikey(GLU)
    assert not resolve.is_valid_inchikey("not-a-key")
    assert not resolve.is_valid_inchikey("WQZGKKKJIJFFOK")  # first block only
    assert not resolve.is_valid_inchikey(None)


def test_first_block():
    assert resolve.first_block(GLU) == "WQZGKKKJIJFFOK"
    assert resolve.first_block("") is None


def test_resolver_precedence_direct_inchikey():
    r = resolve.resolve_referent({"inchikey": GLU, "name": "glucose"}, pubchem=None)
    assert r.lane is resolve.Lane.INCHIKEY and r.inchikey == GLU


def test_resolver_falls_back_to_pubchem_name():
    class FakePubChem:
        def name_to_inchikey(self, name):
            return GLU if name == "glucose" else None

    r = resolve.resolve_referent({"name": "glucose"}, pubchem=FakePubChem())
    assert r.lane is resolve.Lane.NAME and r.inchikey == GLU

    r2 = resolve.resolve_referent({"name": "??"}, pubchem=FakePubChem())
    assert r2.lane is resolve.Lane.UNRESOLVED and r2.inchikey is None


# ---- score -------------------------------------------------------------------

def test_any_member_and_recall_block():
    # gold = {NADH, NADP}; model gets NADH right, plus a wrong extra -> P=1/2 R=1/2
    s = score.score_name(
        name="agree_a",
        gold_inchikeys=[NADH, NADP],
        predicted_inchikeys=[NADH, GLU],
        granularity="block",
    )
    assert s.any_member is True
    assert s.tp == 1
    assert s.precision == pytest.approx(0.5)
    assert s.recall == pytest.approx(0.5)
    assert s.f1 == pytest.approx(0.5)


def test_block_vs_full_granularity():
    # Same connectivity, different protonation/charge suffix: block matches, full doesn't.
    gold = ["BOPGDPNILDQYTO-NNYOXOHSSA-L"]
    pred = ["BOPGDPNILDQYTO-NNYOXOHSSA-M"]
    assert score.score_name(name="n", gold_inchikeys=gold, predicted_inchikeys=pred, granularity="block").any_member
    assert not score.score_name(name="n", gold_inchikeys=gold, predicted_inchikeys=pred, granularity="full").any_member


def test_aggregate_any_member_rate():
    rows = [
        score.score_name(name="a", gold_inchikeys=[GLU], predicted_inchikeys=[GLU], granularity="block"),
        score.score_name(name="b", gold_inchikeys=[GLU], predicted_inchikeys=[NADH], granularity="block"),
    ]
    agg = score.aggregate(rows, "block")
    assert agg.any_member_passes == 1
    assert agg.any_member_rate == pytest.approx(0.5)


# ---- verdict -----------------------------------------------------------------

@pytest.mark.parametrize(
    "rate,expected",
    [(0.60, "KILL"), (0.10, "ESCALATE"), (0.30, "AMBIGUOUS"), (None, "INCONCLUSIVE")],
)
def test_verdict_thresholds(rate, expected):
    assert expected in run_spike._verdict(rate)
