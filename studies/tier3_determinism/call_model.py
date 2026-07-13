"""Unified model-call layer for Arm A.

One ``call_model()`` entry point routes to three providers behind their native
transports:
  * ``openai``     -> OpenAI Chat Completions
  * ``openrouter`` -> OpenAI SDK pointed at OpenRouter (open-weights models, fp8)
  * ``anthropic``  -> Anthropic Messages

Clients are constructed lazily (SDKs imported only when needed) and are injectable
for testing. Transport failures are captured on the result, never raised, so a
long sweep is not aborted by one 429.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from studies.tier3_determinism.models import DecodingParams, ModelSpec

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


@dataclass
class ModelResponse:
    text: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_s: float
    error: str | None = None


def _make_client(spec: ModelSpec) -> Any:
    """Construct the provider SDK client. Imported lazily; needs the relevant key."""
    if spec.provider in ("openai", "openrouter"):
        from openai import OpenAI

        if spec.provider == "openrouter":
            return OpenAI(base_url=OPENROUTER_BASE_URL, api_key=os.environ["OPENROUTER_API_KEY"])
        return OpenAI()
    if spec.provider == "anthropic":
        from anthropic import Anthropic

        return Anthropic()
    raise ValueError(f"Unknown provider: {spec.provider!r}")


def _call_openai_style(
    client: Any, spec: ModelSpec, messages: list[dict[str, str]], d: DecodingParams
) -> ModelResponse:
    kwargs: dict[str, Any] = {
        "model": spec.model_id,
        "messages": messages,
        "temperature": d.temperature,
        "top_p": d.top_p,
        "max_tokens": d.max_tokens,
    }
    if d.seed is not None:
        kwargs["seed"] = d.seed
    start = time.perf_counter()
    resp = client.chat.completions.create(**kwargs)
    latency = time.perf_counter() - start
    usage = getattr(resp, "usage", None)
    return ModelResponse(
        text=resp.choices[0].message.content or "",
        prompt_tokens=getattr(usage, "prompt_tokens", None),
        completion_tokens=getattr(usage, "completion_tokens", None),
        latency_s=latency,
    )


def _call_anthropic(client: Any, spec: ModelSpec, messages: list[dict[str, str]], d: DecodingParams) -> ModelResponse:
    system = " ".join(m["content"] for m in messages if m["role"] == "system")
    chat = [m for m in messages if m["role"] != "system"]
    # Anthropic has no `seed` param -- part of the story: greedy != reproducible.
    start = time.perf_counter()
    resp = client.messages.create(
        model=spec.model_id,
        system=system,
        messages=chat,
        temperature=d.temperature,
        top_p=d.top_p,
        max_tokens=d.max_tokens,
    )
    latency = time.perf_counter() - start
    usage = getattr(resp, "usage", None)
    text = resp.content[0].text if resp.content else ""
    return ModelResponse(
        text=text or "",
        prompt_tokens=getattr(usage, "input_tokens", None),
        completion_tokens=getattr(usage, "output_tokens", None),
        latency_s=latency,
    )


def call_model(
    spec: ModelSpec,
    messages: list[dict[str, str]],
    decoding: DecodingParams,
    client: Any | None = None,
) -> ModelResponse:
    """Call one model once. Never raises on transport error -- returns it on ``.error``."""
    if spec.provider not in ("openai", "openrouter", "anthropic"):
        raise ValueError(f"Unknown provider: {spec.provider!r}")
    start = time.perf_counter()
    try:
        if client is None:
            client = _make_client(spec)
        if spec.provider == "anthropic":
            return _call_anthropic(client, spec, messages, decoding)
        return _call_openai_style(client, spec, messages, decoding)
    except Exception as exc:  # noqa: BLE001 -- capture any transport/SDK failure
        return ModelResponse(
            text="",
            prompt_tokens=None,
            completion_tokens=None,
            latency_s=time.perf_counter() - start,
            error=f"{type(exc).__name__}: {exc}",
        )
