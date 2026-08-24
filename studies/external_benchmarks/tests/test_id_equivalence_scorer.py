"""score_name_hit + injected id-equivalence judge — additive keys, strict number preserved."""

from __future__ import annotations

import pandas as pd
import pytest

from studies.external_benchmarks.adapters.metaboliteannotator import SOURCE_ACCESSION_COL
from studies.external_benchmarks.config import METABOLITEANNOTATOR_POS
from studies.external_benchmarks.scorers.name_hit_scorer import score_name_hit


def _row(name, chosen, gold_id, equiv=None, acc="MTBLS1"):
    return {
        METABOLITEANNOTATOR_POS.name_column: name,
        "chosen_kg_id": chosen,
        METABOLITEANNOTATOR_POS.gold_id_column: gold_id,
        "kg_equivalent_ids": equiv if equiv is not None else {},
        METABOLITEANNOTATOR_POS.gold_smiles_column: "",
        SOURCE_ACCESSION_COL: acc,
    }


class FakeJudge:
    """Deterministic judge keyed by frozenset(gold)|frozenset(pred) -> verdict."""

    def __init__(self, uci_map, block_map):
        self._uci = uci_map
        self._block = block_map

    def uci_equivalent(self, gold, pred):
        return self._uci.get((frozenset(gold), frozenset(pred)))

    def block_equivalent(self, gold, pred):
        return self._block.get((frozenset(gold), frozenset(pred)))


def test_judge_absent_leaves_strict_untouched_and_new_keys_none():
    df = pd.DataFrame([_row("glucose", "CHEBI:4167", "HMDB:HMDB0000122")])
    result = score_name_hit(df, METABOLITEANNOTATOR_POS)
    assert result["id_concordance"]["concordant"] == 0  # strict: CHEBI != HMDB gold
    assert result["id_concordance_uci_equivalence"] is None
    assert result["id_concordance_inchikey_bridge"] is None


def test_equivalence_credits_right_molecule_wrong_namespace():
    # gold HMDB, prediction CHEBI — strict discordant, but the judge credits both variants.
    df = pd.DataFrame([_row("glucose", "CHEBI:4167", "HMDB:HMDB0000122")])
    gold = frozenset({"HMDB:HMDB0000122"})
    pred = frozenset({"CHEBI:4167"})
    judge = FakeJudge({(gold, pred): True}, {(gold, pred): True})
    result = score_name_hit(df, METABOLITEANNOTATOR_POS, id_equivalence_judge=judge)
    assert result["id_concordance"]["concordant"] == 0  # strict unchanged
    uci = result["id_concordance_uci_equivalence"]
    assert uci["scored"] == 1 and uci["concordant"] == 1
    assert uci["concordance_rate"] == pytest.approx(1.0)
    assert result["id_concordance_inchikey_bridge"]["concordant"] == 1


def test_needs_verification_excluded_from_rate_not_counted_as_miss():
    # The only row is unresolvable -> nothing evaluable -> rate is None (unknown), NOT 0.0.
    # An unverifiable row must not be counted as non-equivalent (that would let a UniChem
    # outage silently deflate the published concordance rate).
    df = pd.DataFrame([_row("mystery", "CHEBI:99999", "HMDB:HMDB9999999")])
    gold = frozenset({"HMDB:HMDB9999999"})
    pred = frozenset({"CHEBI:99999"})
    judge = FakeJudge({(gold, pred): None}, {(gold, pred): None})
    result = score_name_hit(df, METABOLITEANNOTATOR_POS, id_equivalence_judge=judge)
    uci = result["id_concordance_uci_equivalence"]
    assert uci["scored"] == 1
    assert uci["evaluable"] == 0
    assert uci["concordant"] == 0
    assert uci["needs_verification"] == 1
    assert uci["concordance_rate"] is None  # nothing to adjudicate -> unknown, not a miss


def test_rate_is_over_evaluable_subset_with_partial_coverage():
    # Two rows with a gold id: one adjudicated equivalent, one unresolvable. The rate reflects
    # the judged subset (1/1 = 100%), with coverage exposed via evaluable/needs_verification.
    df = pd.DataFrame(
        [
            _row("glucose", "CHEBI:4167", "HMDB:HMDB0000122"),
            _row("mystery", "CHEBI:99999", "HMDB:HMDB9999999"),
        ]
    )
    g1, p1 = frozenset({"HMDB:HMDB0000122"}), frozenset({"CHEBI:4167"})
    g2, p2 = frozenset({"HMDB:HMDB9999999"}), frozenset({"CHEBI:99999"})
    judge = FakeJudge({(g1, p1): True, (g2, p2): None}, {(g1, p1): True, (g2, p2): None})
    result = score_name_hit(df, METABOLITEANNOTATOR_POS, id_equivalence_judge=judge)
    uci = result["id_concordance_uci_equivalence"]
    assert uci["scored"] == 2  # full strict population (both have a gold id)
    assert uci["evaluable"] == 1  # one row UniChem could adjudicate
    assert uci["concordant"] == 1
    assert uci["needs_verification"] == 1
    assert uci["concordance_rate"] == pytest.approx(1.0)  # over the judged subset, not 0.5


def test_equivalence_denominator_matches_strict_id_scored():
    # Row with a hit but NO gold id is NOT in the equivalence denominator (same as strict).
    df = pd.DataFrame(
        [
            _row("glucose", "CHEBI:4167", "HMDB:HMDB0000122"),
            _row("ATP", "CHEBI:15422", ""),  # hit, no gold -> excluded
        ]
    )
    gold = frozenset({"HMDB:HMDB0000122"})
    pred = frozenset({"CHEBI:4167"})
    judge = FakeJudge({(gold, pred): True}, {(gold, pred): True})
    result = score_name_hit(df, METABOLITEANNOTATOR_POS, id_equivalence_judge=judge)
    assert result["id_concordance"]["scored"] == 1
    assert result["id_concordance_uci_equivalence"]["scored"] == 1


def test_namespace_confusion_matrix_counts_divergent_rows():
    # Two glucose-like rows: gold HMDB, prediction CHEBI, bridge-credited but strict-discordant.
    df = pd.DataFrame(
        [
            _row("glucose", "CHEBI:4167", "HMDB:HMDB0000122"),
            _row("fructose", "CHEBI:28757", "HMDB:HMDB0000660"),
        ]
    )
    judge = FakeJudge(
        uci_map={
            (frozenset({"HMDB:HMDB0000122"}), frozenset({"CHEBI:4167"})): False,
            (frozenset({"HMDB:HMDB0000660"}), frozenset({"CHEBI:28757"})): False,
        },
        block_map={
            (frozenset({"HMDB:HMDB0000122"}), frozenset({"CHEBI:4167"})): True,
            (frozenset({"HMDB:HMDB0000660"}), frozenset({"CHEBI:28757"})): True,
        },
    )
    result = score_name_hit(df, METABOLITEANNOTATOR_POS, id_equivalence_judge=judge)
    matrix = result["namespace_confusion"]
    assert matrix == {"HMDB": {"CHEBI": 2}}  # systematic HMDB(gold) -> CHEBI(pred) divergence


def test_namespace_confusion_excludes_strict_concordant_rows():
    # Strict-concordant row (gold == prediction) must NOT appear in the divergence matrix.
    df = pd.DataFrame([_row("glucose", "CHEBI:4167", "CHEBI:4167")])
    gold = frozenset({"CHEBI:4167"})
    pred = frozenset({"CHEBI:4167"})
    judge = FakeJudge({(gold, pred): True}, {(gold, pred): True})
    result = score_name_hit(df, METABOLITEANNOTATOR_POS, id_equivalence_judge=judge)
    assert result["namespace_confusion"] == {}
