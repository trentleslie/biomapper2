"""Minimal publication-grade figure styling (figure-style skill essentials).

Role-mapped font ladder, outward ticks, frameless legends, 300-dpi output. Kept small and
house-look-neutral so the study's two figures read as one system.
"""

from __future__ import annotations

import matplotlib.pyplot as plt

DPI = 300
FONT = {"title": 13, "label": 11, "tick": 9, "annot": 8, "legend": 9}


def apply_figure_style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": DPI,
            "savefig.dpi": DPI,
            "savefig.bbox": "tight",
            "axes.titlesize": FONT["title"],
            "axes.labelsize": FONT["label"],
            "xtick.labelsize": FONT["tick"],
            "ytick.labelsize": FONT["tick"],
            "legend.fontsize": FONT["legend"],
            "xtick.direction": "out",
            "ytick.direction": "out",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "font.family": "sans-serif",
        }
    )


def frameless_legend(ax, **kwargs):
    leg = ax.legend(frameon=False, **kwargs)
    return leg
