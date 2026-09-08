"""Unit B4 — positive-control plant from empirically-known small-molecule conflations (R-D2).

The plant is the gate's self-test arm. It takes pairs of names that are KNOWN to be different molecules
(the refuted candidates a prior Xu↔NECS diagnosis produced) and forces each pair onto a shared
NON-STRUCTURAL CURIE so the identifier-only linker (``link_by_intersection``) joins them into a link;
the SAME PubChem-by-name oracle the arms use then adjudicates that link as ``refuted`` (the two names
carry different structures). ``evaluate_conflation_gate`` runs its self-test on this arm and ABORTs if
the decision core cannot detect it.

Why non-structural: ``curie_set`` strips INCHIKEY/INCHI/SMILES, so a plant keyed on an InChIKey would
never link. The shared id must be a CHEBI/KEGG/PUBCHEM CURIE.

Pure/offline: builds rows + verifies against passed-in oracle blocks. ``load_known_conflations`` reads
a ``refuted_pairs.json`` runtime artifact (run the diagnosis first) or a small curated fallback.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

from .cross_cohort_devapi_sweep import ResolvedRows, score_arm

Pair = tuple[str, str]

_STRUCTURAL_NAMESPACES = frozenset({"INCHIKEY", "INCHI", "SMILES"})

# A small CURATED fallback of known small-molecule conflations (same formula / different connectivity),
# used when no ``refuted_pairs.json`` artifact is available. The REAL set comes from running the
# Xu↔NECS certificate diagnosis first; this fallback only keeps the self-test non-degenerate.
_CURATED_FALLBACK: tuple[Pair, ...] = (
    ("D-Xylose", "D-Glucose"),
    ("D-Glucose", "D-Fructose"),
    ("L-Leucine", "L-Isoleucine"),
)


def load_known_conflations(path: str | Path | None) -> list[Pair]:
    """Load known-conflation name pairs from a ``refuted_pairs.json`` artifact, or the curated fallback.

    The artifact is the ``refuted_pairs.json`` a prior Xu↔NECS diagnosis wrote (a list of ``[a, b]``
    pairs). Document the prerequisite: run that diagnosis first for the empirical set. Absent a path (or
    a missing file), fall back to the small curated set so the plant is never empty.
    """
    if path is not None:
        p = Path(path)
        if p.exists():
            raw = json.loads(p.read_text())
            return [(str(a), str(b)) for a, b in raw]
    return list(_CURATED_FALLBACK)


def build_plant_rows(
    baseline_rows: ResolvedRows,
    known_conflations: Iterable[Pair],
    shared_prefix: str = "CHEBI",
) -> tuple[dict[str, dict], dict[str, dict]]:
    """Force each known-bad pair onto a shared non-structural CURIE -> (a_rows, b_rows) that will link.

    * ``shared_prefix`` MUST be non-structural (CHEBI/KEGG/PUBCHEM); an InChIKey/InChI/SMILES prefix is
      rejected — ``curie_set`` would strip it and the plant would never link.
    * a pair naming an analyte absent from ``baseline_rows`` is SKIPPED (it cannot be planted honestly).
    * if no pair survives, the plant is DEGENERATE and this raises (never a silent empty self-test).
    """
    if shared_prefix.upper() in _STRUCTURAL_NAMESPACES:
        raise ValueError(
            f"shared_prefix {shared_prefix!r} is structural — the plant must use a non-structural CURIE "
            "(CHEBI/KEGG/PUBCHEM); curie_set strips INCHIKEY/INCHI/SMILES so it would never link"
        )
    a_rows: dict[str, dict] = {}
    b_rows: dict[str, dict] = {}
    idx = 0
    for a_name, b_name in known_conflations:
        if a_name not in baseline_rows or b_name not in baseline_rows:
            continue  # absent analyte — skip (documented)
        shared = f"{shared_prefix}:9{idx:06d}"
        a_rows[a_name] = {"chosen_kg_id": shared, "kg_equivalent_ids": {}}
        b_rows[b_name] = {"chosen_kg_id": shared, "kg_equivalent_ids": {}}
        idx += 1
    if not a_rows:
        raise ValueError(
            "degenerate plant — no known conflation survived (empty set or all names absent from the "
            "baseline panel); the positive control cannot be built"
        )
    return a_rows, b_rows


def verify_plant_refutes(
    a_rows: ResolvedRows,
    b_rows: ResolvedRows,
    a_independent: Mapping[str, str | None],
    b_independent: Mapping[str, str | None],
) -> int:
    """Score the plant under the SAME oracle the arms use; return the refuted count, raise if 0.

    The whole point of the plant is that it carries at least one link the certificate ``refutes``. If
    scoring produces zero refuted links the plant is worthless (it cannot exercise the FAIL path), so
    this raises rather than let a silently-good plant clear the self-test.
    """
    score = score_arm(a_rows, b_rows, a_independent, b_independent)
    refuted = score.certified.refuted
    if refuted < 1:
        raise ValueError(
            f"plant scored {refuted} refuted links under the arms' oracle — a degenerate positive "
            "control (it cannot fire the FAIL path); check the known-conflation set + oracle blocks"
        )
    return refuted
