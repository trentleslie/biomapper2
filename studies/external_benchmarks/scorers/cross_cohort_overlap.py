"""Unit 2 — cross-cohort overlap scorer (Arm M / M+ID linking rule).

The linker is CURIE-set INTERSECTION and nothing else (R6): two metabolites — one per cohort —
link iff their normalized CURIE sets share at least one member. Structure is NEVER consulted here;
that is the certificate's job (Unit 5), resolved from an oracle independent of these CURIEs (R6a).
Keeping the linker structure-free is what stops precision from being 100% by construction.

A metabolite's CURIE set is drawn from BioMapper's ``chosen_kg_id`` plus its ``kg_equivalent_ids``
(any namespace), normalized via ``curie_scorer.normalize_curie`` so prefix synonyms for one id
space compare equal (``KEGG.COMPOUND:C00031`` == ``KEGG:C00031``) while genuinely different spaces
(``KEGG.GLYCAN``) stay distinct.

This module is fully offline: it consumes already-resolved CURIE sets (real ones from a live run,
or mocks in tests) and never calls the mapper or the KG.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .curie_scorer import CHOSEN_COL, EQUIV_COL, predicted_curies

# Structure-encoding namespaces are EXCLUDED from the linker: linking two metabolites via a shared
# InChIKey (a structure hash) would make the linker structural, which R6 forbids — and would make
# the later independent-structure certificate circular. The linker is IDENTIFIER-only (CHEBI/KEGG/
# HMDB/PUBCHEM/CAS/…); structure is the certificate's job (Unit 5), from a KG-independent oracle.
_STRUCTURAL_NAMESPACES: frozenset[str] = frozenset({"INCHIKEY", "INCHI", "SMILES"})


def curie_set(chosen: Any = None, equivalents: Any = None) -> frozenset[str]:
    """Identifier-only CURIE set for one metabolite = chosen_kg_id ∪ kg_equivalent_ids, MINUS any
    structure-encoding namespace (InChIKey/InChI/SMILES).

    Delegates to ``curie_scorer.predicted_curies`` so the REAL ``kg_equivalent_ids`` shape is
    handled: a ``{prefix: [local_id, ...]}`` dict (or its dict-repr string from a TSV), NOT a
    ``|``-delimited list. An empty result means the metabolite did not resolve — a refusal
    candidate downstream, not a link.
    """
    row = pd.Series({CHOSEN_COL: chosen, EQUIV_COL: equivalents})
    return frozenset(
        c for c in predicted_curies(row) if c.split(":", 1)[0] not in _STRUCTURAL_NAMESPACES
    )


def row_curie_set(row: pd.Series) -> frozenset[str]:
    """Identifier-only CURIE set straight from a BioMapper output row (the live-run path)."""
    return curie_set(row.get(CHOSEN_COL), row.get(EQUIV_COL))


@dataclass(frozen=True)
class Link:
    a_name: str
    b_name: str
    shared: frozenset[str]  # the CURIE(s) that formed the link — carried for the certificate/audit


@dataclass(frozen=True)
class OverlapResult:
    links: tuple[Link, ...]
    n_links: int  # distinct (a, b) linked pairs
    n_a_linked: int  # distinct A-side names in a link
    n_b_linked: int  # distinct B-side names in a link
    n_a_comparable: int  # A-side names with a non-empty CURIE set (the shared-denominator basis, R9)
    n_b_comparable: int  # B-side names with a non-empty CURIE set


def link_by_intersection(
    a_curies: dict[str, frozenset[str]],
    b_curies: dict[str, frozenset[str]],
) -> OverlapResult:
    """Link A↔B metabolites whose normalized CURIE sets intersect (Arm M / M+ID).

    Uses an inverted CURIE→names index so cost is O(total CURIEs) rather than O(|A|·|B|). A pair
    sharing several CURIEs yields ONE link carrying all shared CURIEs. The comparable denominator
    (R9) is the count of names with a non-empty CURIE set on each side — identical whatever formed
    the sets (Arm M vs M+ID), so arms share a denominator.
    """
    idx_b: dict[str, set[str]] = defaultdict(set)
    for b_name, curies in b_curies.items():
        for c in curies:
            idx_b[c].add(b_name)

    pair_shared: dict[tuple[str, str], set[str]] = defaultdict(set)
    for a_name, curies in a_curies.items():
        for c in curies:
            for b_name in idx_b.get(c, ()):
                pair_shared[(a_name, b_name)].add(c)

    links = tuple(
        Link(a_name=a, b_name=b, shared=frozenset(shared))
        for (a, b), shared in sorted(pair_shared.items())
    )
    return OverlapResult(
        links=links,
        n_links=len(links),
        n_a_linked=len({lk.a_name for lk in links}),
        n_b_linked=len({lk.b_name for lk in links}),
        n_a_comparable=sum(1 for s in a_curies.values() if s),
        n_b_comparable=sum(1 for s in b_curies.values() if s),
    )
