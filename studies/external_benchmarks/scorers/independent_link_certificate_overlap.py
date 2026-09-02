"""Unit C — KG-INDEPENDENT certificate over a set of cross-cohort links (the TRUST metric).

Unlike the stability descriptor (Unit B, which reads the KG node's own InChIKey and is therefore
circular / non-authoritative), this module NEVER touches the KG node. Each side's structure is an
INDEPENDENT InChIKey resolved from the cohort's own vendor id via PubChem/HMDB
(``independent_inchikey.py``) — the caller's gated LIVE step. This module is pure: it consumes the
already-resolved independent InChIKeys keyed by name and applies ``certify_link`` to each link, so it
is fully offline-testable (tests pass keys directly; no network).

Verdicts (from ``certify_link``): ``certified`` (independent structures agree), ``refuted`` (they
disagree at connectivity or stereo — a wrong-molecule / stereoisomer link), ``refused`` (a side has no
independent structure — counts-only, excluded from the certified rate, never certified off the KG).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .cross_cohort_overlap import Link
from .independent_inchikey import ProvidedBlock
from .link_certificate import certify_link


@dataclass(frozen=True)
class CertifiedOverlap:
    certified: int
    refuted: int
    refused: int
    per_link: tuple[tuple[str, str, str], ...]  # (a_name, b_name, verdict)

    @property
    def adjudicable(self) -> int:
        """Links with independent structure on BOTH sides (refused excluded)."""
        return self.certified + self.refuted

    @property
    def certified_rate(self) -> float | None:
        """certified / adjudicable — None when nothing was adjudicable (no false precision on empty)."""
        return self.certified / self.adjudicable if self.adjudicable else None


def certify_links(
    links: Iterable[Link],
    a_independent: Mapping[str, str | None],
    b_independent: Mapping[str, str | None],
) -> CertifiedOverlap:
    """Certify each link with KG-INDEPENDENT structures.

    ``a_independent``/``b_independent`` map a side's name to an independent InChIKey (resolved upstream
    from that cohort's vendor id via PubChem/HMDB — NOT the KG node). A missing/None key on either side
    yields ``refused`` for that link.
    """
    counts: Counter[str] = Counter()
    per: list[tuple[str, str, str]] = []
    for lk in links:
        cert = certify_link(a_independent.get(lk.a_name), b_independent.get(lk.b_name))
        counts[cert.verdict] += 1
        per.append((lk.a_name, lk.b_name, cert.verdict))
    return CertifiedOverlap(
        certified=counts["certified"],
        refuted=counts["refuted"],
        refused=counts["refused"],
        per_link=tuple(per),
    )


def certify_links_tagged(
    links: Iterable[Link],
    a_provided: Mapping[str, ProvidedBlock | None],
    b_provided: Mapping[str, ProvidedBlock | None],
    *,
    require_tags: bool = True,
) -> tuple[CertifiedOverlap, int]:
    """Certify links over PROVENANCE-TAGGED independent structures (``ProvidedBlock``), fail-closed.

    Each side carries a ``source`` tag; a KG-derived (``"kg"``) or — in strict mode — untagged side
    refuses rather than certifies (R4/KD2). Returns ``(overlap, untagged_sides)``: ``untagged_sides`` is
    the canary the reported-metric driver aborts on if nonzero, so no untagged block can silently feed
    the certified/refused number. A missing entry for a link's name counts as an untagged side.
    """
    counts: Counter[str] = Counter()
    per: list[tuple[str, str, str]] = []
    untagged_sides = 0
    for lk in links:
        a = a_provided.get(lk.a_name)
        b = b_provided.get(lk.b_name)
        a_block, a_src = (a.block, a.source) if a is not None else (None, None)
        b_block, b_src = (b.block, b.source) if b is not None else (None, None)
        if a_src is None:
            untagged_sides += 1
        if b_src is None:
            untagged_sides += 1
        cert = certify_link(
            a_block, b_block, necs_source=a_src, cohort_source=b_src, require_tags=require_tags
        )
        counts[cert.verdict] += 1
        per.append((lk.a_name, lk.b_name, cert.verdict))
    overlap = CertifiedOverlap(
        certified=counts["certified"],
        refuted=counts["refuted"],
        refused=counts["refused"],
        per_link=tuple(per),
    )
    return overlap, untagged_sides
