"""Construct the messy input D̃ from the clean D*.

Perturbation operates on surface forms only, holding the underlying entity
fixed, so the hidden gold mapping G (surface -> canonical name) is always known.
Three operators at the slice's moderate level, applied independently per entity
under a pinned seed:
  - synonym substitution (dextrose for D-glucose, ...) drawn from a table OUTSIDE
    BioMapper's resolver path; overlap with the resolver's own synonyms is
    impossible to eliminate and is reported honestly, not claimed away.
  - namespace mixing: express some rows as raw KEGG C-numbers.
  - typos: a single controlled character edit.

G is sacrosanct: logged for the oracle / diagnostic arms only; it never feeds the
product arm's answer.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import pandas as pd

from .config import SUHRE, NorthStarConfig

# Real synonyms, sourced independently of BioMapper's resolution path.
SYNONYMS: dict[str, str] = {
    "D-glucose": "dextrose",
    "L-valine": "valine",
    "L-leucine": "leucine",
    "L-isoleucine": "isoleucine",
    "L-alanine": "2-aminopropanoic acid",
    "L-tyrosine": "tyrosine",
    "L-phenylalanine": "phenylalanine",
    "glycine": "aminoacetic acid",
    "L-serine": "serine",
    "L-glutamine": "glutamine",
    "citrate": "citric acid",
    "pyruvate": "pyruvic acid",
    "L-lactate": "lactic acid",
    "2-hydroxybutyrate": "2-hydroxybutyric acid",
    "acetylcarnitine": "O-acetylcarnitine",
}


@dataclass(frozen=True)
class MessResult:
    messy_df: pd.DataFrame
    hidden_mapping: dict[str, str]  # surface form -> canonical name
    operators_applied: dict[str, str]  # canonical name -> operator label


def _typo(name: str, rng: random.Random) -> str:
    if len(name) < 4:
        return name
    i = rng.randrange(1, len(name) - 1)
    return name[:i] + name[i + 1 :]  # drop one interior character


def make_messy(
    input_df: pd.DataFrame,
    config: NorthStarConfig = SUHRE,
    synonyms: dict[str, str] = SYNONYMS,
    seed: int | None = None,
) -> MessResult:
    rng = random.Random(config.mess_seed if seed is None else seed)
    out = input_df.copy(deep=True)
    hidden: dict[str, str] = {}
    ops: dict[str, str] = {}

    surfaces: list[str] = []
    for _, row in input_df.iterrows():
        canonical = str(row[config.name_column]).strip()
        kegg = str(row[config.gold_kegg_column]).strip()
        roll = rng.random()
        if roll < 0.40 and canonical in synonyms:
            surface, op = synonyms[canonical], "synonym"
        elif roll < 0.70 and kegg:
            surface, op = kegg, "namespace_mixing"  # raw KEGG C-number in the name column
        elif roll < 0.90:
            surface, op = _typo(canonical, rng), "typo"
        else:
            surface, op = canonical, "clean"
        # Guarantee G is invertible: on an accidental collision, fall back to clean.
        if surface in hidden and hidden[surface] != canonical:
            surface, op = canonical, "clean"
        surfaces.append(surface)
        hidden[surface] = canonical
        ops[canonical] = op

    out[config.name_column] = surfaces
    return MessResult(messy_df=out, hidden_mapping=hidden, operators_applied=ops)
