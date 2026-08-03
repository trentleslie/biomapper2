"""Suhre 2010 adapter: canonical D* -> mapper-ready input_df + dataset card.

The mapper is later called with name_column=config.name_column and
provided_id_columns=[] — so the gold + measurement columns ride along into the
output untouched and are consumed only by the oracle arm / scorers, never by
BioMapper. Network is isolated behind fetch_supplement so the transform is fully
offline-testable.
"""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import SUHRE, NorthStarConfig
from ..gold import CANONICAL_CSV

RAW_NAME = "name"
RAW_HMDB = "hmdb"
RAW_CHEBI = "chebi"
RAW_KEGG = "kegg_compound"
RAW_DIR = "direction"
RAW_Q = "qvalue"


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fetch_supplement(url: str, *, timeout: float = 30.0) -> bytes:
    """Fetch the Suhre supplement bytes (network). Isolated so tests never hit it."""
    import requests

    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.content


def parse_raw(raw: bytes) -> pd.DataFrame:
    text = raw.decode("utf-8-sig")
    return pd.read_csv(io.StringIO(text), dtype=str).fillna("")


def _norm(v: Any) -> str:
    return "" if v is None else str(v).strip()


def build_input_df(raw_df: pd.DataFrame, config: NorthStarConfig = SUHRE) -> pd.DataFrame:
    out = pd.DataFrame()
    out[config.name_column] = raw_df[RAW_NAME].map(_norm)
    out[config.gold_chebi_column] = raw_df[RAW_CHEBI].map(_norm)
    out[config.gold_hmdb_column] = raw_df[RAW_HMDB].map(_norm)
    out[config.gold_kegg_column] = raw_df[RAW_KEGG].map(_norm)
    out[config.direction_column] = raw_df[RAW_DIR].map(_norm)
    out[config.qvalue_column] = raw_df[RAW_Q].map(_norm)
    return out


def build_card(raw_df: pd.DataFrame, source_sha: str, config: NorthStarConfig = SUHRE) -> dict:
    df = build_input_df(raw_df, config)
    return {
        "dataset": config.key,
        "entity_type": config.entity_type,
        "n_rows": len(df),
        "target_vocab": config.target_vocab,
        "pathway_vocab": config.pathway_vocab,
        "source_doi": config.source_doi,
        "source_sha256": source_sha,
    }


@dataclass(frozen=True)
class SuhreBundle:
    input_df: pd.DataFrame
    card: dict


def load_suhre(source: bytes | str | pd.DataFrame | None = None, config: NorthStarConfig = SUHRE) -> SuhreBundle:
    """Load from the committed CSV (default), raw bytes, a URL, or a DataFrame."""
    if source is None:
        raw_bytes = Path(CANONICAL_CSV).read_bytes()
        raw_df = parse_raw(raw_bytes)
    elif isinstance(source, pd.DataFrame):
        raw_df = source
        raw_bytes = raw_df.to_csv(index=False).encode("utf-8")
    elif isinstance(source, bytes):
        raw_bytes = source
        raw_df = parse_raw(raw_bytes)
    elif isinstance(source, str):
        raw_bytes = fetch_supplement(source)
        raw_df = parse_raw(raw_bytes)
    else:
        raise TypeError(f"unsupported source type {type(source)!r}")
    sha = sha256_bytes(raw_bytes)
    return SuhreBundle(input_df=build_input_df(raw_df, config), card=build_card(raw_df, sha, config))
