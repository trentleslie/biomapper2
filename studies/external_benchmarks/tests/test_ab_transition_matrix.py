"""Unit 4 (pure) — the 2x2 transition matrix cannot report a false improvement.

Guards: refused->adjudicated is the only improvement; lookup_failed/filter_eliminated stay in the
denominator (no attrition win); a certified drop is surfaced (certified_not_dropped=False); Unit-A vs
Unit-B effects are attributed. Every case is a positive control that can fail. Pure/offline.
"""

from __future__ import annotations

from studies.external_benchmarks.ab_transition_matrix import (
    BASE,
    BOTH,
    FILTER_ONLY,
    ORACLE_ONLY,
    attribute_change,
    build_report,
    classify_transition,
    summarize_cell,
)


def test_refused_to_adjudicated_is_improvement():
    assert classify_transition("refused", "certified") == "improvement"
    assert classify_transition("refused", "refuted") == "improvement"


def test_certified_to_worse_is_regression():
    assert classify_transition("certified", "refuted") == "regression"
    assert classify_transition("certified", "refused") == "regression"


def test_refused_to_failure_states_is_not_improvement():
    # The attrition guard: a transient failure or a filtered-out link is NOT a win.
    assert classify_transition("refused", "lookup_failed") == "neutral"
    assert classify_transition("refused", "filter_eliminated") == "neutral"


def test_adjudicable_fraction_keeps_failures_in_denominator():
    cell = summarize_cell({"a": "certified", "b": "refuted", "c": "lookup_failed", "d": "filter_eliminated"})
    assert cell.adjudicated == 2 and cell.n == 4
    assert cell.adjudicable_fraction == 0.5  # failures cannot inflate it


def test_attribution_splits_filter_oracle_both():
    # name f changes only with the filter; name o only with the oracle; name x only in BOTH (interaction).
    cells = {
        BASE: {"f": "refused", "o": "refused", "x": "refused"},
        FILTER_ONLY: {"f": "certified", "o": "refused", "x": "refused"},
        ORACLE_ONLY: {"f": "refused", "o": "certified", "x": "refused"},
        BOTH: {"f": "certified", "o": "certified", "x": "certified"},
    }
    assert attribute_change("f", cells) == "filter"
    assert attribute_change("o", cells) == "oracle"
    assert attribute_change("x", cells) == "both"


def test_build_report_counts_and_certified_not_dropped_true():
    cells = {
        BASE: {"lip": "refused", "sm": "certified"},
        FILTER_ONLY: {"lip": "refused", "sm": "certified"},
        ORACLE_ONLY: {"lip": "certified", "sm": "certified"},
        BOTH: {"lip": "certified", "sm": "certified"},
    }
    rep = build_report(cells)
    assert rep.improvements == 1 and rep.regressions == 0
    assert rep.attribution["oracle"] == 1
    assert rep.certified_not_dropped is True


def test_certified_drop_is_flagged_positive_control():
    # A wrong-compound flip breaks a previously-certified link -> regression + certified_not_dropped False.
    cells = {
        BASE: {"q": "certified"},
        FILTER_ONLY: {"q": "refuted"},
        ORACLE_ONLY: {"q": "certified"},
        BOTH: {"q": "refuted"},
    }
    rep = build_report(cells)
    assert rep.regressions == 1
    assert rep.certified_not_dropped is False  # must not silently pass
