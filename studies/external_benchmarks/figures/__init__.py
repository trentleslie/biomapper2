"""Figures: S1 per-vocab accuracy bar, S2 same-dataset competitor panel.

Data-pinned: every plotted value is read from a validated results bundle (or a DOI-cited
competitor number) and returned alongside the saved figure so tests can assert
figure==results traceability. Figures must not be generated until validation passes.
"""

import matplotlib

matplotlib.use("Agg")  # headless; no display required
