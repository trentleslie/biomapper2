"""Provided-ID (identifier-input) adapters.

Reshape an existing name-input bundle into a provided-ID ``input_df``: a single SOURCE id column
(named so the biomapper2 normalizer recognizes its vocab) plus the HELD-OUT gold TARGET columns
(carried verbatim, consumed only by the scorer) and an inert placeholder name column (unused under
``annotation_mode='none'``). Two source families, both reusing already-built machinery:

  - **Gene/protein backbones** — reuse ``backbones.load_backbone`` (streaming + reservoir subsample
    + persisted-subsample reproducibility), then map its bare source column (``gene_id`` /
    ``uniprotkb_ac``) into the provided source column and keep the authoritative gold cross-refs
    held out.
  - **Metabolite (Hajjar)** — reuse ``hajjar.load_hajjar``; the curated ChEBI id becomes the
    provided source, the curated InChIKey stays held out (the ChEBI -> InChIKey parity anchor).

ANTI-TRIVIAL-100%: the source column is disjoint from the gold TARGET columns by construction (the
``ProvidedIdDatasetConfig`` invariant already refuses any overlap); this adapter additionally
re-checks via ``assert_target_held_out`` so a mis-wired backbone column fails loud here, not silently
at scoring time.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import HAJJAR, CurieDatasetConfig, ProvidedIdDatasetConfig
from ..scorers.provided_id_scorer import assert_target_held_out


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _bare_local(value: Any) -> str:
    """A clean bare local id for the provided source column.

    The normalizer accepts a prefixed value (``CHEBI:15377``) and strips the prefix itself, but we
    normalize to the bare local id up front so the persisted subsample is unambiguous. HTTP-like
    values are left untouched.
    """
    s = "" if value is None else str(value).strip()
    if not s or s.lower() == "nan":
        return ""
    if ":" in s and not s.startswith("http"):
        return s.split(":", 1)[1].strip()
    return s


@dataclass(frozen=True)
class ProvidedIdBundle:
    input_df: pd.DataFrame
    card: dict[str, Any]


def build_provided_input_df(name_input_df: pd.DataFrame, config: ProvidedIdDatasetConfig) -> pd.DataFrame:
    """Reshape a name-input df into a provided-ID df: source id + held-out gold + placeholder name.

    ``config.backbone_source_column`` names the column in ``name_input_df`` that supplies the source
    id; every ``config.gold_target_columns`` column is carried verbatim (held out). The placeholder
    name column is empty — provided-ID mode never consults it (annotation_mode='none').
    """
    assert_target_held_out(config)  # fail loud here, not at scoring time
    src_col = config.backbone_source_column
    if src_col is None or src_col not in name_input_df.columns:
        raise KeyError(
            f"{config.key}: backbone_source_column {src_col!r} not present in the source frame "
            f"(columns: {list(name_input_df.columns)})"
        )
    out = pd.DataFrame()
    out[config.name_column] = ["" for _ in range(len(name_input_df))]  # inert placeholder query
    out[config.source_id_column] = name_input_df[src_col].map(_bare_local)
    for _namespace, column in config.gold_target_columns:
        if column not in name_input_df.columns:
            raise KeyError(f"{config.key}: gold target column {column!r} missing from source frame")
        out[column] = name_input_df[column]  # held out, verbatim
    return out


def build_card(
    input_df: pd.DataFrame,
    *,
    source_sha: str,
    config: ProvidedIdDatasetConfig,
    n_scanned: int | None = None,
    source_version: str | None = None,
) -> dict[str, Any]:
    """Provided-ID dataset card: N, source id column/namespace, held-out gold identity, coverage, SHA."""
    n = len(input_df)
    n_with_source = int(input_df[config.source_id_column].map(lambda s: bool(str(s).strip())).sum())
    coverage: dict[str, dict[str, Any]] = {}
    for namespace, column in config.gold_target_columns:
        col = input_df[column] if column in input_df.columns else pd.Series([""] * n)
        present = int(col.map(lambda s: bool(str(s).strip())).sum())
        coverage[namespace] = {"n": present, "fraction": (present / n) if n else 0.0}
    return {
        "dataset": config.key,
        "arm": config.arm,
        "entity_type": config.entity_type,
        "input_type": config.input_type,
        "mode": "provided_id",
        "annotation_mode": config.annotation_mode,
        # The load-bearing anti-trivial record: the source PROVIDED to BioMapper vs the gold HELD OUT.
        "source_id_column": config.source_id_column,
        "source_namespace": config.source_namespace,
        "provided_id_columns": [config.source_id_column],
        "gold_target_columns": {ns: col for ns, col in config.gold_target_columns},
        "target_vocabs": list(config.target_vocabs),
        "n_rows": n,
        "n_scanned": n_scanned,
        "coverage": {"source_id": {"n": n_with_source, "fraction": (n_with_source / n) if n else 0.0}, **coverage},
        "source_label": config.source_label,
        "source_url": config.source_url,
        "source_sha256": source_sha,
        "subsample_filename": subsample_filename(config.key),
        "source_version": source_version,
        "license": config.license,
    }


def subsample_filename(key: str) -> str:
    return f"{key}_subsample.csv"


def subsample_csv_bytes(input_df: pd.DataFrame) -> bytes:
    return input_df.to_csv(index=False).encode("utf-8")


def persist_subsample(bundle: ProvidedIdBundle, out_dir: Path | str) -> Path:
    """Persist the exact scored provided-ID input beside the card, so the run is reconstructable."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / subsample_filename(bundle.card["dataset"])
    path.write_bytes(subsample_csv_bytes(bundle.input_df))
    return path


def load_provided_backbone(
    source: Any,
    config: ProvidedIdDatasetConfig,
    backbone_config: CurieDatasetConfig,
    *,
    source_version: str | None = None,
) -> ProvidedIdBundle:
    """Load a gene/protein provided-ID set by reusing the backbone streaming/subsample machinery.

    ``source`` is a URL string (streamed) or a line iterator (tests), handed straight to
    ``backbones.load_backbone``; the resulting name-input subsample is reshaped to provided-ID form.
    The SHA is recomputed over the reshaped provided-ID subsample bytes (what actually gets scored).
    """
    from . import backbones

    backbone_bundle = backbones.load_backbone(source, backbone_config, source_version=source_version)
    input_df = build_provided_input_df(backbone_bundle.input_df, config)
    sha = sha256_bytes(subsample_csv_bytes(input_df))
    card = build_card(
        input_df,
        source_sha=sha,
        config=config,
        n_scanned=backbone_bundle.card.get("n_scanned"),
        source_version=backbone_bundle.card.get("source_version", source_version),
    )
    return ProvidedIdBundle(input_df=input_df, card=card)


def load_provided_hajjar(source: Any, config: ProvidedIdDatasetConfig) -> ProvidedIdBundle:
    """Load the metabolite provided-ID anchor by reusing the Hajjar adapter (ChEBI -> InChIKey).

    ``source`` is raw bytes / URL / DataFrame, handed to ``hajjar.load_hajjar``; the curated ChEBI
    becomes the provided source and the curated InChIKey stays held out.
    """
    from . import hajjar

    hajjar_bundle = hajjar.load_hajjar(source, HAJJAR)
    input_df = build_provided_input_df(hajjar_bundle.input_df, config)
    sha = sha256_bytes(subsample_csv_bytes(input_df))
    card = build_card(input_df, source_sha=sha, config=config, n_scanned=len(input_df))
    return ProvidedIdBundle(input_df=input_df, card=card)


def load_provided(
    source: Any,
    config: ProvidedIdDatasetConfig,
    backbone_config: CurieDatasetConfig | None = None,
    *,
    source_version: str | None = None,
) -> ProvidedIdBundle:
    """Dispatch to the backbone or Hajjar provided-ID loader based on ``backbone_config``."""
    if backbone_config is not None:
        return load_provided_backbone(source, config, backbone_config, source_version=source_version)
    return load_provided_hajjar(source, config)
