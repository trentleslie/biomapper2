"""Unit 4 - the naive one-shot model probe (a strict lower bound).

One fixed prompt, no tools, no web access for the model, thinking disabled, structured
output. The model is given ONLY the lipid shorthand and asked to build the structure it
denotes, emitting a SMILES (RDKit-checkable) plus — for failure analysis only — its own
reading of the head-group class and total carbon / double-bond counts.

DELIBERATE: the prompt does NOT tell the model that grading happens at sum-composition
resolution, nor that the exact sn-isomer does not matter. The shorthand is
self-specifying and a ``no-network`` terminal agent would see only the shorthand;
pre-hinting the resolution would (a) ease the task and (b) leak the grader design. (This
mirrors the #3 lesson that pre-hinting ambiguity changes measured difficulty. The
grader's resolution choice is a scoring-side decision, invisible to the model.)

NOTE ON DETERMINISM: ``temperature`` is REJECTED (HTTP 400) on claude-opus-4-8 /
sonnet-5 / fable-5. Determinism is instead approximated by pinning the model id + subset
seed + saving every raw response, and disabling extended thinking to keep it one-shot.

The anthropic SDK is imported lazily; it is NOT a project dependency.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

DEFAULT_MODEL = "claude-opus-4-8"

PROMPT_TEMPLATE = (
    "You are given a lipid named in LIPID MAPS shorthand notation. Determine the "
    "chemical structure it denotes and return it as a SMILES string.\n\n"
    "Answer from your own knowledge only — do not use any external tools, lookups, or "
    "network. Emit an isomeric SMILES if you are confident of the stereochemistry, "
    "otherwise a valid non-isomeric SMILES. Do not invent an InChIKey; only include one "
    "if you are certain of it. Also report your reading of the head-group class and the "
    "TOTAL acyl carbon count and TOTAL double-bond count across all chains, so your "
    "reasoning can be checked.\n\n"
    "Lipid shorthand: {name}"
)

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "smiles": {"type": "string"},
        "inchikey": {"type": "string"},
        "lipid_class": {"type": "string"},
        "total_carbons": {"type": "integer"},
        "total_double_bonds": {"type": "integer"},
    },
    "required": ["smiles"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class ProbeResult:
    name: str
    emitted: dict  # raw {smiles, inchikey?, lipid_class?, total_carbons?, total_double_bonds?}
    model: str
    raw_response: dict = field(default_factory=dict)
    error: str | None = None


def build_prompt(name: str) -> str:
    return PROMPT_TEMPLATE.format(name=name)


def probe_name(client, name: str, *, model: str = DEFAULT_MODEL, max_tokens: int = 2048) -> ProbeResult:
    """One structured-output call. ``client`` is an ``anthropic.Anthropic``.

    Disables extended thinking (genuine one-shot). Does NOT pass ``temperature``.
    Any API/parse failure is captured, not raised, so one bad name can't sink the run.
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
        payload = json.loads(text) if text else {}
        return ProbeResult(
            name=name,
            emitted=dict(payload),
            model=getattr(resp, "model", model),
            raw_response={"stop_reason": getattr(resp, "stop_reason", None), "text": text},
        )
    except Exception as exc:  # noqa: BLE001 - capture, don't sink the run
        return ProbeResult(name=name, emitted={}, model=model, error=f"{type(exc).__name__}: {exc}")


def make_client():
    """Lazy anthropic client. Credentials resolve from env / `ant auth login`."""
    import anthropic

    return anthropic.Anthropic()
