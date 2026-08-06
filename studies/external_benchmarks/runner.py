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


class EmptyDatasetError(RuntimeError):
    """Raised when an adapter hands the runner a dataset with zero rows.

    A source that yields nothing is a broken run, not a scorable zero. Without this guard the empty
    frame travels into the mapper and surfaces much later as a confusing pandas join error
    (``columns overlap but no suffix specified``) that names schema columns and points at the wrong
    problem entirely — which is exactly what happened to SwissLipids on 2026-08-05, when its pinned
    ``source_url`` began returning HTTP 200 with a zero-byte body.
    """


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


_METAGRAPH_CACHE: dict[str, Any] | None = None


def _fetch_metagraph(*, refresh: bool = False) -> dict[str, Any]:
    """GET ``/metagraph`` — the graph's own account of which build is being served.

    Best-effort by design: a provenance probe must never abort a benchmark run, so a failure is
    RECORDED as an error rather than raised, and the caller falls back to the sentinel.

    Memoized for the life of the process. A suite calls this once per dataset, and the served build
    does not change from one dataset to the next in the normal case, so without caching an
    unreachable KG would cost the timeout on every dataset and add minutes before the suite could
    finalize its artifacts. Failures are cached too: within one run an unreachable KG is unlikely to
    heal, and retrying it per dataset is exactly the cost being avoided.

    ``refresh`` forces a live re-read, for the end-of-suite check that the build did not move
    underneath the run.
    """
    global _METAGRAPH_CACHE
    if _METAGRAPH_CACHE is not None and not refresh:
        return _METAGRAPH_CACHE
    result = _fetch_metagraph_uncached()
    _METAGRAPH_CACHE = result
    return result


def _fetch_metagraph_uncached() -> dict[str, Any]:
    try:
        import requests

        r = requests.get(f"{KESTREL_API_URL.rstrip('/')}/metagraph", timeout=20)
        if not r.ok:
            return {"error": f"HTTP {r.status_code}"}
        mg = r.json()
        # Keep the identity + the fingerprint, drop the multi-thousand-entry category/triple lists so
        # the manifest stays readable. node_prefixes is kept only for the CHEBI count below.
        return {
            "graph": mg.get("graph"),
            "version": mg.get("version"),
            "summary": mg.get("summary"),
            "n_knowledge_sources": len(mg.get("knowledge_sources") or {}),
            "chebi_node_count": (mg.get("node_prefixes") or {}).get("CHEBI"),
        }
    except Exception as exc:  # never fail a run over provenance
        return {"error": f"{type(exc).__name__}: {exc}"}


def kg_provenance(*, probe_live: bool = False) -> dict[str, Any]:
    """KG-snapshot / ChEBI-release provenance for a run's manifest.

    The snapshot is read FROM THE GRAPH: ``GET /metagraph`` self-reports ``graph`` and ``version``
    plus a summary block (node/edge/category/prefix/predicate counts) that acts as a content
    fingerprint. That fingerprint is the valuable part, because it separates two builds that both
    call themselves 2.0.1 — something a hand-typed label cannot do.

    This replaces the previous env-var-only scheme. That scheme was not merely weaker, it was inert
    for the case that matters: the scheduled workflow wired ``KG_SNAPSHOT``/``CHEBI_RELEASE`` from
    ``github.event.inputs.*``, which exist ONLY on ``workflow_dispatch``. On the ``schedule:``
    trigger they evaluate to empty, so every unattended run recorded ``"unrecorded"`` and no
    operator discipline could have fixed it. Reading the graph closes that on both triggers.

    The env vars survive as an OPERATOR OVERRIDE (an out-of-band assertion still beats a guess when
    someone genuinely knows better), and the fetched metagraph is recorded alongside either way, so
    an override never hides what was actually served.

    ``chebi_release`` stays env-only: ``/metagraph`` carries no ChEBI version. The CHEBI node count
    is recorded as its stand-in, which answers the canary question ("did the graph move?") even
    though it is not a release string.

    ``probe_live`` gates the network (``/metagraph`` + a ``/health`` temporal anchor). Off by
    default so manifest construction stays pure/offline for unit tests; live run paths turn it on
    once per run.

    Earlier code asserted this endpoint did not exist, on a 2026-07-22 probe of ``/version``,
    ``/meta`` and ``/meta_knowledge_graph``. Those do 404. The endpoint is ``/metagraph``, which
    that probe never tried; the TRAPI-style names were the wrong guess.
    """
    prov: dict[str, Any] = {
        "kg_snapshot": os.getenv("KG_SNAPSHOT") or UNRECORDED,
        "chebi_release": os.getenv("CHEBI_RELEASE") or UNRECORDED,
    }
    if probe_live:
        mg = _fetch_metagraph()
        prov["kg_metagraph"] = mg
        if mg.get("chebi_node_count") is not None:
            prov["chebi_node_count"] = mg["chebi_node_count"]
        # Derive the snapshot only when the operator did not pin one by hand.
        if prov["kg_snapshot"] == UNRECORDED and mg.get("version"):
            summary = mg.get("summary") or {}
            nodes, edges = summary.get("total_nodes"), summary.get("total_edges")
            fingerprint = f" ({nodes}n/{edges}e)" if nodes and edges else ""
            prov["kg_snapshot"] = f"{mg.get('graph') or 'kg'} {mg['version']}{fingerprint}"

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
    # Also guarded here, not only in run_all, because orchestrate_metabench calls run_vocab directly.
    # Cheap and idempotent when reached via run_all, which has already checked.
    _assert_dataset_nonempty(input_df, config)
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


def _assert_dataset_nonempty(input_df: pd.DataFrame, config: RunnableConfig) -> None:
    """Fail fast, and name the likely culprit, when an adapter produced no rows.

    Checked before the KG probe and before any mapper call so the error costs nothing and arrives
    while the cause is still obvious. The message names the dataset, the row count, and the pinned
    source, because an empty dataset almost always means the source stopped serving data rather than
    that the harness broke.
    """
    if len(input_df) > 0:
        return
    source = getattr(config, "source_url", "") or ""
    where = f" Pinned source: {source}" if source else ""
    raise EmptyDatasetError(
        f"{config.key}: the adapter produced 0 rows, so there is nothing to map. "
        f"This is a broken run, not a score of zero.{where} "
        f"Check that the source still serves data — an HTTP 200 with an empty body reads as success "
        f"to a streaming adapter and yields exactly this."
    )


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
    _assert_dataset_nonempty(input_df, config)
    kg_prov = kg_provenance(probe_live=True)  # read the KG build once per run, share across vocabs
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
        except (TrivialMappingError, EmptyDatasetError):
            # Neither is a per-vocab hiccup: both condemn the whole run. Letting the generic handler
            # below catch them would file the failure as one vocab's error and let the others
            # proceed, turning a loud stop into a quiet partial result.
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
        kg_prov=kg_provenance(probe_live=True),
    )
    (out_dir / f"{config.key}_provided_manifest.json").write_text(json.dumps(manifest, indent=2))
    return ProvidedRun(ok=True, output_tsv=str(output_tsv), stats=stats, manifest=manifest)
