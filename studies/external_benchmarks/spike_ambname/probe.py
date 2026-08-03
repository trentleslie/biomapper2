"""Unit 4 - the naive one-shot model probe (a strict lower bound).

One fixed prompt template, no tools, no web access for the model, structured
output. The model enumerates ALL legitimate referents of the ambiguous name; for
each it emits whatever machine-checkable structure it can (InChIKey preferred,
SMILES acceptable, name as a last resort) which ``resolve.py`` then turns into an
InChIKey via a NEUTRAL resolver.

NOTE ON DETERMINISM: the spec asks for temp=0. On claude-opus-4-8 (and every
4.7/4.8 / Sonnet-5 / Fable-5 model) the ``temperature`` parameter is REMOVED and
returns HTTP 400 - temp=0 is not settable there. This probe therefore pins the
model id/version + the subset seed + saves every raw response for reproducibility
instead of relying on temp=0, and disables extended thinking to keep it a genuine
one-shot. If strict temp=0 is required, pin ``model`` to an older id that still
accepts sampling params (e.g. claude-haiku-4-5 / claude-sonnet-4-5) - a Trent
decision recorded in the run card.

The anthropic SDK is imported lazily so this module (and the offline test suite)
imports without it installed; it is NOT yet a project dependency.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

DEFAULT_MODEL = "claude-opus-4-8"

PROMPT_TEMPLATE = (
    "You are given the ambiguous metabolite / small-molecule name below. It maps "
    "to two or more DISTINCT chemical structures. Enumerate EVERY legitimate "
    "distinct structural referent of the name.\n\n"
    "For each referent, give a machine-checkable structure identifier. Prefer a "
    "full InChIKey; if you are not confident of the exact InChIKey, give an "
    "isomeric SMILES; only if you can give neither, give the precise chemical "
    "name. Do not invent InChIKeys - a wrong-but-confident InChIKey is worse than "
    "a SMILES or a name. Do not use any external tools or lookups; answer from "
    "your own knowledge.\n\n"
    "Ambiguous name: {name}"
)

# JSON schema for structured output: a list of referents, each carrying at most
# one of inchikey / smiles / name (all optional; resolver picks the best lane).
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "referents": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "inchikey": {"type": "string"},
                    "smiles": {"type": "string"},
                    "name": {"type": "string"},
                },
                "required": ["label"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["referents"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class ProbeResult:
    name: str
    referents: list[dict]  # raw emitted [{label, inchikey?, smiles?, name?}]
    model: str
    raw_response: dict = field(default_factory=dict)
    error: str | None = None


def build_prompt(name: str) -> str:
    return PROMPT_TEMPLATE.format(name=name)


def probe_name(client, name: str, *, model: str = DEFAULT_MODEL, max_tokens: int = 4096) -> ProbeResult:
    """One structured-output call. ``client`` is an ``anthropic.Anthropic``.

    Disables extended thinking (genuine one-shot). Does NOT pass ``temperature``
    (rejected on opus-4-8). Any API/parse failure is captured, not raised, so one
    bad name can't sink the run.
    """
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            thinking={"type": "disabled"},
            output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
            messages=[{"role": "user", "content": build_prompt(name)}],
        )
        text = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), "")
        payload = json.loads(text) if text else {"referents": []}
        return ProbeResult(
            name=name,
            referents=list(payload.get("referents", [])),
            model=getattr(resp, "model", model),
            raw_response={"stop_reason": getattr(resp, "stop_reason", None), "text": text},
        )
    except Exception as exc:  # noqa: BLE001 - capture, don't sink the run
        return ProbeResult(name=name, referents=[], model=model, error=f"{type(exc).__name__}: {exc}")


def make_client():
    """Lazy anthropic client. Credentials resolve from env / `ant auth login`."""
    import anthropic

    return anthropic.Anthropic()
