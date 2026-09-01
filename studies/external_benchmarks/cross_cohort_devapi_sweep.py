"""Unit D — committable cross-cohort sweep driver: dual metric + confound controls.

Two clearly separated layers:

  * PURE, unit-tested (no network): ``score_arm`` produces, for one arm/pair, the identifier-only CURIE
    overlap (coverage), the KG-derived stability descriptor overlap (Unit B, non-authoritative), and
    the KG-INDEPENDENT certified overlap (Unit C, the trust metric). ``arms_look_confounded`` is the
    guard that flags byte-identical arm caches — the shared-KG-cache confound that invalidated a sweep
    this session.

  * LIVE, SUPERVISED (``resolve_and_persist``, invoked explicitly by an operator; never in pytest):
    resolve panels through the dev API, resolve each side's INDEPENDENT structure from vendor ids via
    PubChem/HMDB, score with ``score_arm``, and persist a manifest that pins the deployed commit, the
    ``/metagraph`` fingerprint, the annotator set, a RefMet-availability probe, and a cache canary.

The confound protocol is documented on ``resolve_and_persist``: arms must be run against a COLD KG
cache (proven by a canary that differs cold-vs-warm), RefMet availability probed per arm and arms run
back-to-back in one window, and ≥3 replicates per arm to establish a per-pair noise floor. A process
restart of the dev API is NOT assumed sufficient — the canary, not the restart, is the gate.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .scorers.cross_cohort_overlap import (
    OverlapResult,
    curie_set,
    link_by_intersection,
    stability_descriptor_set,
)
from .scorers.independent_link_certificate_overlap import CertifiedOverlap, certify_links

# a resolved row = {"chosen_kg_id": str | None, "kg_equivalent_ids": dict}
ResolvedRows = Mapping[str, Mapping]


@dataclass(frozen=True)
class ArmScore:
    curie: OverlapResult  # identifier-only overlap — COVERAGE figure only
    stability: OverlapResult  # KG-derived descriptor overlap — NON-AUTHORITATIVE (Unit B)
    certified: CertifiedOverlap  # KG-INDEPENDENT trust metric (Unit C) — the gate metric


def score_arm(
    a_rows: ResolvedRows,
    b_rows: ResolvedRows,
    a_independent: Mapping[str, str | None],
    b_independent: Mapping[str, str | None],
) -> ArmScore:
    """Score one arm/pair under all three metrics from already-resolved rows + independent structures.

    ``a_independent``/``b_independent`` are name→independent InChIKey (from the cohort's own vendor id
    via PubChem/HMDB, NOT the KG node). The certified metric adjudicates the CURIE-linked pairs.
    """
    a_curie = {n: curie_set(r.get("chosen_kg_id"), r.get("kg_equivalent_ids")) for n, r in a_rows.items()}
    b_curie = {n: curie_set(r.get("chosen_kg_id"), r.get("kg_equivalent_ids")) for n, r in b_rows.items()}
    a_desc = {n: stability_descriptor_set(r.get("chosen_kg_id"), r.get("kg_equivalent_ids")) for n, r in a_rows.items()}
    b_desc = {n: stability_descriptor_set(r.get("chosen_kg_id"), r.get("kg_equivalent_ids")) for n, r in b_rows.items()}

    curie_ov = link_by_intersection(a_curie, b_curie)
    stability_ov = link_by_intersection(a_desc, b_desc)
    certified = certify_links(curie_ov.links, a_independent, b_independent)
    return ArmScore(curie=curie_ov, stability=stability_ov, certified=certified)


def arms_look_confounded(caches: Mapping[str, ResolvedRows]) -> list[tuple[str, str]]:
    """Guard: return arm pairs whose per-name chosen_kg_id is byte-identical — a probable shared-cache
    confound (one arm's cached KG responses served to a later arm). The metagraph fingerprint is NOT a
    cache signal (identical across arms whether cold or warm); this per-name equality is.

    NOTE: this catches only TOTAL degeneracy. Partial cache bleed yields non-identical outputs that
    slip past — which is why the live protocol also requires a cold-vs-warm canary per arm.
    """
    names = list(caches)
    flagged: list[tuple[str, str]] = []
    chosen = {a: {n: r.get("chosen_kg_id") for n, r in caches[a].items()} for a in names}
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if chosen[names[i]] == chosen[names[j]]:
                flagged.append((names[i], names[j]))
    return flagged


def resolve_and_persist(*args, **kwargs):  # pragma: no cover - supervised live step, never unit-tested
    """LIVE, SUPERVISED operator step — resolve panels via the dev API + independent oracle, score with
    ``score_arm``, and persist a manifest (deployed commit, /metagraph fingerprint, annotators, RefMet
    probe, cache canary, replicate index) under a timestamped path (R23).

    Deliberately unimplemented in the committable module: wiring it to the live dev API belongs in the
    gated Unit E/F operator runs, not in importable library code that a test could accidentally trip.
    """
    raise NotImplementedError(
        "resolve_and_persist is a supervised live step; run it from the gated Unit E/F operator harness"
    )
