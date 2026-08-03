"""Cross-source gold resolution + independence audit for the lipid ACCURACY arm.

Goslin emits no InChIKey, so the gold structure comes from SOME lookup DB. To keep the accuracy honest
the gold must be resolved on infrastructure DISJOINT from BioMapper's resolution path and must NOT be a
Kraken ingest source. This resolves the held-out SwissLipids PubChem CID -> InChIKey first-block via the
INDEPENDENT PubChem resolver (external, non-KG), and records a per-run independence audit that fails
loud if the disjointness or non-Kraken-gold invariants are violated.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# Sources ingested into Kraken: an accuracy gold drawn from any of these is circular (its structure
# co-descends with BioMapper's binding). SwissLipids / PubChem / experimental sets are NOT here.
KRAKEN_INGEST_SOURCES = frozenset({"LIPIDMAPS", "REFMET"})

_RESIDUAL_CAVEAT = (
    "Structure scored against an InChIKey resolved by an external, non-KG source disjoint from the "
    "resolution-path binding. Residual nomenclature-standard overlap remains: Goslin's grammars and "
    "the gold's names both descend from the Liebisch 2020 / LIPID MAPS shorthand standard, so this is "
    "structure-independent but classification-shared (not fully independent)."
)


def resolve_gold_inchikey_blocks(
    input_df: pd.DataFrame,
    resolver: Any,
    *,
    pubchem_col: str,
    out_col: str,
) -> pd.DataFrame:
    """Fill ``out_col`` with the PubChem-resolved InChIKey first-block for each held-out PubChem CID.

    Fail-soft: a blank/unresolvable CID leaves the row's ``out_col`` empty (the structure-oracle scorer
    then excludes it from the accuracy denominator, exactly like a missing gold structure).
    """
    out = input_df.copy()
    blocks: list[str] = []
    for cid in out[pubchem_col].astype(str):
        cid = cid.strip()
        block = resolver.block_for_pubchem(cid) if cid else None
        blocks.append(block or "")
    out[out_col] = blocks
    return out


def independence_audit(
    *,
    binding_source: str,
    gold_source: str,
    lipidmaps_rest_fired: bool,
    dialect_breakdown: dict[str, int],
) -> dict[str, Any]:
    """Record + ENFORCE the disjointness invariants for a lipid accuracy run (fail-loud)."""
    if gold_source.upper() in KRAKEN_INGEST_SOURCES:
        raise ValueError(
            f"Independence violation: gold source {gold_source!r} is a Kraken ingest source "
            f"({sorted(KRAKEN_INGEST_SOURCES)}). A lipid accuracy gold must be a non-Kraken source "
            f"(SwissLipids / PubChem / experimental)."
        )
    if binding_source.strip().upper() == gold_source.strip().upper():
        raise ValueError(
            f"Independence violation: resolution-path binding source and gold source are both "
            f"{gold_source!r} — they must be disjoint (resolution-path vs scoring-path rule)."
        )
    return {
        "resolution_path_binding_source": binding_source,
        "gold_structure_source": gold_source,
        "gold_is_kraken_ingest_source": False,
        "disjoint": True,
        "lipidmaps_rest_enrichment_fired": lipidmaps_rest_fired,
        "goslin_dialect_breakdown": dict(dialect_breakdown),
        "residual_caveat": _RESIDUAL_CAVEAT,
    }
