"""Tier-3 orchestrator: run both arms, compute Fig-4 data, and SAVE EVERYTHING.

Per the artifact-hygiene SOP, every run persists its full raw output by default to a
timestamped path -- ``out_dir=None`` writes to ``runs/<UTC-stamp>/`` and the path is
printed on completion. ``out_dir`` only *overrides* the location; it is never the sole
way to save. The manifest pins model ids + run date, verbatim prompt + hash, decoding
params, reference DB versions, and the dataset content SHA.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from studies.tier3_determinism import arms, dataset, fig4, prompt
from studies.tier3_determinism.arms import CallFn, ResolveFn
from studies.tier3_determinism.fig4 import Fig4Data
from studies.tier3_determinism.models import (
    ArmACall,
    ArmBCall,
    DecodingParams,
    ExperimentConfig,
    RunManifest,
)

DEFAULT_RUNS_ROOT = Path(__file__).parent / "runs"


@dataclass
class ExperimentResult:
    out_dir: Path
    manifest: RunManifest
    fig4: Fig4Data
    arm_a: list[ArmACall]
    arm_b: list[ArmBCall]


def _reference_versions() -> tuple[str | None, str | None, dict[str, str]]:
    """Best-effort read of BioMapper's pinned references for the manifest (Arm B is
    deterministic *conditional on* these -- record them honestly)."""
    kestrel_url: str | None = None
    biolink: str | None = None
    refs: dict[str, str] = {}
    try:
        from biomapper2 import config as bm_config

        kestrel_url = getattr(bm_config, "KESTREL_API_URL", None)
        biolink = getattr(bm_config, "BIOLINK_VERSION_DEFAULT", None)
        if biolink:
            refs["biolink_model"] = biolink
    except Exception:  # noqa: BLE001 -- config import is optional for Arm-A-only runs
        pass
    return kestrel_url, biolink, refs


def _write_jsonl(path: Path, rows: list) -> None:
    path.write_text("".join(r.model_dump_json() + "\n" for r in rows))


class _IncrementalWriter:
    """Thread-safe append-one-JSON-line-per-record sink.

    Artifact-hygiene SOP: raw results stream to disk as they are produced, so a crash
    (or the guard tripping, a killed process, an OOM) preserves the partial evidence
    already gathered instead of discarding an entire multi-hour run.
    """

    def __init__(self, path: Path) -> None:
        self._fh = path.open("w", buffering=1)  # line-buffered
        self._lock = threading.Lock()

    def __call__(self, record: Any) -> None:
        line = record.model_dump_json() + "\n"
        with self._lock:
            self._fh.write(line)
            self._fh.flush()

    def close(self) -> None:
        self._fh.close()


def run_experiment(
    config: ExperimentConfig,
    out_dir: Path | None = None,
    call_fn: CallFn | None = None,
    resolve_fn: ResolveFn | None = None,
    now: datetime | None = None,
    git_commit: str | None = None,
    runs_root: Path | None = None,
) -> ExperimentResult:
    now = now or datetime.now(timezone.utc)
    queries = dataset.load_query_set(config.dataset_path)
    if config.limit is not None:
        queries = queries[: config.limit]
    decodings = [
        DecodingParams(temperature=t, top_p=config.top_p, max_tokens=config.max_tokens, seed=config.seed)
        for t in config.temperatures
    ]

    # Resolve the save path. Save-by-default: timestamped dir under runs_root.
    if out_dir is None:
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        out_dir = (runs_root or DEFAULT_RUNS_ROOT) / stamp
    out_dir = Path(out_dir)
    # Never clobber a COMPLETED run: refuse only when a finished artifact (fig4_data.json)
    # is already present. A dir that holds just a stray log, or a partial/in-progress run,
    # is fine to (re)write -- the previous design tripped on its own redirected run.log and
    # discarded ~10h of work, so the guard now keys on completion, not emptiness.
    if (out_dir / "fig4_data.json").exists():
        raise FileExistsError(
            f"output dir already contains a completed run (fig4_data.json): {out_dir}. "
            "Refusing to overwrite prior evidence; pick a fresh --out or clear it."
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    # Write the manifest FIRST (reproducibility pins are known upfront), then stream raw
    # results to disk as they are produced -- a crash preserves partial evidence.
    kestrel_url, biolink, refs = _reference_versions()
    manifest = RunManifest(
        generated_utc=now.isoformat(),
        git_commit=git_commit,
        dataset_source=str(config.dataset_path),
        dataset_sha256=dataset.content_sha256(config.dataset_path),
        n_queries=len(queries),
        n_repeats=config.n_repeats,
        n_repeats_arm_b=config.arm_b_repeats if config.run_arm_b else None,
        temperatures=config.temperatures,
        top_p=config.top_p,
        max_tokens=config.max_tokens,
        seed_policy=config.seed_policy,
        models=config.models,
        prompt_sha256=prompt.prompt_fingerprint(),
        prompt_verbatim=prompt.verbatim_template(),
        kestrel_api_url=kestrel_url if config.run_arm_b else None,
        biolink_version=biolink if config.run_arm_b else None,
        reference_db_versions=refs if config.run_arm_b else {},
        endpoint_note="Arm A via provider APIs; Arm B via Kestrel KG." if config.run_arm_b else "Arm A only.",
    )
    (out_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2))

    write_a = _IncrementalWriter(out_dir / "arm_a_raw.jsonl")
    write_b = _IncrementalWriter(out_dir / "arm_b_raw.jsonl")
    try:
        # Arm A calls are independent -> run concurrently to keep a large N sweep from
        # taking ~10h sequentially. Each result streams to disk on completion.
        arm_a = arms.run_arm_a(
            queries, config.models, decodings, config.n_repeats,
            call_fn=call_fn, on_result=write_a, max_workers=config.arm_a_workers,
        )
        # Asymmetric N: Arm B is deterministic given pinned refs, so a few repeats suffice
        # to *demonstrate* byte-identical variance=0. Kept sequential (one Kestrel pipeline)
        # but streamed to disk per call.
        arm_b = (
            arms.run_arm_b(queries, config.arm_b_repeats, resolve_fn=resolve_fn, on_result=write_b)
            if config.run_arm_b
            else []
        )
    finally:
        write_a.close()
        write_b.close()

    figure = fig4.build_fig4(arm_a, arm_b)
    (out_dir / "fig4_data.json").write_text(figure.model_dump_json(indent=2))

    print(f"[tier3] saved {len(arm_a)} Arm-A + {len(arm_b)} Arm-B raw calls to: {out_dir}")
    return ExperimentResult(out_dir=out_dir, manifest=manifest, fig4=figure, arm_a=arm_a, arm_b=arm_b)
