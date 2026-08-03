"""Registry for the north-star end-to-end slice."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NorthStarConfig:
    key: str
    entity_type: str  # Biolink-standardizable, e.g. "metabolite"
    name_column: str  # the query column handed to mapper.name_column
    gold_chebi_column: str  # held-out ground-truth ChEBI (oracle arm only)
    gold_hmdb_column: str
    gold_kegg_column: str  # held-out gold KEGG compound (oracle arm + provenance)
    direction_column: str  # measurement: "up" / "down" (rides along, never resolved)
    qvalue_column: str
    question: str  # the interpretation question posed to the pipeline
    pathway_vocab: str  # fixed vocabulary; "KEGG" (never mix Reactome)
    source_doi: str
    source_url: str  # supplement URL; "" when the canonical CSV is committed
    target_vocab: str  # mapper target vocab for the annotation stage
    mess_seed: int  # pinned seed for reproducible perturbation


SUHRE = NorthStarConfig(
    key="suhre-t2d",
    entity_type="metabolite",
    name_column="metabolite_name",
    gold_chebi_column="gold_chebi",
    gold_hmdb_column="gold_hmdb",
    gold_kegg_column="gold_kegg",
    direction_column="direction",
    qvalue_column="qvalue",
    question=(
        "Which metabolic pathways or processes are dysregulated in cases relative "
        "to controls, and what condition is most consistent with this profile?"
    ),
    pathway_vocab="KEGG",
    source_doi="10.1371/journal.pone.0013953",
    source_url="",  # canonical table is committed (data/suhre2010_canonical.csv)
    target_vocab="CHEBI",
    mess_seed=20260725,
)
