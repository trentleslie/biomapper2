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
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from biomapper2.config import BIOLINK_VERSION_DEFAULT, KESTREL_API_URL

from .config import ProvidedIdDatasetConfig, RunnableConfig
from .scorers.provided_id_scorer import assert_target_held_out


class TrivialMappingError(RuntimeError):
    """Raised when assigned mappings are zero — signals the gold-as-provided trap."""


class NoProvidedMappingError(RuntimeError):
    """Raised in provided-ID mode when the provided source produced zero KG mappings.

    Provided-ID mode expects ``mapped_to_kg_provided > 0`` (the assign path is off entirely, so the
    name-input ``assigned``-based guard does not apply). Zero provided mappings means the source id
    never linked — a broken run, not a scorable zero.
    """


def assigned_stats_nonnull(stats: dict[str, Any]) -> bool:
    """True iff the run produced at least one *assigned* KG mapping.

    Name-only input with ``annotation_mode='all'`` must resolve via the assign path; zero
    assigned mappings means the gold column leaked into the provided-id path.
    """
    return int(stats.get("mapped_to_kg_assigned", 0) or 0) > 0


def mapped_provided_nonnull(stats: dict[str, Any]) -> bool:
    """True iff a provided-ID run produced at least one KG mapping via the *provided* path.

    The name-input analog (``assigned_stats_nonnull``) is inverted here: provided-ID mode runs with
    ``annotation_mode='none'``, so ``mapped_to_kg_assigned`` is expected to be 0 and the provided
    path is the only one that can produce a mapping.
    """
    return int(stats.get("mapped_to_kg_provided", 0) or 0) > 0


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


UNRECORDED = "unrecorded"


def kg_provenance(*, probe_health: bool = False) -> dict[str, Any]:
    """KG-snapshot / ChEBI-release provenance for a run's manifest.

    The Kestrel KG serves the graph BioMapper resolves against, but it exposes no version /
    ``meta_knowledge_graph`` endpoint (verified live 2026-07-22: ``/version``, ``/meta``,
    ``/meta_knowledge_graph`` all 404; only ``/health`` responds). So the KG snapshot and the
    ChEBI release cannot be queried — they are OPERATOR-SUPPLIED out of band via the ``KG_SNAPSHOT``
    and ``CHEBI_RELEASE`` env vars. A run that omits them records the loud ``"unrecorded"`` sentinel
    (never a silent green) so an un-pinned run is visible on its face.

    ``probe_health`` adds a live ``/health`` GET as a weak temporal anchor (server status + timestamp)
    — off by default so manifest construction stays pure/offline for unit tests; live run paths turn
    it on once per run.
    """
    prov: dict[str, Any] = {
        "kg_snapshot": os.getenv("KG_SNAPSHOT") or UNRECORDED,
        "chebi_release": os.getenv("CHEBI_RELEASE") or UNRECORDED,
    }
    if probe_health:
        health: dict[str, Any]
        try:
            import requests

            r = requests.get(f"{KESTREL_API_URL.rstrip('/')}/health", timeout=8)
            health = {"ok": r.ok, "status_code": r.status_code, "response": r.json() if r.ok else r.text[:200]}
        except Exception as exc:  # liveness probe is best-effort; never fail the run over it
            health = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        prov["kg_health_probe"] = health
    return prov


def build_manifest(
    *,
    vocab: str,
    config: RunnableConfig,
    dataset_sha: str,
    biolink_version: str,
    output_tsv: str,
    repo_root: Path,
    kg_prov: dict[str, Any] | None = None,
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
        **(kg_prov if kg_prov is not None else kg_provenance()),
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
    config: RunnableConfig,
    vocab: str,
    out_dir: Path,
    *,
    dataset_sha: str,
    repo_root: Path,
    enforce_assigned: bool = True,
    kg_prov: dict[str, Any] | None = None,
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
        kg_prov=kg_prov,
    )
    (out_dir / f"{config.key}_{vocab}_manifest.json").write_text(json.dumps(manifest, indent=2))
    return VocabRun(vocab=vocab, ok=True, output_tsv=str(output_tsv), stats=stats, manifest=manifest)


def run_all(
    mapper: Any,
    input_df: pd.DataFrame,
    config: RunnableConfig,
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
    kg_prov = kg_provenance(probe_health=True)  # probe KG liveness once per run, share across vocabs
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
                kg_prov=kg_prov,
            )
        except TrivialMappingError:
            raise
        except Exception as exc:  # per-vocab isolation (e.g. Kestrel error)
            results[vocab] = VocabRun(vocab=vocab, ok=False, output_tsv=None, stats=None, manifest=None, error=str(exc))
    return results


# --------------------------------------------------------------------------------------------------
# Provided-ID (identifier-input) run mode. The source id is handed to the mapper as a PROVIDED id
# with ``annotation_mode='none'`` (pure equivalence expansion); the target is held out for the
# scorer. Distinct from the name-input path in three ways: provided_id_columns=[source] (not []),
# annotation_mode='none' (not 'all'), and the anti-trivial guard is mapped_to_kg_provided>0 (not
# assigned>0). A single run per dataset — the equivalence expansion is not vocab-steered.
# --------------------------------------------------------------------------------------------------


def build_manifest_provided(
    *,
    config: ProvidedIdDatasetConfig,
    dataset_sha: str,
    biolink_version: str,
    output_tsv: str,
    repo_root: Path,
    kg_prov: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "dataset": config.key,
        "entity_type": config.entity_type,
        "input_type": config.input_type,
        "mode": "provided_id",
        "annotation_mode": config.annotation_mode,
        # The load-bearing anti-trivial record: source PROVIDED, target HELD OUT (never provided).
        "provided_id_columns": [config.source_id_column],
        "source_namespace": config.source_namespace,
        "held_out_target_columns": {ns: col for ns, col in config.gold_target_columns},
        "biomapper2_commit": _git_commit(repo_root),
        "kestrel_api_url": KESTREL_API_URL,
        "biolink_version": biolink_version,
        **(kg_prov if kg_prov is not None else kg_provenance()),
        "dataset_source_sha256": dataset_sha,
        "output_tsv": output_tsv,
        "timestamp_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }


@dataclass
class ProvidedRun:
    ok: bool
    output_tsv: str | None
    stats: dict[str, Any] | None
    manifest: dict[str, Any] | None
    error: str | None = None


def run_provided_id(
    mapper: Any,
    input_df: pd.DataFrame,
    config: ProvidedIdDatasetConfig,
    out_dir: Path,
    *,
    dataset_sha: str,
    repo_root: Path,
    enforce_mapped: bool = True,
) -> ProvidedRun:
    """Run one provided-ID dataset. Source id in ``provided_id_columns``; target held out.

    ``assert_target_held_out`` runs FIRST (fail-loud anti-trivial-100% guard): a config whose scored
    target is a provided column — or shares the source namespace — raises before the mapper is even
    called, so a trivial 100% can never be produced. Then the provided-path mapping guard
    (``mapped_to_kg_provided > 0``) confirms the source actually linked.
    """
    assert_target_held_out(config)  # anti-trivial-100% invariant: target must be held out
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_tsv, stats = mapper.map_dataset_to_kg(
        dataset=input_df,
        entity_type=config.entity_type,
        name_column=config.name_column,
        provided_id_columns=[config.source_id_column],
        vocab=None,  # equivalence expansion is not vocab-steered; no target restriction
        annotation_mode=config.annotation_mode,  # 'none' — pure provided-ID equivalence expansion
        output_dir=out_dir,
        output_prefix=f"{config.key}_provided",
    )
    if enforce_mapped and not getattr(config, "known_source_gap", False) and not mapped_provided_nonnull(stats):
        raise NoProvidedMappingError(
            f"{config.key}: provided-ID run produced zero KG mappings via the provided path "
            f"(mapped_to_kg_provided={stats.get('mapped_to_kg_provided')}). The source id never "
            f"linked — refusing to score a broken run."
        )
    biolink_version = (
        getattr(getattr(mapper, "biolink_client", None), "biolink_version", None) or BIOLINK_VERSION_DEFAULT
    )
    manifest = build_manifest_provided(
        config=config,
        dataset_sha=dataset_sha,
        biolink_version=biolink_version,
        output_tsv=str(output_tsv),
        repo_root=repo_root,
        kg_prov=kg_provenance(probe_health=True),
    )
    (out_dir / f"{config.key}_provided_manifest.json").write_text(json.dumps(manifest, indent=2))
    return ProvidedRun(ok=True, output_tsv=str(output_tsv), stats=stats, manifest=manifest)
