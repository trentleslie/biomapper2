"""Certificate-gated RefMet-name bridge (D2 re-resolution) — pure, offline-tested harmonization step.

BioMapper links two cohort names when they share a KG CURIE. This adds a link when they share a RefMet
standardized name but NOT a CURIE, GATED by the KG-independent structure certificate: adopt only bridges
whose two independent structures CERTIFY (agree), reject the refuted (the other method's errors), hold
the refused (no structure — the frontier). Correct-by-construction: no un-certified link is ever added.

Reuses ``link_by_intersection`` (CURIE links) and ``certify_link`` (the block1+block2[:8] verdict), so the
gate is the same trusted certificate used everywhere else. Pure: consumes already-resolved maps; no network.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from collections.abc import Mapping

from .cross_cohort_overlap import Link, link_by_intersection
from .link_certificate import certify_link


@dataclass(frozen=True)
class BridgeResult:
    curie_links: tuple[Link, ...]  # BioMapper baseline (shared CURIE)
    bridge_certified: tuple[Link, ...]  # RefMet-name bridges the certificate confirmed (adopted)
    bridge_refuted: tuple[tuple[str, str], ...]  # RefMet-name matches the certificate refuted (rejected)
    bridge_refused: tuple[tuple[str, str], ...]  # RefMet-name matches with no independent structure (pending)

    @property
    def combined_links(self) -> tuple[Link, ...]:
        """CURIE links + certified bridges — the harmonizer output after gated re-resolution."""
        return self.curie_links + self.bridge_certified


def certified_bridge_links(
    a_curie: Mapping[str, frozenset[str]],
    b_curie: Mapping[str, frozenset[str]],
    a_refmet: Mapping[str, str],
    b_refmet: Mapping[str, str],
    a_block: Mapping[str, str | None],
    b_block: Mapping[str, str | None],
) -> BridgeResult:
    """Return CURIE links plus certificate-gated RefMet-name bridge links.

    A bridge candidate is a pair (a, b) sharing a non-empty RefMet name but NOT already CURIE-linked.
    Each candidate is adjudicated by ``certify_link`` on the two sides' INDEPENDENT structure blocks:
    certified -> adopted, refuted -> rejected, refused (a side lacks structure) -> held.
    """
    curie = link_by_intersection(a_curie, b_curie)
    already = {(lk.a_name, lk.b_name) for lk in curie.links}
    b_by_rm: dict[str, set[str]] = defaultdict(set)
    for bn, rm in b_refmet.items():
        if rm:
            b_by_rm[rm].add(bn)

    certified: list[Link] = []
    refuted: list[tuple[str, str]] = []
    refused: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for an, rm in a_refmet.items():
        if not rm:
            continue
        for bn in b_by_rm.get(rm, ()):
            pair = (an, bn)
            if pair in already or pair in seen:
                continue
            seen.add(pair)
            verdict = certify_link(a_block.get(an), b_block.get(bn)).verdict
            if verdict == "certified":
                certified.append(Link(a_name=an, b_name=bn, shared=frozenset({f"REFMET:{rm}"})))
            elif verdict == "refuted":
                refuted.append(pair)
            else:
                refused.append(pair)
    return BridgeResult(curie.links, tuple(certified), tuple(refuted), tuple(refused))
