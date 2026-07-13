"""The Arm-A (LLM-only) prompt and its answer parser.

This is deliberately a *well-engineered* baseline -- NAR reviewers reject strawman
baselines, and a weak prompt would inflate BioMapper's determinism win. So Arm A
gets: an expert role, the exact target namespace per query, a strict JSON schema,
few-shot exemplars (disjoint from the held-out eval set), and explicit permission
to answer ``"unknown"`` rather than guess.

The prompt template is versioned by content hash (``prompt_fingerprint``) and pinned
verbatim into every run's manifest.
"""

from __future__ import annotations

import hashlib
import json
import re

from studies.tier3_determinism.models import Query

PROMPT_VERSION = "arm_a_v1"

_NAMESPACE_GUIDE = {
    "CHEBI": "a ChEBI identifier of the form 'CHEBI:<number>'",
    "HGNC": "an HGNC gene identifier of the form 'HGNC:<number>'",
    "UniProtKB": "a UniProtKB accession of the form 'UniProtKB:<accession>'",
}

SYSTEM_PROMPT = (
    "You are an expert biocurator specializing in mapping biological entity names to "
    "standard ontology identifiers. Given an entity name and a target namespace, return "
    "the single best-matching identifier in that namespace.\n\n"
    "Rules:\n"
    '1. Respond with ONLY a JSON object of the form {"id": "<CURIE>"} and nothing else.\n'
    "2. The CURIE MUST be in the requested target namespace.\n"
    "3. Choose the canonical/primary entry when several plausible entries exist "
    "(e.g. the neutral parent compound rather than a salt or specific ionic form).\n"
    "4. If you are not confident the identifier is correct, respond with "
    '{"id": "unknown"}. Do not guess. An honest "unknown" is better than a wrong id.'
)

# Few-shot exemplars. Deliberately chosen to be DISJOINT from the held-out eval set
# so the baseline is fair and non-leaky; they demonstrate the schema and the
# canonical-choice + abstention behavior across all three entity types.
_FEW_SHOT: list[tuple[str, str, str]] = [
    ("water", "CHEBI", '{"id": "CHEBI:15377"}'),
    ("L-tyrosine", "CHEBI", '{"id": "CHEBI:17895"}'),
    ("EGFR", "HGNC", '{"id": "HGNC:3236"}'),
    ("Serum albumin (human)", "UniProtKB", '{"id": "UniProtKB:P02768"}'),
    ("zorblaxine", "CHEBI", '{"id": "unknown"}'),  # not a real entity -> abstain
]


def _user_content(name: str, namespace: str) -> str:
    guide = _NAMESPACE_GUIDE.get(namespace, f"an identifier in the {namespace} namespace")
    return f"Entity name: {name}\n" f"Target namespace: {namespace} ({guide})\n" "Respond with the JSON object only."


def build_messages(query: Query) -> list[dict[str, str]]:
    """Build the chat-message list for one query (system + few-shot + user)."""
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for name, namespace, answer in _FEW_SHOT:
        messages.append({"role": "user", "content": _user_content(name, namespace)})
        messages.append({"role": "assistant", "content": answer})
    messages.append({"role": "user", "content": _user_content(query.query_name, query.target_namespace)})
    return messages


def prompt_fingerprint() -> str:
    """Stable SHA-256 over the verbatim prompt template (version + system + few-shot).

    Pinned into the manifest so a prompt edit is detectable in the artifact record.
    """
    payload = json.dumps(
        {"version": PROMPT_VERSION, "system": SYSTEM_PROMPT, "few_shot": _FEW_SHOT},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def verbatim_template() -> str:
    """Human-readable dump of the exact prompt template, pinned into the manifest."""
    lines = [f"# PROMPT VERSION: {PROMPT_VERSION}", "", "## SYSTEM", SYSTEM_PROMPT, "", "## FEW-SHOT EXEMPLARS"]
    for name, namespace, answer in _FEW_SHOT:
        lines.append(f"- user: {_user_content(name, namespace)!r}")
        lines.append(f"  assistant: {answer}")
    lines += ["", "## USER TEMPLATE", _user_content("<ENTITY_NAME>", "<TARGET_NAMESPACE>")]
    return "\n".join(lines)


_JSON_ID_RE = re.compile(r'"id"\s*:\s*"([^"]*)"')


def parse_answer(raw_text: str) -> str | None:
    """Extract the normalized top-1 CURIE from a model reply.

    Returns ``None`` for an explicit ``"unknown"``, an empty id, or any reply we
    cannot parse an id out of. Handles bare JSON, code-fenced JSON, and JSON
    embedded in prose.
    """
    if not raw_text:
        return None
    match = _JSON_ID_RE.search(raw_text)
    if not match:
        return None
    value = match.group(1).strip()
    if not value or value.lower() == "unknown":
        return None
    return value
