"""LLM interpreter: grounded candidate pathways + measurements -> structured answer.

The interpreter is FORCED to emit a structured answer (ranked KEGG pathway list +
disease label) so scoring is objective (spec §4). The model may only rank pathways
from the grounded candidate set — a pathway it names that is not a candidate is
dropped, keeping the answer traceable to the annotated data (provenance, spec §5).
The llm_fn is injected so this module is offline-testable; anthropic_llm_fn wires
the real claude-opus-4-8 call.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

INTERPRETER_MODEL = "claude-opus-4-8"

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "ranked_pathways": {"type": "array", "items": {"type": "string"}},
        "disease_label": {"type": "string"},
    },
    "required": ["ranked_pathways", "disease_label"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Interpretation:
    ranked_pathways: tuple[str, ...]
    disease_label: str


def build_prompt(grounded, measurements: pd.DataFrame, question: str, *, name_col: str, dir_col: str) -> str:
    lines = [
        "You are interpreting a serum metabolomics case-vs-control contrast.",
        f"Question: {question}",
        "",
        "Per-entity measurements (surface name -> direction of change in cases):",
    ]
    for _, row in measurements.iterrows():
        lines.append(f"  - {row[name_col]}: {row[dir_col]}")
    lines += [
        "",
        "Candidate KEGG pathways grounded in the resolved entities (rank the "
        "dysregulated ones; you may ONLY use ids from this list):",
        "  " + " ".join(grounded.candidate_pathways),
        "",
        'Return JSON: {"ranked_pathways": [map ids most-to-least dysregulated], '
        '"disease_label": short condition name}.',
    ]
    return "\n".join(lines)


def interpret(
    grounded,
    measurements: pd.DataFrame,
    question: str,
    llm_fn: Callable[[str], dict],
    *,
    name_col: str,
    dir_col: str,
) -> Interpretation:
    prompt = build_prompt(grounded, measurements, question, name_col=name_col, dir_col=dir_col)
    raw = llm_fn(prompt)
    allowed = set(grounded.candidate_pathways)
    ranked = tuple(p for p in raw.get("ranked_pathways", []) if p in allowed)
    return Interpretation(ranked_pathways=ranked, disease_label=str(raw.get("disease_label", "")).strip())


def anthropic_llm_fn(prompt: str) -> dict:
    """Live interpreter: claude-opus-4-8, adaptive thinking, structured output."""
    import anthropic

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=INTERPRETER_MODEL,
        max_tokens=2048,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )
    import json

    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)
