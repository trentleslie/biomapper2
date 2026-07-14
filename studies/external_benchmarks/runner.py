"""Unit 2 — batch runner over ``mapper.map_dataset_to_kg`` (mapper unmodified).

One run per target vocab, name query only (``provided_id_columns=[]``,
``annotation_mode='all'``), each into a timestamped dir with the mapper's own
``*_MAPPED`` splits + summary_stats, plus a fully-pinned manifest. Save-by-default:
outputs are always persisted; ``out_dir`` is an override, not the only way to save.

An anti-trivial-100% guard asserts *assigned* stats are non-null: with name-only input,
every mapping must come through the annotate/assign path. If assigned mappings are zero,
the gold likely leaked in as a provided id (the trivial ``chosen==gold`` trap) and we
refuse the run.
"""

from __future__ import annotations

import datetime as _dt
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from biomapper2.config import BIOLINK_VERSION_DEFAULT, KESTREL_API_URL

from .config import DatasetConfig


class TrivialMappingError(RuntimeError):
    """Raised when assigned mappings are zero — signals the gold-as-provided trap."""


def assigned_stats_nonnull(stats: dict[str, Any]) -> bool:
    """True iff the run produced at least one *assigned* KG mapping.

    Name-only input with ``annotation_mode='all'`` must resolve via the assign path; zero
    assigned mappings means the gold column leaked into the provided-id path.
    """
    return int(stats.get("mapped_to_kg_assigned", 0) or 0) > 0


def _git_commit(repo_root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def build_manifest(
    *,
    vocab: str,
    config: DatasetConfig,
    dataset_sha: str,
    biolink_version: str,
    output_tsv: str,
    repo_root: Path,
) -> dict[str, Any]:
    return {
        "dataset": config.key,
        "vocab": vocab,
        "entity_type": config.entity_type,
        "input_type": config.input_type,
        "annotation_mode": "all",
        "provided_id_columns": [],
        "biomapper2_commit": _git_commit(repo_root),
        "kestrel_api_url": KESTREL_API_URL,
        "biolink_version": biolink_version,
        "dataset_source_sha256": dataset_sha,
        "output_tsv": output_tsv,
        "timestamp_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }


@dataclass
class VocabRun:
    vocab: str
    ok: bool
    output_tsv: str | None
    stats: dict[str, Any] | None
    manifest: dict[str, Any] | None
    error: str | None = None


def run_vocab(
    mapper: Any,
    input_df: pd.DataFrame,
    config: DatasetConfig,
    vocab: str,
    out_dir: Path,
    *,
    dataset_sha: str,
    repo_root: Path,
    enforce_assigned: bool = True,
) -> VocabRun:
    """Run one vocab. Consumes the mapper as-is; writes manifest beside the outputs."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_tsv, stats = mapper.map_dataset_to_kg(
        dataset=input_df,
        entity_type=config.entity_type,
        name_column=config.name_column,
        provided_id_columns=[],
        vocab=vocab,
        annotation_mode="all",
        output_dir=out_dir,
        output_prefix=f"{config.key}_{vocab}",
    )
    if enforce_assigned and not assigned_stats_nonnull(stats):
        raise TrivialMappingError(
            f"vocab {vocab}: assigned KG mappings are zero — gold likely leaked as a "
            f"provided id (trivial-100% trap). Stats: mapped_to_kg_assigned="
            f"{stats.get('mapped_to_kg_assigned')}"
        )
    biolink_version = (
        getattr(getattr(mapper, "biolink_client", None), "biolink_version", None) or BIOLINK_VERSION_DEFAULT
    )
    manifest = build_manifest(
        vocab=vocab,
        config=config,
        dataset_sha=dataset_sha,
        biolink_version=biolink_version,
        output_tsv=str(output_tsv),
        repo_root=repo_root,
    )
    (out_dir / f"{config.key}_{vocab}_manifest.json").write_text(json.dumps(manifest, indent=2))
    return VocabRun(vocab=vocab, ok=True, output_tsv=str(output_tsv), stats=stats, manifest=manifest)


def run_all(
    mapper: Any,
    input_df: pd.DataFrame,
    config: DatasetConfig,
    out_dir: Path,
    *,
    dataset_sha: str,
    repo_root: Path,
    vocabs: tuple[str, ...] | None = None,
    enforce_assigned: bool = True,
) -> dict[str, VocabRun]:
    """Run every target vocab. A Kestrel error on one vocab is recorded, not fatal:
    the remaining vocabs still run. ``TrivialMappingError`` is NOT swallowed — it is a
    correctness failure of the whole run, not a per-vocab hiccup.
    """
    vocabs = vocabs or config.target_vocabs
    results: dict[str, VocabRun] = {}
    for vocab in vocabs:
        try:
            results[vocab] = run_vocab(
                mapper,
                input_df,
                config,
                vocab,
                out_dir,
                dataset_sha=dataset_sha,
                repo_root=repo_root,
                enforce_assigned=enforce_assigned,
            )
        except TrivialMappingError:
            raise
        except Exception as exc:  # per-vocab isolation (e.g. Kestrel error)
            results[vocab] = VocabRun(vocab=vocab, ok=False, output_tsv=None, stats=None, manifest=None, error=str(exc))
    return results
