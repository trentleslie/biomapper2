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

# Completeness floor for the reportable accuracy arm. A retained CID is a row we KEPT for scoring
# because it carried a held-out PubChem CID (the accuracy-eligible population). If the external
# PubChem resolver returns no InChIKey for such a row, the structure scorer silently drops it from
# its denominator. Any tolerance < 1.0 therefore leaves the scored denominator dependent on WHICH
# CIDs happened to resolve — and an empty InChIKey is indistinguishable at scoring time between a
# genuinely structure-less CID and a transient outage — so even a small allowance reports accuracy
# over a moving, outage-dependent subset. We require FULL resolution of the retained population:
# every retained CID must resolve to a gold InChIKey or the run fails closed, listing the offenders.
# A CID that genuinely has no PubChem InChIKey must be pruned from the pinned subsample WITH A
# DOCUMENTED REASON and the run re-run, so the reported number is always over a fixed, fully-resolved
# eligible population (never a silently-shrunk one).
MIN_GOLD_RESOLUTION = 1.0

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


def gold_resolution_report(
    mapped_df: pd.DataFrame,
    *,
    pubchem_col: str,
    gold_col: str,
) -> dict[str, Any]:
    """Report how completely the retained held-out PubChem CIDs resolved to a gold InChIKey.

    The eligible population is the rows carrying a non-empty ``pubchem_col`` (accuracy-eligible: the
    adapter keeps only structure-resolvable rows). ``resolved`` counts those whose ``gold_col`` came
    back non-empty from the external resolver; the difference is the population the scorer would
    silently drop. Recording this makes the exact scored denominator reproducible and an outage
    detectable, per the fail-closed rule below.
    """

    def _nonempty(v: Any) -> bool:
        return bool(str(v).strip()) if v is not None else False

    retained_mask = mapped_df[pubchem_col].map(_nonempty) if pubchem_col in mapped_df.columns else None
    retained = int(retained_mask.sum()) if retained_mask is not None else 0
    if retained == 0:
        return {"retained": 0, "resolved": 0, "unresolved": 0, "completeness": None, "unresolved_cids": []}
    resolved_mask = retained_mask & mapped_df[gold_col].map(_nonempty)
    resolved = int(resolved_mask.sum())
    unresolved_cids = sorted(
        str(c).strip() for c in mapped_df.loc[retained_mask & ~mapped_df[gold_col].map(_nonempty), pubchem_col]
    )
    return {
        "retained": retained,
        "resolved": resolved,
        "unresolved": retained - resolved,
        "completeness": resolved / retained,
        "unresolved_cids": unresolved_cids,
    }


def assert_gold_resolution_complete(report: dict[str, Any], *, min_completeness: float = MIN_GOLD_RESOLUTION) -> None:
    """Fail CLOSED when gold-InChIKey resolution over the retained CIDs is below ``min_completeness``.

    An outage-scale shortfall means the scored population moved silently, so the accuracy number is
    not comparable — refuse to persist it. ``completeness is None`` (no retained CIDs) also raises,
    since there is nothing legitimate to score.
    """
    completeness = report.get("completeness")
    if completeness is None:
        raise ValueError(
            "gold resolution: no retained PubChem CIDs to resolve — the accuracy arm has an empty "
            "eligible population; refusing to report."
        )
    if completeness < min_completeness:
        raise ValueError(
            f"gold resolution incomplete: {report['resolved']}/{report['retained']} retained PubChem "
            f"CIDs resolved to an InChIKey ({completeness:.3f} < floor {min_completeness:.3f}). A "
            f"partial PubChem outage would silently move the scored population and make the reported "
            f"accuracy incomparable — refusing to persist. Unresolved: {report['unresolved_cids'][:10]}"
        )


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
