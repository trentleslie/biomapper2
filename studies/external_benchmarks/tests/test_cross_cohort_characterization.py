"""Pure delta/render helpers for the two-arm Arm-M certificate characterization (offline; no network).

The live loop (main) is `# pragma: no cover` and never runs here. These tests pin the falsifiable pure
logic: the per-pair base/treat/delta row and the rendered table, including that a coverage swing (links
changing) is reported alongside the raw counts so it can't masquerade as pure correctness movement.
"""

from __future__ import annotations

from studies.external_benchmarks.cross_cohort_certificate_characterization import (
    ArmPairResult,
    delta_row,
    render_table,
)
from studies.external_benchmarks.scorers.independent_link_certificate_overlap import CertifiedOverlap


def _arm(links, certified, refuted, refused) -> ArmPairResult:
    return ArmPairResult(
        n_links=links,
        n_necs_linked=links,
        n_cohort_linked=links,
        certified=CertifiedOverlap(certified=certified, refuted=refuted, refused=refused, per_link=()),
    )


def test_delta_row_counts_and_deltas():
    base = _arm(100, 80, 5, 15)
    treat = _arm(110, 88, 2, 20)
    row = delta_row("necs↔xu", base, treat)
    assert row["links_base"] == 100 and row["links_treat"] == 110 and row["links_delta"] == 10
    assert row["certified_delta"] == 8
    assert row["refuted_delta"] == -3  # improvement
    assert row["refused_delta"] == 5  # coverage swing surfaced, not hidden


def test_delta_row_certified_rate():
    base = _arm(100, 80, 20, 0)  # rate = 80/100
    treat = _arm(100, 90, 10, 0)  # rate = 90/100
    row = delta_row("necs↔arivale", base, treat)
    assert row["certrate_base"] == 0.8
    assert row["certrate_treat"] == 0.9
    assert row["certrate_delta"] == 0.1


def test_delta_row_rate_none_when_no_adjudicable():
    base = _arm(5, 0, 0, 5)  # all refused -> rate None
    treat = _arm(5, 0, 0, 5)
    row = delta_row("necs↔llfs", base, treat)
    assert row["certrate_base"] is None
    assert row["certrate_delta"] is None  # None-safe, no crash


def test_render_table_has_header_pairs_and_total():
    rows = [
        delta_row("necs↔xu", _arm(100, 80, 5, 15), _arm(110, 88, 2, 20)),
        delta_row("necs↔blsa", _arm(50, 40, 3, 7), _arm(52, 41, 3, 8)),
    ]
    out = render_table(rows)
    assert "cert-rate(b/t/d)" in out
    assert "necs↔xu" in out and "necs↔blsa" in out
    assert "TOTAL" in out


def test_render_table_total_sums_and_signs_delta():
    rows = [
        delta_row("necs↔xu", _arm(100, 80, 5, 15), _arm(110, 88, 2, 20)),
        delta_row("necs↔blsa", _arm(50, 40, 3, 7), _arm(52, 41, 3, 8)),
    ]
    out = render_table(rows).splitlines()
    total = [ln for ln in out if ln.startswith("TOTAL")][0]
    assert "150/162/+12" in total  # links 150 -> 162
    assert "120/129/+9" in total  # certified 120 -> 129


def test_render_table_negative_delta_shows_minus():
    rows = [delta_row("necs↔xu", _arm(100, 80, 10, 10), _arm(100, 78, 12, 10))]
    out = render_table(rows)
    assert "80/78/-2" in out  # certified fell -> signed negative delta visible
