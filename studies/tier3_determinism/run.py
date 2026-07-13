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
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from studies.tier3_determinism import dataset, experiment
from studies.tier3_determinism.models import ExperimentConfig, ModelSpec

# API-key env var required per provider. A run over the full preset touches all of
# these; a missing key would otherwise surface only as N per-call errors mid-sweep
# (after real spend on the working arms), so we preflight and fail fast instead.
_PROVIDER_KEY_ENV: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}

# Model ids are pinned here and echoed into the manifest. Providers may silently swap
# the model behind a name -- that drift is itself part of the non-determinism story,
# which is why the manifest also records the run date.
# Pinned, dated model ids -- echoed into the manifest. NOTE: the OpenAI GPT-5 family
# are reasoning models that reject a custom `temperature`/`max_tokens` on Chat
# Completions (they require `max_completion_tokens`, temp fixed at 1), so they do not
# fit the temperature-sweep call path; `gpt` therefore pins gpt-4o, which supports the
# full decoding-param surface. Point `--models` at a GPT-5.x id once the call layer
# grows a reasoning-model branch.
# NOTE on temperature: Opus 4.8 rejects BOTH temperature and top_p (400) -- it has no
# caller-facing sampling controls, so `supports_temperature=False` and the temperature
# sweep is NOT expressible for it (every "temp" bucket is the same native request).
# Sonnet 4.6 accepts temperature alone (never with top_p); gpt-4o and qwen accept both.
# The call layer (call_model._call_anthropic) never sends top_p to Anthropic.
MODEL_REGISTRY: dict[str, ModelSpec] = {
    "gpt": ModelSpec(provider="openai", model_id="gpt-4o-2024-08-06", label="gpt-4o"),
    "opus": ModelSpec(provider="anthropic", model_id="claude-opus-4-8", label="opus-4.8", supports_temperature=False),
    "sonnet": ModelSpec(provider="anthropic", model_id="claude-sonnet-4-6", label="sonnet-4.6"),
    "qwen": ModelSpec(provider="openrouter", model_id="qwen/qwen3-8b", label="qwen3-8b"),
}


@dataclass(frozen=True)
class _Preset:
    models: list[str]
    temps: list[float]
    n_repeats: int
    limit: int | None
    n_repeats_arm_b: int | None = None  # None -> reuse n_repeats (symmetric); set for asymmetric-N


_PRESETS: dict[str, _Preset] = {
    "smoke": _Preset(models=["gpt"], temps=[0.0, 0.7], n_repeats=3, limit=2),
    "full": _Preset(models=["opus", "sonnet", "gpt", "qwen"], temps=[0.0, 0.7], n_repeats=25, limit=None),
    # Headline Fig-4: asymmetric N -- Arm A (LLM) N=25 captures the answer-distribution spread; Arm B
    # (BioMapper/Kestrel, ~2-3 min/call) N=5 is enough to *demonstrate* byte-identical variance=0 since
    # it is deterministic given pinned references. All 4 pinned models, full 25-query set.
    "headline-asym": _Preset(
        models=["opus", "sonnet", "gpt", "qwen"], temps=[0.0, 0.7], n_repeats=25, limit=None, n_repeats_arm_b=5
    ),
}


def build_config(
    preset: str = "smoke",
    dataset_path: Path | None = None,
    models: list[str] | None = None,
    temps: list[float] | None = None,
    n_repeats: int | None = None,
    n_repeats_arm_b: int | None = None,
    max_tokens: int | None = None,
    limit: int | None = None,
    use_preset_limit: bool = True,
    no_arm_b: bool = False,
    seed: int | None = 12345,
) -> ExperimentConfig:
    """Build an ExperimentConfig from a preset with optional overrides.

    ``use_preset_limit`` keeps the preset's query cap; pass ``use_preset_limit=False``
    (with ``limit``) to override it (``limit=None`` then means "run the whole set").
    ``n_repeats_arm_b`` overrides the preset's Arm-B repeat count (asymmetric-N); when both the
    override and the preset are unset it falls back to ``n_repeats`` (symmetric).
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
        n_repeats_arm_b=n_repeats_arm_b if n_repeats_arm_b is not None else base.n_repeats_arm_b,
        max_tokens=max_tokens if max_tokens is not None else 256,
        seed=seed,
        run_arm_b=not no_arm_b,
        limit=resolved_limit,
    )


def missing_provider_keys(config: ExperimentConfig) -> list[str]:
    """Env-var names for API keys required by the config's providers but not set.

    Deduplicated and ordered by first appearance across the model matrix.
    """
    missing: list[str] = []
    for spec in config.models:
        env = _PROVIDER_KEY_ENV.get(spec.provider)
        if env and env not in os.environ and env not in missing:
            missing.append(env)
    return missing


def preflight_keys(config: ExperimentConfig) -> None:
    """Fail fast before any API spend if a selected provider is missing its key."""
    missing = missing_provider_keys(config)
    if missing:
        raise RuntimeError(
            "Missing API key(s) for the selected models: "
            + ", ".join(missing)
            + ". Set them (or drop those --models) before running."
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
    parser.add_argument("--n-repeats", type=int, default=None, help="N independent repeats per query per model (Arm A)")
    parser.add_argument(
        "--n-repeats-arm-b",
        type=int,
        default=None,
        help="Arm-B (BioMapper) repeats; defaults to the preset's value, else --n-repeats (asymmetric-N)",
    )
    parser.add_argument("--max-tokens", type=int, default=None, help="per-call output cap (default 256; 64 is plenty for JSON answers)")
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
        n_repeats_arm_b=args.n_repeats_arm_b,
        max_tokens=args.max_tokens,
        limit=args.limit,
        use_preset_limit=args.limit is None,  # only override the cap when --limit is given
        no_arm_b=args.no_arm_b,
    )
    preflight_keys(cfg)  # fail fast before any API spend if a provider key is missing
    experiment.run_experiment(cfg, out_dir=args.out, git_commit=_git_commit())


if __name__ == "__main__":
    main()
