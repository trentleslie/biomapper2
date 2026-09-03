"""Unit 4 (pure core) — the pre-registered 2x2 transition matrix for the sprint's A/B.

The headline is **adjudicable-fraction rising via ``refused -> adjudicated`` transitions ONLY**, never a
bare refused-count falling. Two failure modes this module structurally forbids (both are ways refused
could fall WITHOUT any real new adjudication):

  - ``lookup_failed`` (a transient oracle failure) and ``filter_eliminated`` (a link dropped because
    the Kestrel fix filtered out its wrong-category candidate) are kept in the not-adjudicated
    denominator — they can never count as improvement.
  - A ``certified -> anything-worse`` move is a regression and is surfaced, so a certified drop cannot
    hide behind a refused-fraction that fell for other reasons.

Per-name changes are attributed to {filter, oracle, both} across the 2x2 (pre/post Kestrel-fix x
oracle-off/on) so Unit A and Unit B effects don't entangle. Pure/offline: it consumes already-computed
per-name verdicts; the live 4-cell resolution is the caller's gated operator step.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

State = Literal["certified", "refuted", "refused", "lookup_failed", "filter_eliminated"]

ADJUDICATED: frozenset[str] = frozenset({"certified", "refuted"})
# Destinations that must NOT be read as an improvement even when the source was ``refused``.
NON_IMPROVEMENT_DEST: frozenset[str] = frozenset({"lookup_failed", "filter_eliminated"})

# The 2x2 cell key: (kestrel_fix_on, oracle_on).
Cell = tuple[bool, bool]
BASE: Cell = (False, False)
FILTER_ONLY: Cell = (True, False)
ORACLE_ONLY: Cell = (False, True)
BOTH: Cell = (True, True)


def classify_transition(src: str, dst: str) -> str:
    """Classify a per-name state change as ``improvement`` | ``regression`` | ``neutral`` (KD7).

    Only ``refused -> {certified, refuted}`` is an improvement (a previously-uncheckable link is now
    adjudicated). Any ``certified -> not-certified`` is a regression. Everything else — including
    ``refused -> lookup_failed`` / ``refused -> filter_eliminated`` — is neutral (not adjudicated).
    """
    if src == dst:
        return "neutral"
    if src == "refused" and dst in ADJUDICATED:
        return "improvement"
    if src == "certified" and dst != "certified":
        return "regression"
    return "neutral"


@dataclass(frozen=True)
class CellSummary:
    """Verdict tally for one 2x2 cell; adjudicable-fraction keeps lookup_failed/filter_eliminated in
    the denominator so it can never be inflated by attrition."""

    n: int
    certified: int
    refuted: int
    refused: int
    lookup_failed: int
    filter_eliminated: int

    @property
    def adjudicated(self) -> int:
        return self.certified + self.refuted

    @property
    def adjudicable_fraction(self) -> float | None:
        return self.adjudicated / self.n if self.n else None


def summarize_cell(verdicts: Mapping[str, str]) -> CellSummary:
    """Tally one cell's per-name verdicts into a CellSummary."""
    c = r = ref = lf = fe = 0
    for v in verdicts.values():
        if v == "certified":
            c += 1
        elif v == "refuted":
            r += 1
        elif v == "refused":
            ref += 1
        elif v == "lookup_failed":
            lf += 1
        elif v == "filter_eliminated":
            fe += 1
    return CellSummary(n=len(verdicts), certified=c, refuted=r, refused=ref, lookup_failed=lf, filter_eliminated=fe)


def attribute_change(name: str, cells: Mapping[Cell, Mapping[str, str]]) -> str | None:
    """Attribute a name's BASE->BOTH verdict change to ``filter`` | ``oracle`` | ``both`` (or None).

    ``None`` when BOTH == BASE (no net change). Otherwise: an effect from toggling the oracle alone
    (BASE vs ORACLE_ONLY) and/or the filter alone (BASE vs FILTER_ONLY) attributes accordingly; a change
    that appears only in the BOTH cell (neither single axis reproduces it) is an interaction -> ``both``.
    """
    base = cells[BASE].get(name)
    both = cells[BOTH].get(name)
    if base == both:
        return None
    oracle_effect = cells[ORACLE_ONLY].get(name) != base
    filter_effect = cells[FILTER_ONLY].get(name) != base
    if oracle_effect and filter_effect:
        return "both"
    if oracle_effect:
        return "oracle"
    if filter_effect:
        return "filter"
    return "both"  # interaction: change materializes only when both are on


@dataclass(frozen=True)
class MatrixReport:
    cells: dict[str, CellSummary]  # keyed by "fix{0|1}_oracle{0|1}"
    improvements: int
    regressions: int
    attribution: dict[str, int]  # {filter, oracle, both}
    certified_not_dropped: bool  # BOTH cell certified >= BASE cell certified


def _cell_key(cell: Cell) -> str:
    return f"fix{int(cell[0])}_oracle{int(cell[1])}"


def build_report(cells: Mapping[Cell, Mapping[str, str]]) -> MatrixReport:
    """Assemble the pre-registered 2x2 report from the four per-name verdict maps.

    ``improvements``/``regressions`` are counted on the BASE->BOTH diagonal (the headline comparison);
    attribution splits each net change across {filter, oracle, both}. ``certified_not_dropped`` is the
    R2 guard: the reported number is only defensible if BOTH's certified count did not fall below BASE.
    """
    summaries = {_cell_key(k): summarize_cell(cells[k]) for k in (BASE, FILTER_ONLY, ORACLE_ONLY, BOTH)}
    names = set(cells[BASE]) | set(cells[BOTH])
    improvements = regressions = 0
    attribution = {"filter": 0, "oracle": 0, "both": 0}
    for name in names:
        src = cells[BASE].get(name, "refused")
        dst = cells[BOTH].get(name, "refused")
        verdict = classify_transition(src, dst)
        if verdict == "improvement":
            improvements += 1
        elif verdict == "regression":
            regressions += 1
        who = attribute_change(name, cells)
        if who is not None:
            attribution[who] += 1
    certified_not_dropped = summaries[_cell_key(BOTH)].certified >= summaries[_cell_key(BASE)].certified
    return MatrixReport(
        cells=summaries,
        improvements=improvements,
        regressions=regressions,
        attribution=attribution,
        certified_not_dropped=certified_not_dropped,
    )
