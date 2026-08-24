"""Unit 6 offline scoring core — reproduction, identity, abstention, newly-covered controls."""

from __future__ import annotations

from studies.external_benchmarks.score_necs_both_golds import score_both_golds

# name, predicted_block, gold_block(original)
_PER_ROW = [
    {"name": "a", "predicted_block": "AAAAAAAAAAAAAA", "gold_block": "AAAAAAAAAAAAAA"},  # correct
    {"name": "b", "predicted_block": "BBBBBBBBBBBBBB", "gold_block": "XXXXXXXXXXXXXX"},  # orig wrong
    {"name": "c", "predicted_block": "CCCCCCCCCCCCCC", "gold_block": "CCCCCCCCCCCCCC"},  # correct
    {"name": "d", "predicted_block": "DDDDDDDDDDDDDD", "gold_block": ""},               # no orig gold
]


def test_identity_map_reproduces_original_exactly():
    """Repaired map == original golds must reproduce the baseline on numerator AND denominator,
    exercising the repaired-path join through a known answer."""
    identity = {"a": "AAAAAAAAAAAAAA-Z", "b": "XXXXXXXXXXXXXX-Z", "c": "CCCCCCCCCCCCCC-Z"}
    out = score_both_golds(_PER_ROW, identity)
    assert out["original"] == {"numerator": 2, "denominator": 3}
    assert out["repaired"]["numerator"] == 2 and out["repaired"]["denominator"] == 3


def test_repair_that_fixes_row_b_is_counted_as_fixed():
    """Repairing b's gold to match its prediction moves it orig-wrong -> repaired-correct."""
    repaired = {"a": "AAAAAAAAAAAAAA-Z", "b": "BBBBBBBBBBBBBB-Z", "c": "CCCCCCCCCCCCCC-Z"}
    out = score_both_golds(_PER_ROW, repaired)
    assert out["repaired"]["numerator"] == 3  # b now correct
    assert out["changed_rows"].get("fixed") == 1


def test_abstention_is_costly_triple_and_pessimistic():
    """A row with an original gold but no repaired gold abstains — reported, and penalized in the
    pessimistic figure so abstaining cannot silently raise accuracy."""
    repaired = {"a": "AAAAAAAAAAAAAA-Z", "c": "CCCCCCCCCCCCCC-Z"}  # b abstains (had orig gold)
    out = score_both_golds(_PER_ROW, repaired)
    assert out["repaired"]["abstained"] == 1
    assert out["repaired"] == {"numerator": 2, "denominator": 2, "abstained": 1}
    assert out["repaired_pessimistic"] == {"numerator": 2, "denominator": 3}  # abstained in denom


def test_newly_covered_is_separated_not_folded_into_delta():
    """Row d (no original gold) gains a repaired gold — must land in newly_covered, not intersection."""
    repaired = {"a": "AAAAAAAAAAAAAA-Z", "b": "XXXXXXXXXXXXXX-Z",
                "c": "CCCCCCCCCCCCCC-Z", "d": "DDDDDDDDDDDDDD-Z"}
    out = score_both_golds(_PER_ROW, repaired)
    assert out["newly_covered"] == {"numerator": 1, "denominator": 1}
    assert out["intersection"]["denominator"] == 3  # a, b, c — not d
