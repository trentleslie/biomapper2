"""Unit 1 - draw the graded subset from the 887 MetaNetX-cap-PubChem agreements.

The gold referent sets are already materialised in the Pham run artifact:

* ``pham-disambiguation_stratified_subsample.csv`` - columns
  ``metabolite_name``, ``gold_referent_inchikeys`` (pipe-separated full
  InChIKeys), ``gold_referent_ids``, ``gold_metanetx_ids``, ``referent_count``,
  ``stratum`` (non_lipid / lipid). This IS the seed-42 draw; we do NOT re-sample
  it, we sample WITHIN the agreement subset with a fresh seed.
* ``pubchem_crosscheck.json`` - per-name ``agrees`` flag (first-block level).
  The 887 ``agrees == true`` names are the agreement pool.

We restrict to the NON-LIPID agreements (835 of the 887) so the draw is
comparable to BioMapper's 41.7% anchor, which is the non-lipid stratum. Override
``stratum=None`` to draw across both strata.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

# The ambiguous-only Pham run artifact (pinned by the spec). Kept as a default;
# override on the CLI. NOT under version control (it is a run output), so its
# provenance is pinned via ``source_sha256`` on the dataset card, recorded into
# the spike artifact by run_spike.py.
DEFAULT_ARTIFACT = Path.home() / "external_benchmark_runs" / "pham_ambonly_20260716T220912Z"


@dataclass(frozen=True)
class GoldCase:
    """One name and its curated referent InChIKey set (the answer key)."""

    name: str
    gold_inchikeys: tuple[str, ...]  # full InChIKeys, from the MetaNetX source
    stratum: str
    referent_count: int


@dataclass(frozen=True)
class Subset:
    """A seed-pinned draw plus everything needed to reproduce it."""

    seed: int
    stratum: str | None
    n_requested: int
    cases: tuple[GoldCase, ...]
    pool_size: int  # size of the agreement pool the draw came from
    artifact: str = field(default="")

    def as_card(self) -> dict:
        return {
            "seed": self.seed,
            "stratum": self.stratum,
            "n_requested": self.n_requested,
            "n_drawn": len(self.cases),
            "agreement_pool_size": self.pool_size,
            "artifact": self.artifact,
            "names": [c.name for c in self.cases],
        }


def _load_agreement_names(artifact: Path) -> set[str]:
    cc = json.loads((artifact / "pubchem_crosscheck.json").read_text())
    return {name for name, v in cc.items() if v.get("agrees") is True}


def _load_gold(artifact: Path) -> dict[str, GoldCase]:
    gold: dict[str, GoldCase] = {}
    csv_path = artifact / "pham-disambiguation_stratified_subsample.csv"
    with csv_path.open() as fh:
        for row in csv.DictReader(fh):
            keys = tuple(k for k in row["gold_referent_inchikeys"].split("|") if k)
            gold[row["metabolite_name"]] = GoldCase(
                name=row["metabolite_name"],
                gold_inchikeys=keys,
                stratum=row["stratum"],
                referent_count=int(row["referent_count"]),
            )
    return gold


def draw_subset(
    *,
    seed: int,
    n: int = 75,
    stratum: str | None = "non_lipid",
    artifact: Path = DEFAULT_ARTIFACT,
) -> Subset:
    """Draw ``n`` agreement cases with a fresh, recorded ``seed``.

    ``seed`` MUST NOT be 42 (the draw that defines the benchmark's 1,500-name
    eval set); measuring the difficulty estimate on the exact set that seeds the
    benchmark would contaminate it. ``run_spike`` enforces this.
    """
    import random

    agreement = _load_agreement_names(artifact)
    gold = _load_gold(artifact)

    pool = [
        gold[name]
        for name in sorted(agreement)  # sort => deterministic order before shuffle
        if name in gold and (stratum is None or gold[name].stratum == stratum)
    ]
    rng = random.Random(seed)
    rng.shuffle(pool)
    drawn = tuple(pool[:n])
    return Subset(
        seed=seed,
        stratum=stratum,
        n_requested=n,
        cases=drawn,
        pool_size=len(pool),
        artifact=str(artifact),
    )
