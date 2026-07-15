"""Name-hit-rate scorer (MetaboliteAnnotator regime) — known input -> expected. Metric is the crux."""

from __future__ import annotations

import pandas as pd
import pytest

from studies.external_benchmarks.adapters.metaboliteannotator import SOURCE_ACCESSION_COL
from studies.external_benchmarks.config import METABOLITEANNOTATOR_POS
from studies.external_benchmarks.scorers.name_hit_scorer import (
    UnscorableRunError,
    merge_vocab_runs,
    score_name_hit,
)


def _row(name, chosen, gold_id, equiv=None, smiles="", acc="MTBLS111"):
    return {
        METABOLITEANNOTATOR_POS.name_column: name,
        "chosen_kg_id": chosen,
        METABOLITEANNOTATOR_POS.gold_id_column: gold_id,
        "kg_equivalent_ids": equiv if equiv is not None else {},
        METABOLITEANNOTATOR_POS.gold_smiles_column: smiles,
        SOURCE_ACCESSION_COL: acc,
    }


def test_name_hit_rate_is_fraction_of_names_that_produced_an_id():
    df = pd.DataFrame(
        [
            _row("glucose", "CHEBI:4167", "CHEBI:17234"),  # hit
            _row("L-alanine", "CHEBI:16977", "CHEBI:16977"),  # hit
            _row("caffeine", "CHEBI:27732", "CHEBI:27732"),  # hit
            _row("mystery", "", "CHEBI:99999"),  # produced no id -> MISS (even though gold exists)
        ]
    )
    result = score_name_hit(df, METABOLITEANNOTATOR_POS)
    core = result["comparable_core"]
    assert core["metric"] == "name_hit_rate"
    assert core["matched"] == 3
    assert core["total"] == 4
    assert core["name_hit_rate"] == pytest.approx(0.75)


def test_hit_comes_from_prediction_not_the_held_out_gold():
    # A name with a gold id but NO produced id must be a miss — the hit is adjudicated on BioMapper's
    # output (chosen_kg_id), never on the held-out gold column (anti-trivial).
    df = pd.DataFrame([_row("mystery", "", "CHEBI:99999")])
    result = score_name_hit(df, METABOLITEANNOTATOR_POS)
    assert result["comparable_core"]["matched"] == 0
    assert result["comparable_core"]["name_hit_rate"] == pytest.approx(0.0)


def test_fail_loud_on_unscorable_empty_input():
    with pytest.raises(UnscorableRunError):
        score_name_hit(pd.DataFrame({METABOLITEANNOTATOR_POS.name_column: []}), METABOLITEANNOTATOR_POS)


def test_id_concordance_qualifier_uses_split_gold_curies():
    # Of the names we HIT that also carry a gold id, how many hit the RIGHT id. The |-multi gold cell
    # is parsed by split_gold_curies; equivalents count toward concordance.
    df = pd.DataFrame(
        [
            _row("glucose", "CHEBI:4167", "CHEBI:4167"),  # concordant (chosen == gold)
            _row("L-alanine", "CHEBI:00000", "CHEBI:16977|CHEBI:57972", equiv={"CHEBI": ["57972"]}),  # via equiv
            _row("caffeine", "CHEBI:99999", "CHEBI:27732"),  # produced but wrong id -> discordant
            _row("ATP", "CHEBI:15422", ""),  # hit but no gold -> not in concordance denominator
        ]
    )
    qual = score_name_hit(df, METABOLITEANNOTATOR_POS)["id_concordance"]
    assert qual["scored"] == 3  # glucose, L-alanine, caffeine (ATP has no gold)
    assert qual["concordant"] == 2
    assert qual["concordance_rate"] == pytest.approx(2 / 3)


def test_per_accession_breakdown_is_traceability_only():
    df = pd.DataFrame(
        [
            _row("glucose", "CHEBI:4167", "CHEBI:4167", acc="MTBLS111"),
            _row("mystery", "", "CHEBI:1", acc="MTBLS111"),
            _row("caffeine", "CHEBI:27732", "CHEBI:27732", acc="MTBLS222"),
        ]
    )
    result = score_name_hit(df, METABOLITEANNOTATOR_POS)
    per = result["per_accession"]
    assert per["MTBLS111"]["matched"] == 1 and per["MTBLS111"]["total"] == 2
    assert per["MTBLS222"]["matched"] == 1 and per["MTBLS222"]["total"] == 1


def test_charge_normalized_structure_qualifier_reuses_oracle_neutral_block():
    # When a live oracle exposing neutral_block is supplied, a charge-normalized STRUCTURE concordance
    # is reported over the hit-and-gold-smiles subset (the dominant-miss protonation variant).
    class FakeNeutralOracle:
        def __init__(self, blocks):
            self._blocks = blocks

        def kg_block(self, node_id):
            return self._blocks.get(node_id)

        def resolved_block(self, node_id):
            return self._blocks.get(node_id)

        def neutral_block(self, node_id):
            return self._blocks.get(node_id)

    # gold SMILES for glucose -> its neutral first block; oracle returns the same block for the id.
    from studies.external_benchmarks.scorers.structure_oracle_scorer import neutralize_first_block

    glucose_smiles = "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O"
    gold_block = neutralize_first_block(glucose_smiles)
    oracle = FakeNeutralOracle({"CHEBI:4167": gold_block})
    df = pd.DataFrame([_row("glucose", "CHEBI:4167", "CHEBI:4167", smiles=glucose_smiles)])
    result = score_name_hit(df, METABOLITEANNOTATOR_POS, oracle=oracle)
    cn = result["structure_concordance_charge_normalized"]
    assert cn is not None
    assert cn["scored"] == 1
    assert cn["concordant"] == 1


def test_structure_qualifier_is_none_without_oracle():
    df = pd.DataFrame([_row("glucose", "CHEBI:4167", "CHEBI:4167", smiles="CCO")])
    result = score_name_hit(df, METABOLITEANNOTATOR_POS)
    assert result["structure_concordance_charge_normalized"] is None


# --- Hit = ANY target vocab, not CHEBI-only (Greptile PR#22 re-review) ----------------------------


def test_row_resolving_to_hmdb_not_chebi_is_a_hit():
    # Regression: the metric is a HIT when a name resolves to ANY target vocab. A name that maps to
    # HMDB/PubChem/KEGG but NOT CHEBI must count as a hit (old CHEBI-only scoring called it a miss).
    df = pd.DataFrame(
        [
            _row("betaine", "HMDB:HMDB0000043", "HMDB:HMDB0000043"),  # HMDB only -> HIT
            _row("sucrose", "CHEBI:99999", "CHEBI:17992", equiv={"PUBCHEM": ["5988"]}),  # CHEBI+PubChem -> HIT
            _row("glutamate", "", "KEGG:C00025", equiv={"KEGG": ["C00025"]}),  # KEGG via equiv only -> HIT
            _row("odd", "FOO:1", ""),  # resolves only to a NON-target vocab -> MISS
            _row("nothing", "", ""),  # no id at all -> MISS
        ]
    )
    result = score_name_hit(df, METABOLITEANNOTATOR_POS)
    core = result["comparable_core"]
    assert core["matched"] == 3  # betaine, sucrose, glutamate
    assert core["total"] == 5
    assert core["name_hit_rate"] == pytest.approx(3 / 5)
    hits = {r["name"]: r["hit"] for r in result["per_row"]}
    assert hits["betaine"] is True
    assert hits["glutamate"] is True  # hit via a target-vocab equivalent even with empty chosen
    assert hits["odd"] is False
    assert hits["nothing"] is False


def test_merge_vocab_runs_unions_hits_across_passes():
    # run_all produces one pass per vocab. A name resolves only in the HMDB pass (empty in CHEBI);
    # merging the passes must surface it as a hit — still ONE row per name, no per-vocab axis.
    chebi_pass = pd.DataFrame(
        [
            _row("glucose", "CHEBI:4167", "CHEBI:17234"),  # resolved in CHEBI pass
            _row("betaine", "", "HMDB:HMDB0000043"),  # NOT resolved in CHEBI pass
        ]
    )
    hmdb_pass = pd.DataFrame(
        [
            _row("glucose", "", "CHEBI:17234", equiv={"HMDB": ["HMDB0000122"]}),
            _row("betaine", "HMDB:HMDB0000043", "HMDB:HMDB0000043"),  # resolved in HMDB pass
        ]
    )
    merged = merge_vocab_runs([chebi_pass, hmdb_pass], METABOLITEANNOTATOR_POS)
    assert len(merged) == 2  # one row per unique name
    result = score_name_hit(merged, METABOLITEANNOTATOR_POS)
    assert result["comparable_core"]["matched"] == 2  # both names hit after the union
    assert result["comparable_core"]["total"] == 2
