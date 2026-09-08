"""Unit B3 (+ A4 guard) — PubChem-by-name, source-tagged independent oracle for the live gate.

Resolves every panel name to ``(block, source)``:

  * a small-molecule name PubChem resolves by name -> ``(first_block, "pubchem")`` — the KG-independent
    structure the certificate grades on;
  * a lipid SUM-COMPOSITION shorthand (``PC(34:1)``, ``TG(16:0_18:1_18:2)``) cannot be adjudicated by
    name, so it is honestly ``(None, "refused")`` — NEVER graded off a circular structure source. The
    gate is pre-registered as small-molecule-adjudicable; the A1 refused-rise tripwire guards the lipid
    path from a free pass. No HMDB-by-name, no LIPID MAPS.
  * any resolver miss (404 / timeout / ambiguity) is fail-soft ``(None, "refused")``.

The source tag powers A4's runtime disjointness guard (``enforce_disjoint``): a link whose ORACLE
source equals the CANDIDATE resolver source for that name is forced to ``refused``, so the certificate
can never grade a link with the treatment's own structure source (the circular Deliverable-1 failure).

Pure except ``block_for_name`` (the caller injects a live/fake resolver); tests pass a fake. No lipid
structure dump is provisioned here — that is deferred infra (lipids stay refused).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Protocol

# name→(block|None, source): source in {"pubchem", "refused"} for this oracle; the candidate side is
# tagged separately (e.g. "kg") so A4 can compare them.
SourcedBlock = tuple[str | None, str]

# A sum-composition / species-shorthand lipid carries a "carbons:double-bonds" token (e.g. 34:1). That
# token is the marker PubChem-by-name cannot resolve to one structure, so such names are refused.
_SUM_COMPOSITION = re.compile(r"(?<![.\d])\d{1,3}:\d{1,2}(?![.\d])")


class _NameResolver(Protocol):
    def block_for_name(self, name: str) -> str | None: ...


def is_sum_composition_lipid(name: str) -> bool:
    """True when the name is a lipid sum-composition/species shorthand (has a ``C:U`` token)."""
    return bool(_SUM_COMPOSITION.search(name or ""))


def independent_block(name: str, resolver: _NameResolver) -> SourcedBlock:
    """Resolve one name to ``(block, source)``: refused for lipids/misses, ``pubchem`` otherwise."""
    if is_sum_composition_lipid(name):
        return (None, "refused")
    block = resolver.block_for_name(name)
    if block:
        return (block, "pubchem")
    return (None, "refused")


def oracle_by_name(names: Iterable[str], resolver: _NameResolver) -> dict[str, SourcedBlock]:
    """Build the source-tagged oracle map over ``names`` (deduplicated, order-independent)."""
    return {name: independent_block(name, resolver) for name in dict.fromkeys(names)}


def to_block_map(sourced: Mapping[str, SourcedBlock]) -> dict[str, str | None]:
    """Strip source tags to a plain ``name -> block`` map for ``certify_links``."""
    return {name: block for name, (block, _src) in sourced.items()}


def enforce_disjoint(
    sourced: Mapping[str, SourcedBlock],
    candidate_source: Mapping[str, str],
) -> dict[str, str | None]:
    """A4 disjointness: drop to ``None`` (=> refused) any name whose oracle source == candidate source.

    ``candidate_source`` maps a name to the source that produced the LINK candidate structure (e.g.
    ``"kg"``). When the oracle would grade that name with the SAME source, the certificate is circular,
    so the block is withheld and the link is refused rather than certified off the candidate's own
    source. Disjoint sources pass the block through unchanged.
    """
    out: dict[str, str | None] = {}
    for name, (block, src) in sourced.items():
        if block is not None and candidate_source.get(name) == src:
            out[name] = None
        else:
            out[name] = block
    return out
