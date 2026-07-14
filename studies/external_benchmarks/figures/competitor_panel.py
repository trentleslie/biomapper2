"""S2 — BioMapper vs Hajjar's six published tools on the same 100-set.

A valid same-dataset comparison: Hajjar ran its six ID-conversion services on this exact
100-metabolite set, so BioMapper's number sits beside them legitimately. The panel is
labeled as same-dataset. Competitor numbers are transcribed (DOI-cited); a competitor whose
value has not been transcribed is drawn as "not transcribed", never as 0.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

from ..config import CompetitorResult
from .style import apply_figure_style


def build_s2_data(biomapper_value: float, competitors: Iterable[CompetitorResult]) -> dict[str, Any]:
    bars = [{"tool": "BioMapper", "value": biomapper_value, "source": "this study", "transcribed": True}]
    for c in competitors:
        bars.append(
            {
                "tool": c.tool,
                "value": c.value,
                "source": c.doi,
                "table_ref": c.table_ref,
                "transcribed": c.value is not None,
            }
        )
    return {"bars": bars, "biomapper_value": biomapper_value}


def render_s2(
    biomapper_value: float,
    competitors: Iterable[CompetitorResult],
    out_path: str | Path,
    metric_label: str = "Conversion accuracy (%)",
) -> dict[str, Any]:
    """Render S2 to ``out_path`` (300 dpi). Returns plotted data for traceability."""
    apply_figure_style()
    competitors = list(competitors)
    data = build_s2_data(biomapper_value, competitors)
    bars = data["bars"]

    fig, ax = plt.subplots(figsize=(7, 4))
    xs = range(len(bars))
    values = [(b["value"] or 0.0) * 100 for b in bars]
    colors = ["#E45756" if b["tool"] == "BioMapper" else "#4C78A8" for b in bars]
    ax.bar(xs, values, color=colors, width=0.65)
    ax.set_xticks(list(xs))
    ax.set_xticklabels([b["tool"] for b in bars], rotation=30, ha="right")
    ax.set_ylabel(metric_label)
    ax.set_ylim(0, 100)
    ax.set_title("BioMapper vs published tools — Hajjar-100 (same-dataset comparison)")

    for i, b in enumerate(bars):
        if not b["transcribed"]:
            ax.text(i, 2, "not\ntranscribed", ha="center", va="bottom", fontsize=7, color="#666")
        else:
            ax.text(
                i,
                (b["value"] or 0.0) * 100 + 1,
                f"{(b['value'] or 0.0) * 100:.0f}%",
                ha="center",
                va="bottom",
                fontsize=8,
            )

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    return {"figure": str(out_path), "same_dataset": True, "data": data}
