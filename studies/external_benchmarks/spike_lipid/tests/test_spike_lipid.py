"""Offline tests for the deterministic spike units.

Network-free and money-free: pygoslin, RDKit and the anthropic client are all injected
as fakes, so the suite imports and passes without any of them installed. Exercises: the
seed-42 guard, the shorthand subset draw (query_source filter, gold-present filter,
reproducibility), formula normalisation, the gold-quality gate, both scoring metrics,
the failure taxonomy, the class-collision signal, and the taxonomy-aware verdict bands.
"""

from __future__ import annotations

import csv
import json

import pytest

from studies.external_benchmarks.spike_lipid import reference, run_spike, score, subset

# real first-blocks / keys used across tests
IK_A = "SSJULPPOBKUTHM-MXRJECHTSA-N"  # PG 36:4 gold (from the artifact)
IK_A_ISOMER = "SSJULPPOBKUTHM-ABCDEFGHSA-N"  # same connectivity, different stereo suffix
IK_B = "XAYIZQCSPHRCKT-UHFFFAOYSA-N"  # unrelated


# ---- fixtures: a tiny fake LMSD artifact -------------------------------------


@pytest.fixture
def fake_artifact(tmp_path):
    rows = [
        ["lipid_name", "query_source", "held_out_lm_id", "gold_inchikey", "gold_smiles"],
        ["TG 57:6", "abbreviation", "LM01", IK_A, "C(=O)"],
        ["PG 36:4", "abbreviation", "LM02", IK_B, "C(=O)O"],
        # a common name (must be excluded from the abbreviation draw)
        ["Cholesterol", "common_name", "LM03", IK_B, "CC"],
        # an abbreviation row missing gold structure (must be excluded)
        ["FA 4:1;O", "abbreviation", "LM04", "", ""],
    ]
    csv_path = tmp_path / "lmsd_subsample.csv"
    with csv_path.open("w", newline="") as fh:
        csv.writer(fh).writerows(rows)
    (tmp_path / "dataset_card.json").write_text(json.dumps({"subsample_sha256": "cafef00d"}))
    return tmp_path


# ---- subset ------------------------------------------------------------------


def test_subset_restricts_to_abbreviation_with_gold(fake_artifact):
    sub = subset.draw_subset(seed=7, n=10, query_source="abbreviation", artifact=fake_artifact)
    names = {c.name for c in sub.cases}
    assert names == {"TG 57:6", "PG 36:4"}  # common name + gold-less row excluded
    assert sub.pool_size == 2


def test_subset_seed_reproducible(fake_artifact):
    a = subset.draw_subset(seed=13, n=2, query_source="abbreviation", artifact=fake_artifact)
    b = subset.draw_subset(seed=13, n=2, query_source="abbreviation", artifact=fake_artifact)
    assert [c.name for c in a.cases] == [c.name for c in b.cases]


def test_seed_42_is_rejected(fake_artifact):
    with pytest.raises(ValueError, match="seed=42"):
        run_spike.run(seed=42, artifact=fake_artifact)


# ---- reference: pure helpers -------------------------------------------------


def test_normalize_formula_canonicalises():
    assert reference.normalize_formula("C60H102O6") == "C60H102O6"
    assert reference.normalize_formula("C60 H102 O6") == "C60H102O6"
    assert reference.normalize_formula("O6C60H102") == "C60H102O6"  # Hill re-order
    assert reference.normalize_formula("C3H6NO2P+") == "C3H6NO2P"   # charge stripped
    assert reference.normalize_formula("") is None
    assert reference.normalize_formula(None) is None


def test_first_block_and_inchikey_validation():
    assert reference.first_block(IK_A) == "SSJULPPOBKUTHM"
    assert reference.is_valid_inchikey(IK_A)
    assert not reference.is_valid_inchikey("SSJULPPOBKUTHM")  # block only
    assert not reference.is_valid_inchikey(None)


def test_class_backbone_ok_injected_matcher():
    calls = []

    def matcher(smiles, smarts):
        calls.append((smiles, smarts))
        return True

    assert reference.class_backbone_ok("CCO", "TG", matcher=matcher) is True
    assert calls  # covered class -> matcher invoked
    # uncovered class -> no signal, matcher not consulted
    assert reference.class_backbone_ok("CCO", "SomeExoticGlycan", matcher=matcher) is None


# ---- score: gate -------------------------------------------------------------


def test_gate_requires_parse_and_formula_agreement():
    assert score.gold_quality_gate(parsed=True, ref_formula="C60H102O6", gold_formula="C60H102O6")
    assert not score.gold_quality_gate(parsed=True, ref_formula="C60H102O6", gold_formula="C60H100O6")
    assert not score.gold_quality_gate(parsed=False, ref_formula="C60H102O6", gold_formula="C60H102O6")
    assert not score.gold_quality_gate(parsed=True, ref_formula=None, gold_formula="C60H102O6")


# ---- score: metrics + taxonomy -----------------------------------------------


def test_species_pass_but_strict_fail_is_the_key_gap():
    # right sum composition (formula match), wrong sn-isomer (different full key,
    # same first block as gold only if connectivity matches; here connectivity differs)
    s = score.score_name(
        name="TG 57:6",
        gradeable=True,
        model_smiles="CCCC",
        model_formula="C60H102O6",
        model_inchikey=IK_B,  # wrong exact structure
        ref_formula="C60H102O6",
        gold_inchikey=IK_A,
        class_ok=True,
    )
    assert s.species_pass is True
    assert s.strict_block_pass is False
    assert s.strict_full_pass is False
    assert s.failure_bucket is None


def test_strict_block_matches_on_connectivity_only():
    s = score.score_name(
        name="PG 36:4",
        gradeable=True,
        model_smiles="X",
        model_formula="C42H74O10P",
        model_inchikey=IK_A_ISOMER,  # same first block as IK_A, diff stereo
        ref_formula="C42H74O10P",
        gold_inchikey=IK_A,
        class_ok=True,
    )
    assert s.strict_block_pass is True
    assert s.strict_full_pass is False


def test_failure_bucket_wrong_carbon_count():
    s = score.score_name(
        name="TG 57:6",
        gradeable=True,
        model_smiles="CCCC",
        model_formula="C58H98O6",  # != ref
        model_inchikey=IK_B,
        ref_formula="C60H102O6",
        gold_inchikey=IK_A,
        class_ok=True,
        model_total_carbons=55,
        ref_total_carbons=57,
    )
    assert s.species_pass is False
    assert s.failure_bucket == "wrong_carbon_count"


def test_failure_bucket_invalid_smiles():
    s = score.score_name(
        name="TG 57:6",
        gradeable=True,
        model_smiles="not-a-smiles",
        model_formula=None,  # RDKit could not parse
        model_inchikey=None,
        ref_formula="C60H102O6",
        gold_inchikey=IK_A,
        class_ok=None,
    )
    assert s.failure_bucket == "invalid_smiles"


def test_ungradeable_row_scores_all_false():
    s = score.score_name(
        name="weird",
        gradeable=False,
        model_smiles="CCCC",
        model_formula="C60H102O6",
        model_inchikey=IK_A,
        ref_formula=None,
        gold_inchikey=IK_A,
        class_ok=None,
    )
    assert not (s.species_pass or s.strict_block_pass or s.strict_full_pass)


# ---- score: aggregate --------------------------------------------------------


def test_aggregate_rates_over_gradeable_only():
    scores = [
        score.score_name(name="a", gradeable=True, model_smiles="C", model_formula="F1",
                         model_inchikey=IK_A, ref_formula="F1", gold_inchikey=IK_A, class_ok=True),
        score.score_name(name="b", gradeable=True, model_smiles="C", model_formula="F2",
                         model_inchikey=IK_B, ref_formula="F1", gold_inchikey=IK_A, class_ok=True),
        score.score_name(name="c", gradeable=False, model_smiles="C", model_formula="F1",
                         model_inchikey=IK_A, ref_formula=None, gold_inchikey=IK_A, class_ok=None),
    ]
    agg = score.aggregate(scores)
    assert agg.n_drawn == 3
    assert agg.n_gradeable == 2
    assert agg.species_match_rate == pytest.approx(0.5)  # 1 of 2 gradeable
    assert agg.gate_pass_rate == pytest.approx(2 / 3)


def test_class_collision_counted_among_species_passes():
    # species passes (formula match) BUT class check says wrong backbone -> collision
    scores = [
        score.score_name(name="a", gradeable=True, model_smiles="C", model_formula="F1",
                         model_inchikey=IK_B, ref_formula="F1", gold_inchikey=IK_A, class_ok=False),
    ]
    agg = score.aggregate(scores)
    assert agg.species_pass_class_collisions == 1


# ---- verdict bands (taxonomy-aware) ------------------------------------------


def test_verdict_easy_kills():
    assert "KILL" in run_spike._verdict(0.55, {})


def test_verdict_in_band_promising():
    assert "IN-BAND" in run_spike._verdict(0.15, {"wrong_carbon_count": 5})


def test_verdict_below_band_meaningful_vs_artifact():
    meaningful = run_spike._verdict(0.05, {"wrong_carbon_count": 8, "wrong_class": 4})
    artifact = run_spike._verdict(0.05, {"invalid_smiles": 9, "no_structure_emitted": 3})
    assert "MEANINGFUL" in meaningful
    assert "ARTIFACT-RISK" in artifact


def test_verdict_inconclusive_on_no_gradeable():
    assert "INCONCLUSIVE" in run_spike._verdict(None, {})


# ---- end-to-end wiring with fakes (no money, no network) ---------------------


def test_run_end_to_end_with_fakes(fake_artifact, tmp_path):
    class FakeClient:
        def __init__(self):
            self.messages = self

        def create(self, **kw):
            # emit a correct-sum-composition SMILES for every name
            payload = {"smiles": "CCCC", "total_carbons": 57, "total_double_bonds": 6, "lipid_class": "TG"}

            class R:
                content = [type("B", (), {"type": "text", "text": json.dumps(payload)})()]
                model = "fake-model"
                stop_reason = "end_turn"

            return R()

    card = run_spike.run(
        seed=8617,
        n=10,
        artifact=fake_artifact,
        out_dir=tmp_path / "out",
        client=FakeClient(),
        goslin_parse=lambda name: reference.ShorthandParse(
            name=name, parsed=True, lipid_class="TG",
            total_carbons=57, total_double_bonds=6, formula="C60H102O6",
        ),
        formula_from_smiles=lambda s: "C60H102O6" if s else None,
        inchikey_from_smiles=lambda s: "ZZZZZZZZZZZZZZ-UHFFFAOYSA-N" if s else None,
        class_check=lambda s, c: True,
    )
    assert card["pins"]["seed"] == 8617
    assert card["pins"]["subsample_sha256"] == "cafef00d"
    assert card["scores"]["n_gradeable"] == 2  # both abbreviation-with-gold rows gradeable
    # model always emits the right sum composition -> species matches; strict fails (wrong key)
    assert card["scores"]["species_match"]["rate"] == pytest.approx(1.0)
    assert card["scores"]["strict_match"]["first_block_rate"] == pytest.approx(0.0)
    assert (tmp_path / "out" / "verdict.json").exists()
    assert (tmp_path / "out" / "raw_outputs.jsonl").exists()
