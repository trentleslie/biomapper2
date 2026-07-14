"""Hajjar-100 adapter.

Turns the paper's curated 100-metabolite supplement into a mapper-ready ``input_df``
(a name query plus held-out gold ChEBI + gold InChIKey columns) and a ``dataset_card``
recording N, input_type, per-vocab/structure coverage, source SHA, and license.

Network is isolated behind ``fetch_supplement`` so the transform (``build_input_df`` /
``build_card``) is fully unit-testable on an in-memory fixture. The gold InChIKey column
is preserved *verbatim* — it is the independent structure oracle and must share no infra
with the system under test.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from typing import Any

import pandas as pd

from ..config import HAJJAR, DatasetConfig

# Raw supplement column names -> our canonical held-out column names. Resolved against the
# paper's supplement at acquisition; kept here so a format change is a one-line edit.
RAW_NAME_COL = "Metabolite name"
RAW_CHEBI_COL = "ChEBI ID"
RAW_INCHIKEY_COL = "InChIKey"
RAW_SMILES_COL = "SMILES"

# Marks rows retained for coverage accounting but excluded from the accuracy denominator.
HAS_STRUCTURE_COL = "has_gold_structure"


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fetch_supplement(url: str, *, timeout: float = 30.0) -> bytes:
    """Fetch the Hajjar supplement bytes (network). Isolated so tests never hit it."""
    import requests

    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.content


def parse_raw(raw: bytes) -> pd.DataFrame:
    """Parse supplement bytes into a raw DataFrame (CSV/TSV auto-detected)."""
    text = raw.decode("utf-8-sig")
    sep = "\t" if text.splitlines() and "\t" in text.splitlines()[0] else ","
    return pd.read_csv(io.StringIO(text), sep=sep, dtype=str).fillna("")


def _norm(value: Any) -> str:
    return "" if value is None else str(value).strip()


def build_input_df(raw_df: pd.DataFrame, config: DatasetConfig = HAJJAR) -> pd.DataFrame:
    """Build the mapper-ready input_df: name query + held-out gold columns.

    The mapper is later called with ``name_column=config.name_column`` and
    ``provided_id_columns=[]`` — so the gold columns ride along untouched into the output
    and are consumed only by the scorers, never by BioMapper.
    """
    out = pd.DataFrame()
    out[config.name_column] = raw_df[RAW_NAME_COL].map(_norm)
    out[config.gold_chebi_column] = raw_df[RAW_CHEBI_COL].map(_norm)
    out[config.gold_inchikey_column] = raw_df[RAW_INCHIKEY_COL].map(_norm)  # verbatim
    if config.gold_smiles_column and RAW_SMILES_COL in raw_df.columns:
        out[config.gold_smiles_column] = raw_df[RAW_SMILES_COL].map(_norm)
    # A row missing gold InChIKey is retained but marked no-structure: excluded from the
    # accuracy denominator later, still counted in coverage.
    out[HAS_STRUCTURE_COL] = out[config.gold_inchikey_column].map(lambda s: bool(_norm(s)))
    return out


def build_card(
    raw_df: pd.DataFrame,
    source_sha: str,
    config: DatasetConfig = HAJJAR,
) -> dict[str, Any]:
    """Build the dataset_card: N, input_type, coverage, pinned source SHA, license."""
    input_df = build_input_df(raw_df, config)
    n = len(input_df)
    n_with_inchikey = int(input_df[HAS_STRUCTURE_COL].sum())
    n_with_chebi = int((input_df[config.gold_chebi_column].map(_norm) != "").sum())
    return {
        "dataset": config.key,
        "arm": config.arm,
        "entity_type": config.entity_type,
        "input_type": config.input_type,
        "target_vocabs": list(config.target_vocabs),
        "n_rows": n,
        "coverage": {
            "gold_inchikey": {"n": n_with_inchikey, "fraction": (n_with_inchikey / n) if n else 0.0},
            "gold_chebi": {"n": n_with_chebi, "fraction": (n_with_chebi / n) if n else 0.0},
        },
        "source_doi": config.source_doi,
        "source_sha256": source_sha,
        "license": config.license,
    }


@dataclass(frozen=True)
class HajjarBundle:
    input_df: pd.DataFrame
    card: dict[str, Any]


def load_hajjar(source: bytes | str | pd.DataFrame, config: DatasetConfig = HAJJAR) -> HajjarBundle:
    """Load Hajjar from raw bytes (SHA pinned), a URL string (fetched), or a raw DataFrame.

    When ``source`` is a DataFrame the card's ``source_sha256`` is computed over its
    canonical CSV bytes so the pin is still deterministic for tests.
    """
    if isinstance(source, pd.DataFrame):
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
    return HajjarBundle(input_df=build_input_df(raw_df, config), card=build_card(raw_df, sha, config))
