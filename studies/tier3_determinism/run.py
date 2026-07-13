"""Tier-3 determinism experiment CLI.

    uv run python -m studies.tier3_determinism.run --preset smoke
    uv run python -m studies.tier3_determinism.run --preset full --out runs/headline

Presets:
  * ``smoke`` (default) -- one model, a couple of queries, N=3. Cheap; proves the wiring.
  * ``full``  -- the N=20-30 temperature sweep across the model matrix (real API spend).

All raw runs are saved by default to ``runs/<UTC-stamp>/`` (``--out`` only overrides).
"""

from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path

from studies.tier3_determinism import dataset, experiment
from studies.tier3_determinism.models import ExperimentConfig, ModelSpec

# Model ids are pinned here and echoed into the manifest. Providers may silently swap
# the model behind a name -- that drift is itself part of the non-determinism story,
# which is why the manifest also records the run date.
# Pinned, dated model ids -- echoed into the manifest. NOTE: the OpenAI GPT-5 family
# are reasoning models that reject a custom `temperature`/`max_tokens` on Chat
# Completions (they require `max_completion_tokens`, temp fixed at 1), so they do not
# fit the temperature-sweep call path; `gpt` therefore pins gpt-4o, which supports the
# full decoding-param surface. Point `--models` at a GPT-5.x id once the call layer
# grows a reasoning-model branch.
MODEL_REGISTRY: dict[str, ModelSpec] = {
    "gpt": ModelSpec(provider="openai", model_id="gpt-4o-2024-08-06", label="gpt-4o"),
    "opus": ModelSpec(provider="anthropic", model_id="claude-opus-4-8", label="opus-4.8"),
    "sonnet": ModelSpec(provider="anthropic", model_id="claude-sonnet-4-6", label="sonnet-4.6"),
    "qwen": ModelSpec(provider="openrouter", model_id="qwen/qwen3-8b", label="qwen3-8b"),
}


@dataclass(frozen=True)
class _Preset:
    models: list[str]
    temps: list[float]
    n_repeats: int
    limit: int | None


_PRESETS: dict[str, _Preset] = {
    "smoke": _Preset(models=["gpt"], temps=[0.0, 0.7], n_repeats=3, limit=2),
    "full": _Preset(models=["opus", "sonnet", "gpt", "qwen"], temps=[0.0, 0.7], n_repeats=25, limit=None),
}


def build_config(
    preset: str = "smoke",
    dataset_path: Path | None = None,
    models: list[str] | None = None,
    temps: list[float] | None = None,
    n_repeats: int | None = None,
    limit: int | None = None,
    use_preset_limit: bool = True,
    no_arm_b: bool = False,
    seed: int | None = 12345,
) -> ExperimentConfig:
    """Build an ExperimentConfig from a preset with optional overrides.

    ``use_preset_limit`` keeps the preset's query cap; pass ``use_preset_limit=False``
    (with ``limit``) to override it (``limit=None`` then means "run the whole set").
    """
    base = _PRESETS[preset]
    labels = models if models is not None else base.models
    specs = [MODEL_REGISTRY[label] for label in labels]  # KeyError on unknown label
    resolved_limit = base.limit if use_preset_limit else limit
    return ExperimentConfig(
        dataset_path=dataset_path or dataset.HELD_OUT_QUERY_SET,
        models=specs,
        temperatures=temps if temps is not None else list(base.temps),
        n_repeats=n_repeats if n_repeats is not None else base.n_repeats,
        seed=seed,
        run_arm_b=not no_arm_b,
        limit=resolved_limit,
    )


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        return None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Tier-3 determinism-vs-LLM experiment (WS-E).")
    parser.add_argument("--preset", choices=list(_PRESETS), default="smoke")
    parser.add_argument("--dataset", type=Path, default=None, help="query-set JSONL (default: held-out v1)")
    parser.add_argument("--models", nargs="+", default=None, help=f"registry labels: {list(MODEL_REGISTRY)}")
    parser.add_argument("--temps", nargs="+", type=float, default=None, help="temperature sweep points")
    parser.add_argument("--n-repeats", type=int, default=None, help="N independent repeats per query per model")
    parser.add_argument("--limit", type=int, default=None, help="cap query set size (smoke)")
    parser.add_argument("--no-arm-b", action="store_true", help="skip BioMapper arm (Arm A only)")
    parser.add_argument("--out", type=Path, default=None, help="override output dir (default: runs/<UTC-stamp>)")
    args = parser.parse_args(argv)

    cfg = build_config(
        preset=args.preset,
        dataset_path=args.dataset,
        models=args.models,
        temps=args.temps,
        n_repeats=args.n_repeats,
        limit=args.limit,
        use_preset_limit=args.limit is None,  # only override the cap when --limit is given
        no_arm_b=args.no_arm_b,
    )
    experiment.run_experiment(cfg, out_dir=args.out, git_commit=_git_commit())


if __name__ == "__main__":
    main()
