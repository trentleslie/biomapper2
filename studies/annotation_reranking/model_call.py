"""Unified model-call layer + full-matrix roster for the annotation-reranking harness.

Design notes
------------
* Direct single-shot API calls — no ce: subagents are spawned here, so the
  subagent-billing-leak documented in the old ablation harness does NOT apply.
  Cost is read from each SDK response's usage where available; for OpenRouter,
  we prefer the response's reported cost, else fall back to 0.0.

* OPENROUTER_API_KEY is read lazily from ~/.config/model-ablation/env (format:
  export OPENROUTER_API_KEY=...) if not already in the environment.  The read
  happens inside _load_openrouter_key() which is only called at call time, so
  importing this module does NOT touch the key file or open any network connections.

* Frontier model ids are pinned at run time.  ``PIN_AT_RUNTIME`` is a sentinel
  that must be replaced before billed runs.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ModelCfg:
    label: str
    provider: str       # "anthropic" | "openai" | "openrouter"
    model_id: str
    quant_note: str = field(default="")


# ---------------------------------------------------------------------------
# Roster — full matrix
# ---------------------------------------------------------------------------

ROSTER: list[ModelCfg] = [
    ModelCfg("opus",     "anthropic",  "claude-opus-4-8"),
    ModelCfg("sonnet",   "anthropic",  "claude-sonnet-4-6"),
    # GPT-5.5-class slot; pin the exact id before a billed run
    ModelCfg("gpt-5.5",  "openai",     "PIN_AT_RUNTIME"),
    ModelCfg("qwen3-4b", "openrouter", "qwen/qwen3-4b",
             "OpenRouter fp8, NOT local Q4"),
    ModelCfg("qwen3-8b", "openrouter", "qwen/qwen3-8b",
             "OpenRouter fp8, NOT local Q4"),
]


# ---------------------------------------------------------------------------
# Key loading (lazy — never runs at import time)
# ---------------------------------------------------------------------------

def _load_openrouter_key() -> str:
    """Return the OpenRouter API key from env or ~/.config/model-ablation/env.

    Key is read inline; it is never echoed or logged.
    """
    val = os.getenv("OPENROUTER_API_KEY")
    if val:
        return val
    path = os.path.expanduser("~/.config/model-ablation/env")
    with open(path) as fh:
        for line in fh:
            if "OPENROUTER_API_KEY" in line:
                # handles: export OPENROUTER_API_KEY=sk-or-...
                return line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("OPENROUTER_API_KEY not found in environment or ~/.config/model-ablation/env")


# ---------------------------------------------------------------------------
# Per-provider dispatch functions (each returns {"text": str, "cost": float})
# ---------------------------------------------------------------------------

def _call_openrouter(model_id: str, prompt: str, seed: int) -> dict:
    from openai import OpenAI  # lazy import — no network at module load
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=_load_openrouter_key(),
    )
    resp = client.chat.completions.create(
        model=model_id,
        temperature=0,
        seed=seed,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.choices[0].message.content or ""
    # OpenRouter may report cost in resp.usage; fall back to 0.0
    cost: float = 0.0
    usage = getattr(resp, "usage", None)
    if usage is not None:
        cost = float(getattr(usage, "cost", None) or 0.0)
    return {"text": text, "cost": cost}


def _call_anthropic(model_id: str, prompt: str, seed: int) -> dict:
    from anthropic import Anthropic  # lazy import
    client = Anthropic()
    resp = client.messages.create(
        model=model_id,
        max_tokens=256,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text if resp.content else ""
    # Cost can be computed from usage × per-model price in the manifest;
    # return 0.0 here and let the harness apply pricing post-hoc.
    return {"text": text, "cost": 0.0}


def _call_openai(model_id: str, prompt: str, seed: int) -> dict:
    from openai import OpenAI  # lazy import
    client = OpenAI()
    resp = client.chat.completions.create(
        model=model_id,
        temperature=0,
        seed=seed,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.choices[0].message.content or ""
    return {"text": text, "cost": 0.0}


# ---------------------------------------------------------------------------
# Routing table  (maps provider name → function NAME in this module)
# ---------------------------------------------------------------------------
# We store the name rather than the function reference so that patch.object()
# on _call_* attributes is honoured at call time (used in unit tests).

_DISPATCH: dict[str, str] = {
    "openrouter": "_call_openrouter",
    "anthropic":  "_call_anthropic",
    "openai":     "_call_openai",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def call_model(cfg: ModelCfg, prompt: str, seed: int = 0) -> tuple[str, float, float]:
    """Call a model and return (text, cost_usd, latency_s).

    temperature is always 0 for reproducibility.
    Latency is wall-clock time around the SDK call.
    The dispatch looks up the function by name at call time so that
    unittest.mock.patch.object() on _call_* attributes works correctly in tests.
    """
    import sys
    _mod = sys.modules[__name__]
    fn = getattr(_mod, _DISPATCH[cfg.provider])
    t0 = time.monotonic()
    out: dict = fn(cfg.model_id, prompt, seed)
    latency = time.monotonic() - t0
    return out["text"], float(out.get("cost", 0.0)), latency
