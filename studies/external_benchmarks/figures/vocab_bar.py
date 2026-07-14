"""S1 — Hajjar Top-1 (structure-oracle) accuracy per target vocab.

Annotated input_type=name; each bar shows its scored denominator. A vocab with an empty
scored denominator is rendered explicitly as "n/a (no scored)" — never a silent 0/100.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

from .style import apply_figure_style


def build_s1_data(per_vocab_results: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract the plotted values from validated per-vocab structure results."""
    rows = []
    for vocab, res in per_vocab_results.items():
        core = res["comparable_core"]
        rows.append(
            {
                "vocab": vocab,
                "top1_accuracy": core["top1_accuracy"],
                "scored_denominator": core["scored_denominator"],
                "excluded": core["scored_denominator"] == 0,
            }
        )
    return rows


def render_s1(
    per_vocab_results: dict[str, dict[str, Any]], out_path: str | Path, input_type: str = "name"
) -> dict[str, Any]:
    """Render S1 to ``out_path`` (300 dpi). Returns the plotted data for traceability."""
    apply_figure_style()
    data = build_s1_data(per_vocab_results)
    fig, ax = plt.subplots(figsize=(6, 4))

    labels = [d["vocab"] for d in data]
    values = [(d["top1_accuracy"] or 0.0) * 100 for d in data]
    ax.bar(range(len(data)), values, color="#4C78A8", width=0.6)
    ax.set_xticks(range(len(data)))
    ax.set_xticklabels(labels)
    ax.set_ylabel("Top-1 accuracy (%)")
    ax.set_ylim(0, 100)
    ax.set_title(f"Hajjar-100: BioMapper accuracy per target vocab (input_type={input_type})")

    for i, d in enumerate(data):
        if d["excluded"]:
            ax.text(i, 2, "n/a\n(no scored)", ha="center", va="bottom", fontsize=8, color="#666")
        else:
            ax.text(
                i,
                (d["top1_accuracy"] or 0.0) * 100 + 1,
                f"{(d['top1_accuracy'] or 0.0) * 100:.0f}%\n(n={d['scored_denominator']})",
                ha="center",
                va="bottom",
                fontsize=8,
            )

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    return {"figure": str(out_path), "input_type": input_type, "data": data}
