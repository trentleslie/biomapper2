"""Unit 3 — Arm-B baseline reconstruction (Monti et al. 2026's published per-pair method).

Arm B is the number BioMapper is measured against. It is reconstructed here on the IDENTICAL row
set the M/M+ID arms use, so the comparison is like-for-like (R21a). Two methods, per the paper's
own ``Datasets harmonization`` text:

  - NECS↔Arivale, NECS↔Xu : Metabolon ``CHEMICAL_NAME`` string match (Arivale case-insensitive,
    Xu case-sensitive — the settings that reproduced the paper in the 2026-08-20 replication).
  - NECS↔LLFS, NECS↔BLSA  : RefMet standardized-name join, with ``drop_na(refmet_name)`` applied
    BEFORE the join (a name that does not RefMet-standardize cannot match).

Because WE build this baseline, it is a controlled variable: it must be **frozen** (locked as a
characterization test at a recorded commit) before any BioMapper live run, and the recovery claim
must beat **Monti-published** — the number we did NOT compute — by more than the per-pair
``|re-derived − published|`` reconstruction gap. This module exposes that gap on every result.

Fully offline: pure set logic over name lists and a precomputed RefMet map (a dict, loaded by the
caller from the persisted cache — never a network call here).
"""

from __future__ import annotations

from dataclasses import dataclass

# Monti et al. 2026 Table 2 published overlaps (the un-gamed comparator; we did not compute these).
MONTI_PUBLISHED: dict[str, int] = {"arivale": 615, "xuetal": 432, "llfs": 163, "blsa": 99}

# Per-pair method: ("name", case_sensitive) or ("refmet",). Unknown cohort → fail loud.
PAIR_METHOD: dict[str, tuple[str, ...]] = {
    "arivale": ("name", False),
    "xuetal": ("name", True),
    "llfs": ("refmet",),
    "blsa": ("refmet",),
}


@dataclass(frozen=True)
class ArmBResult:
    cohort: str
    method: str
    count: int  # re-derived overlap on the identical row set
    published: int  # Monti Table 2
    gap: int  # count - published; the error bar recovery must exceed


def _name_key(name: str, case_sensitive: bool) -> str:
    s = name.strip()
    return s if case_sensitive else s.lower()


def name_match_overlap(names_a: list[str], names_b: list[str], *, case_sensitive: bool) -> set[str]:
    """Overlap by exact CHEMICAL_NAME string match (Arm B for same-vendor pairs)."""
    a = {_name_key(n, case_sensitive) for n in names_a if n.strip()}
    b = {_name_key(n, case_sensitive) for n in names_b if n.strip()}
    return a & b


def refmet_join_overlap(
    names_a: list[str],
    names_b: list[str],
    refmet_map: dict[str, str],
) -> set[str]:
    """Overlap by RefMet standardized-name join, drop_na(refmet_name) BEFORE the join.

    ``refmet_map`` maps a raw name to its RefMet name; a name absent from the map or mapping to
    an empty string does not standardize and is dropped before the intersection (exactly Monti's
    ``drop_na`` step — a non-standardizing name can never match).
    """

    def refmet_set(names: list[str]) -> set[str]:
        out: set[str] = set()
        for n in names:
            r = refmet_map.get(n.strip(), "").strip()
            if r:
                out.add(r.lower())
        return out

    return refmet_set(names_a) & refmet_set(names_b)


def arm_b_overlap(
    cohort: str,
    necs_names: list[str],
    cohort_names: list[str],
    *,
    refmet_map: dict[str, str] | None = None,
) -> ArmBResult:
    """Compute Arm B for one NECS↔cohort pair using the cohort's published method. Fails loud on
    an unknown cohort (never defaults to name-match)."""
    if cohort not in PAIR_METHOD:
        raise ValueError(f"no Arm-B method registered for cohort {cohort!r}; known: {sorted(PAIR_METHOD)}")
    spec = PAIR_METHOD[cohort]
    if spec[0] == "name":
        matched = name_match_overlap(necs_names, cohort_names, case_sensitive=spec[1])
        method = f"CHEMICAL_NAME ({'case-sensitive' if spec[1] else 'case-insensitive'})"
    else:
        if refmet_map is None:
            raise ValueError(f"cohort {cohort!r} uses the RefMet method but no refmet_map was provided")
        matched = refmet_join_overlap(necs_names, cohort_names, refmet_map)
        method = "RefMet join (drop_na before join)"
    published = MONTI_PUBLISHED[cohort]
    return ArmBResult(
        cohort=cohort,
        method=method,
        count=len(matched),
        published=published,
        gap=len(matched) - published,
    )
