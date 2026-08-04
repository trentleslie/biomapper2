"""Capability/regression gate for the LMSD lipid arm (post-Goslin).

Once Goslin (parse) + a lipid id-binding lookup are in the resolution path, LMSD stops being an
ACCURACY test and becomes a CAPABILITY/REGRESSION check: shorthand resolvability should jump from
~5.6% toward ~100%, and the run asserts a FLOOR (the capability is wired and has not regressed). This
is deliberately NOT an accuracy number — the LMSD gold is LIPID MAPS and the binding may descend from
LIPID MAPS too, so a high LMSD resolvability certifies only that the grammar capability is present.
"""

from __future__ import annotations

from typing import Any


def capability_resolvability(result: dict[str, Any], regime: str = "shorthand") -> float:
    """Resolvability (coverage fraction) for a name-source regime, falling back to the blended core.

    Prefers the per-regime coverage (``by_name_source_regime[regime].coverage.fraction``) because the
    LMSD sample is ~90% lipid shorthand — the hard class the capability targets. Absent the regime
    breakout, uses the blended coverage. NOTE: ``score_structure_oracle`` emits ``coverage`` at the
    RESULT ROOT (not under ``comparable_core``), so the fallback must read ``result["coverage"]`` —
    reading it under ``comparable_core`` KeyErrors on any regime-less LMSD result.
    """
    by_regime = result.get("by_name_source_regime") or {}
    regime_entry = by_regime.get(regime)
    if regime_entry:
        return float(regime_entry["coverage"]["fraction"])
    return float(result["coverage"]["fraction"])


def assert_capability_floor(result: dict[str, Any], floor: float, regime: str = "shorthand") -> None:
    """Raise ``ValueError`` if the regime resolvability is below ``floor`` (the regression gate)."""
    value = capability_resolvability(result, regime=regime)
    if value < floor:
        raise ValueError(
            f"LMSD capability regression floor not met: {regime} resolvability {value:.3f} < "
            f"regression floor {floor:.3f}. The Goslin lipid capability is missing or has regressed."
        )
