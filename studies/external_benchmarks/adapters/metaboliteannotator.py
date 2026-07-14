"""MetaboliteAnnotator adapter (metabolite arm — NAME-input, name-hit-rate).

Turns the six MetaboLights sets MetaboliteAnnotator benchmarked on into a mapper-ready
``input_df`` (the MAF ``metabolite_identification`` name query + held-out gold columns) and a
``dataset_card`` recording N names, ion mode, per-accession breakdown, gold coverage, pinned
source SHA, and license. Mirrors ``necs_metabolon.py`` / ``hajjar.py``.

Design:
  - The comparable metric is a per-input NAME-HIT-RATE, so the unit is the input NAME. Rows with a
    blank ``metabolite_identification`` (MAF features with no identification) are DROPPED — they are
    not queryable input names and must not dilute the denominator. A name present but lacking a
    ``database_identifier`` is RETAINED (it is still an input name) with an empty gold — an honest
    unmatched-in-source row, never fabricated.
  - The held-out gold columns (``database_identifier`` -> gold CURIEs, ``smiles`` -> structure) are
    preserved verbatim and consumed only by the scorer's ID-concordance / charge-normalized
    qualifiers; ``provided_id_columns=[]`` keeps them out of BioMapper's sight.
  - Network is isolated behind ``fetch_maf_set`` so the transform is fully unit-testable on an
    in-memory fixture. ``fetch_maf_set`` FAILS LOUD on a needs-fetching placeholder accession, so an
    unresolved accession can never be silently scored.

ACCESSION STATUS: the six real MTBLS accessions were not obtainable (ACS full text/SI blocked); the
config ships placeholders flagged ``needs-fetching``. Fill ``config.accessions`` with the real ids
before any live run.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from typing import Any

import pandas as pd

from ..config import METABOLITEANNOTATOR_POS, NEEDS_FETCHING_SENTINEL, NameHitDatasetConfig

# Passthrough column tagging which of the six MetaboLights sets a row came from (per-accession
# coverage / traceability — never the headline).
SOURCE_ACCESSION_COL = "source_accession"

# Canonical held-out column -> candidate raw MAF headers (case-insensitive, first match wins).
QUERY_CANDIDATES: tuple[str, ...] = (
    "metabolite_identification",
    "Metabolite name",
    "metabolite_name",
    "BIOCHEMICAL",
)
GOLD_ID_CANDIDATES: tuple[str, ...] = ("database_identifier", "Database Identifier", "database_id")
GOLD_SMILES_CANDIDATES: tuple[str, ...] = ("smiles", "SMILES", "Canonical SMILES")


class AccessionNotResolvedError(RuntimeError):
    """Raised when a live fetch is attempted against an unresolved needs-fetching placeholder."""


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def parse_maf(raw: bytes) -> pd.DataFrame:
    """Parse MetaboLights MAF bytes (tab-separated) into a raw DataFrame (all cells as strings)."""
    text = raw.decode("utf-8-sig")
    sep = "\t" if (text.splitlines() and "\t" in text.splitlines()[0]) else ","
    return pd.read_csv(io.StringIO(text), sep=sep, dtype=str).fillna("")


def fetch_maf_set(accession: str, config: NameHitDatasetConfig, *, timeout: float = 60.0) -> pd.DataFrame:
    """Fetch + parse the MAF(s) for one MetaboLights accession, tagged with ``source_accession``.

    FAILS LOUD on a needs-fetching placeholder so an unresolved accession never reaches the scorer.
    Network is isolated here so the transform is unit-testable without it. The exact MAF selection
    (which m_*.tsv, filtered to ``config.mode``) is resolved against the study's ISA descriptor at
    acquisition; left as a live-only concern (this arm's accessions are still needs-fetching).
    """
    if accession.startswith(NEEDS_FETCHING_SENTINEL):
        raise AccessionNotResolvedError(
            f"accession {accession!r} is a needs-fetching placeholder — the six real MTBLS accessions "
            f"for MetaboliteAnnotator (PMID {config.source_pmid}, DOI {config.source_doi}) were not "
            f"obtainable (ACS full text/SI blocked). Fill config.accessions with the real ids first."
        )
    import requests

    url = config.source_url_template.format(accession=accession)
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    df = parse_maf(resp.content)
    df[SOURCE_ACCESSION_COL] = accession
    return df


def _norm(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _resolve_column(raw_df: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    lookup = {str(c).strip().lower(): c for c in raw_df.columns}
    for cand in candidates:
        hit = lookup.get(cand.strip().lower())
        if hit is not None:
            return hit
    return None


def build_input_df(raw_df: pd.DataFrame, config: NameHitDatasetConfig = METABOLITEANNOTATOR_POS) -> pd.DataFrame:
    """Build the mapper-ready input_df: name query + held-out gold columns (blank names dropped)."""
    query_raw = _resolve_column(raw_df, QUERY_CANDIDATES)
    if query_raw is None:
        raise KeyError(
            f"MAF is missing a recognizable metabolite-name column; tried {QUERY_CANDIDATES!r} "
            f"against {list(raw_df.columns)!r}"
        )
    gold_id_raw = _resolve_column(raw_df, GOLD_ID_CANDIDATES)
    smiles_raw = _resolve_column(raw_df, GOLD_SMILES_CANDIDATES)

    out = pd.DataFrame()
    out[config.name_column] = raw_df[query_raw].map(_norm)
    out[config.gold_id_column] = raw_df[gold_id_raw].map(_norm) if gold_id_raw is not None else ""
    if config.gold_smiles_column:
        out[config.gold_smiles_column] = raw_df[smiles_raw].map(_norm) if smiles_raw is not None else ""
    if SOURCE_ACCESSION_COL in raw_df.columns:
        out[SOURCE_ACCESSION_COL] = raw_df[SOURCE_ACCESSION_COL].map(_norm)

    # A blank name is a MAF feature with no identification: not a queryable input name -> drop it so
    # it never dilutes the name-hit denominator (the metric is per-INPUT-NAME).
    out = out[out[config.name_column] != ""].reset_index(drop=True)
    return out


def build_card(
    raw_df: pd.DataFrame,
    source_sha: str,
    config: NameHitDatasetConfig = METABOLITEANNOTATOR_POS,
) -> dict[str, Any]:
    """Build the dataset_card: N names, mode, per-accession breakdown, gold coverage, SHA, license."""
    input_df = build_input_df(raw_df, config)
    n = len(input_df)
    gold_present = int((input_df[config.gold_id_column].map(_norm) != "").sum())
    smiles_present = (
        int((input_df.get(config.gold_smiles_column, pd.Series([""] * n)).map(_norm) != "").sum())
        if config.gold_smiles_column
        else 0
    )

    per_accession: dict[str, dict[str, Any]] = {}
    if SOURCE_ACCESSION_COL in input_df.columns:
        for acc, grp in input_df.groupby(SOURCE_ACCESSION_COL):
            per_accession[str(acc)] = {
                "n_names": int(len(grp)),
                "gold_id_n": int((grp[config.gold_id_column].map(_norm) != "").sum()),
            }

    return {
        "dataset": config.key,
        "arm": config.arm,
        "entity_type": config.entity_type,
        "mode": config.mode,
        "input_type": config.input_type,
        "target_vocabs": list(config.target_vocabs),
        "n_names": n,
        "gold_id_coverage": {"n": gold_present, "fraction": (gold_present / n) if n else 0.0},
        "gold_smiles_coverage": {"n": smiles_present, "fraction": (smiles_present / n) if n else 0.0},
        "per_accession": per_accession,
        "accessions": list(config.accessions),
        "accessions_status": config.accessions_status,
        "gold_id_column": config.gold_id_column,
        "source_doi": config.source_doi,
        "source_pmid": config.source_pmid,
        "source_sha256": source_sha,
        "license": config.license,
    }


@dataclass(frozen=True)
class MetaboliteAnnotatorBundle:
    input_df: pd.DataFrame
    card: dict[str, Any]


def load_metaboliteannotator(
    source: bytes | str | pd.DataFrame | tuple[str, ...] | list[str],
    config: NameHitDatasetConfig = METABOLITEANNOTATOR_POS,
) -> MetaboliteAnnotatorBundle:
    """Load from a raw DataFrame (tests), MAF bytes, a single accession/URL, or an accessions tuple.

    For an accessions tuple/list each set is fetched via ``fetch_maf_set`` (fails loud on a
    placeholder) and concatenated; the card's SHA is pinned over the concatenated CSV bytes so the
    scored set is reproducible. Network stays isolated in ``fetch_maf_set``.
    """
    if isinstance(source, pd.DataFrame):
        raw_df = source
        raw_bytes = raw_df.to_csv(index=False).encode("utf-8")
    elif isinstance(source, (tuple, list)):
        frames = [fetch_maf_set(acc, config) for acc in source]
        raw_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        raw_bytes = raw_df.to_csv(index=False).encode("utf-8")
    elif isinstance(source, bytes):
        raw_bytes = source
        raw_df = parse_maf(raw_bytes)
    elif isinstance(source, str):
        raw_df = fetch_maf_set(source, config)
        raw_bytes = raw_df.to_csv(index=False).encode("utf-8")
    else:
        raise TypeError(f"unsupported source type {type(source)!r}")

    sha = sha256_bytes(raw_bytes)
    return MetaboliteAnnotatorBundle(input_df=build_input_df(raw_df, config), card=build_card(raw_df, sha, config))
