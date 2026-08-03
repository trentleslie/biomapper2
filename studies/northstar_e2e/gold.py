"""A* — the known downstream answer for the Suhre 2010 T2D slice.

The gold is a curated set of altered metabolites and, more importantly, the
established altered-pathway set (KEGG) for T2D serum metabolomics, plus the
disease label. NONE of these is an identifier the resolver produced: the pathway
set is a fact from replicated epidemiology (Suhre 2010 / Drogan 2015 / Lu 2016),
independent of how the entities are spelled. That independence is the whole point.

VERIFICATION (do before any scored run): confirm each row's direction and each
gold pathway against the three DOIs, and confirm every gold KEGG compound is a
member of at least one gold pathway in data/kegg_compound_pathway.tsv (Task 5).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
CANONICAL_CSV = DATA_DIR / "suhre2010_canonical.csv"

SOURCE_DOIS = (
    "10.1371/journal.pone.0013953",  # Suhre et al. 2010 (primary D*)
    "10.1373/clinchem.2014.228965",  # Drogan et al. 2015 (replication cross-check)
    "10.1007/s00125-016-4069-2",  # Lu et al. 2016 (replication cross-check)
)

DISEASE_LABEL = "type 2 diabetes"

# Established altered-pathway set for T2D serum metabolomics, KEGG vocabulary
# (fixed up front — do not mix Reactome; databases disagree, Mubeen 2019).
GOLD_PATHWAYS: tuple[str, ...] = (
    "map00280",  # Valine, leucine and isoleucine degradation (BCAA catabolism, up)
    "map00250",  # Alanine, aspartate and glutamate metabolism
    "map00260",  # Glycine, serine and threonine metabolism
    "map00020",  # Citrate cycle (TCA)
    "map00010",  # Glycolysis / Gluconeogenesis
)

GOLD_PATHWAY_NAMES: dict[str, str] = {
    "map00280": "Valine, leucine and isoleucine degradation",
    "map00250": "Alanine, aspartate and glutamate metabolism",
    "map00260": "Glycine, serine and threonine metabolism",
    "map00020": "Citrate cycle (TCA cycle)",
    "map00010": "Glycolysis / Gluconeogenesis",
}


@dataclass(frozen=True)
class GoldMetabolite:
    name: str
    hmdb: str
    chebi: str
    kegg_compound: str
    direction: str  # "up" | "down"
    qvalue: float


def _load_gold_metabolites() -> tuple[GoldMetabolite, ...]:
    with CANONICAL_CSV.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return tuple(
        GoldMetabolite(
            name=r["name"].strip(),
            hmdb=r["hmdb"].strip(),
            chebi=r["chebi"].strip(),
            kegg_compound=r["kegg_compound"].strip(),
            direction=r["direction"].strip(),
            qvalue=float(r["qvalue"]),
        )
        for r in rows
    )


GOLD_METABOLITES: tuple[GoldMetabolite, ...] = _load_gold_metabolites()


def assert_known_answer() -> None:
    """Structural gate on A*. Raises AssertionError on any violation.

    This does NOT verify biological truth (that is the manual DOI cross-check);
    it guards the shape the pipeline relies on so a malformed gold can't silently
    poison a scored run.
    """
    assert 12 <= len(GOLD_METABOLITES) <= 18, "gold metabolite count out of slice range"
    assert 3 <= len(GOLD_PATHWAYS) <= 5, "gold pathway count out of slice range"
    assert set(GOLD_PATHWAYS) <= set(GOLD_PATHWAY_NAMES), "pathway name missing"
    for m in GOLD_METABOLITES:
        assert m.name, "empty metabolite name"
        assert m.hmdb.startswith("HMDB"), f"bad HMDB: {m.hmdb}"
        assert m.chebi.startswith("CHEBI:"), f"bad ChEBI: {m.chebi}"
        assert m.kegg_compound.startswith("C") and m.kegg_compound[1:].isdigit(), m.kegg_compound
        assert m.direction in {"up", "down"}, f"bad direction: {m.direction}"
