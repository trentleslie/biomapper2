"""Unit 1 - draw the graded subset from the LMSD lipid-shorthand pool.

Source data is already materialised in the newbench artifact:

* ``lmsd/lmsd_subsample.csv`` - columns include ``lipid_name`` (the shorthand, e.g.
  ``TG 57:6``), ``query_source`` (``abbreviation`` / ``common_name`` /
  ``systematic_name``), ``held_out_lm_id`` (LIPID MAPS id), ``gold_inchikey`` and
  ``gold_smiles`` (the sn-resolved LMSD reference structure), plus gold cross-refs.

The #2 story is the **shorthand** class, so we restrict to
``query_source == abbreviation`` (1,033 of the 1,500 rows). The blended LMSD number
(19.8%) averages this hard shorthand stratum with the easier common/systematic names;
we probe the hard stratum on purpose.

Note: names contain commas (common/systematic names especially) so the CSV MUST be
parsed with the ``csv`` module, never split on ``,``.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

# The newbench artifact (pinned by the spec). Not under version control (a run
# output); provenance is pinned via ``subsample_sha256`` on the LMSD dataset card,
# recorded into the spike run card by run_spike.py.
DEFAULT_ARTIFACT = (
    Path.home() / "external_benchmark_runs" / "newbench_20260716T173200Z" / "lmsd"
)


@dataclass(frozen=True)
class GoldCase:
    """One lipid shorthand and its LMSD reference structure (the sn-resolved gold).

    ``gold_inchikey`` / ``gold_smiles`` are ONE arbitrary sn-defined isomer that shares
    the shorthand's sum composition — over-specified relative to what the shorthand
    denotes. The grader (score.py) reduces both sides to the species resolution; the
    exact key is used only for the strict/over-specified metric that reproduces 5.4%.
    """

    name: str  # the shorthand, e.g. "TG 57:6"
    gold_inchikey: str
    gold_smiles: str
    query_source: str
    lm_id: str


@dataclass(frozen=True)
class Subset:
    """A seed-pinned draw plus everything needed to reproduce it."""

    seed: int
    query_source: str | None
    n_requested: int
    cases: tuple[GoldCase, ...]
    pool_size: int
    artifact: str = field(default="")

    def as_card(self) -> dict:
        return {
            "seed": self.seed,
            "query_source": self.query_source,
            "n_requested": self.n_requested,
            "n_drawn": len(self.cases),
            "pool_size": self.pool_size,
            "artifact": self.artifact,
            "names": [c.name for c in self.cases],
        }


def _load_rows(artifact: Path) -> list[dict]:
    csv_path = artifact / "lmsd_subsample.csv"
    with csv_path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def draw_subset(
    *,
    seed: int,
    n: int = 100,
    query_source: str | None = "abbreviation",
    artifact: Path = DEFAULT_ARTIFACT,
) -> Subset:
    """Draw ``n`` shorthand cases with a fresh, recorded ``seed``.

    ``seed`` MUST NOT be 42 (the reservoir seed that defines the 1,500-name LMSD
    subsample); measuring the difficulty estimate on the exact set that seeds the
    benchmark would contaminate it. ``run_spike`` enforces this.
    """
    import random

    rows = _load_rows(artifact)
    pool = [
        GoldCase(
            name=r["lipid_name"],
            gold_inchikey=r.get("gold_inchikey", ""),
            gold_smiles=r.get("gold_smiles", ""),
            query_source=r.get("query_source", ""),
            lm_id=r.get("held_out_lm_id", ""),
        )
        for r in rows
        if (query_source is None or r.get("query_source") == query_source)
        and r.get("gold_smiles")
        and r.get("gold_inchikey")
    ]
    # deterministic order before shuffle (rows come sorted by the CSV already, but be
    # explicit so the draw is stable across re-materialisations of the artifact)
    pool.sort(key=lambda c: (c.name, c.lm_id))
    rng = random.Random(seed)
    rng.shuffle(pool)
    drawn = tuple(pool[:n])
    return Subset(
        seed=seed,
        query_source=query_source,
        n_requested=n,
        cases=drawn,
        pool_size=len(pool),
        artifact=str(artifact),
    )
