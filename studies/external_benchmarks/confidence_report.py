"""Regenerate the benchmark section's intervals from a suite directory already on disk.

Reads a completed suite, emits one labelled row per (dataset, arm or regime, correctness flag) with
a score interval, and writes both a machine-readable artifact and a rendered table. It makes no
requests: every input is a file the suite already wrote.

Why a per-dataset registry and not a generic reader
---------------------------------------------------
The result shapes diverge more than one reader can absorb. One dataset ships no conventionally
named results file at all; one nests its results under an extra level; one puts its per-row
correctness under a third key name; four carry three correctness flags over the same rows; two
carry an aggregate that is a union or an exact partition of its own sub-rows. A glob over the
conventional filename silently drops the first of those, and a silently-dropped dataset is
indistinguishable from a dataset that scored badly.

So the registry is explicit, it *raises* on a suite dataset it does not know, and it distinguishes
loudly between "this dataset is not registered" (a defect in this file) and "this dataset is absent
from the suite because its run failed" (a fact about the run, reported with the suite's own reason).

What the rows are careful about
-------------------------------
* **Provenance per row.** The commit and the graph snapshot ride on every row, not only in the
  header, for as long as any row could have come from a different run.
* **Which flag.** Every interval names the correctness flag it was computed from. An unlabelled
  interval on a structure-oracle dataset is a silent metric switch.
* **Dependence.** Several rows are not independent of each other: a relaxed correctness flag is a
  superset of the strict one over the same rows; an any-namespace figure is a union over
  overlapping subsets; a dataset total is the exact sum of its own sub-rows. Nested pairs are
  reported as paired differences with a coherent test, and unions and aggregates are marked
  derived. Two marginal intervals failing to overlap is not a difference test and the header says
  so.
* **Independent items.** A score interval assumes independent items. Templated names from
  homologous series, or a single reference material, break that. Where a cluster key exists a
  cluster-robust companion is emitted beside the plain interval; where no clustering is plausible
  the assertion is recorded rather than left implicit.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .stats import (
    Z_95,
    mcnemar,
    newcombe_paired_mover,
    tango_paired_difference,
    wilson_interval,
)

MODULE_DIR = Path(__file__).parent
RESULTS_DIR = MODULE_DIR / "results"
PREREG_PATH = MODULE_DIR / "prereg_d4.json"
OFF_CATEGORY_RESULTS_DIR = MODULE_DIR.parent / "analysis" / "results"

INDEPENDENCE_ROLES = ("primary", "nested", "derived_union", "derived_aggregate", "standalone")

_FORBIDDEN_INFERENCE = (
    "These intervals are MARGINAL, not simultaneous. No claim of the form 'X exceeds Y' may be "
    "derived from two intervals failing to overlap: non-overlap is neither necessary nor "
    "sufficient for a difference, and several rows in this table are not independent of each "
    "other. Where a difference is claimed, use the paired_difference field on the dependent row."
)

_WILSON_ASSUMPTION = (
    "the score interval treats items as independent draws; where they are not, the effective "
    "denominator is below the nominal one and the plain half-width is over-precise"
)


class UnregisteredDatasetError(KeyError):
    """A suite dataset has no registered reader.

    Raised rather than skipped: a reader that quietly ignores an unknown dataset produces a table
    that is missing a row for no stated reason, which is the exact failure this module exists to
    prevent.
    """


class UndeclaredTestFamilyError(KeyError):
    """A p-value was produced under a family that the committed pre-registration does not declare."""


# ------------------------------------------------------------------------------------------------
# Pre-registration
# ------------------------------------------------------------------------------------------------
def load_prereg(path: Path | None = None) -> dict[str, Any]:
    """The committed multiplicity declaration. Consumed by the reporting code, not applied by hand."""
    return json.loads((path or PREREG_PATH).read_text())


def _family(family_id: str, prereg: dict[str, Any] | None = None) -> dict[str, Any]:
    prereg = prereg or load_prereg()
    for family in prereg["families"]:
        if family["id"] == family_id:
            return family
    raise UndeclaredTestFamilyError(
        f"{family_id!r} is not declared in the committed pre-registration; choosing a family after "
        f"seeing output is precisely what the declaration exists to prevent"
    )


def adjust_within_family(
    entries: list[dict[str, Any]],
    *,
    family_id: str,
    p_key: str,
    prereg: dict[str, Any] | None = None,
) -> list[float]:
    """Apply the family's declared multiplicity correction across every test in that family."""
    family = _family(family_id, prereg)
    method = family["correction"]
    raw = [entry[p_key] for entry in entries]
    n = len(raw)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: raw[i])
    adjusted = [0.0] * n
    if method == "holm":
        running = 0.0
        for rank, index in enumerate(order):
            value = min(1.0, (n - rank) * raw[index])
            running = max(running, value)
            adjusted[index] = running
    elif method == "benjamini_hochberg":
        running = 1.0
        for rank in range(n - 1, -1, -1):
            index = order[rank]
            value = min(1.0, raw[index] * n / (rank + 1))
            running = min(running, value)
            adjusted[index] = running
    else:  # pragma: no cover - the prereg is committed and enumerates its methods
        raise UndeclaredTestFamilyError(f"family {family_id!r} declares an unknown correction {method!r}")
    return adjusted


# ------------------------------------------------------------------------------------------------
# Row construction helpers
# ------------------------------------------------------------------------------------------------
_LIPID_SHORTHAND = re.compile(r"^([A-Za-z]{1,6})[\s(]")


def _lipid_class(name: Any) -> str | None:
    """The leading class token of a lipid shorthand name, or ``None`` when the name is not one.

    Names drawn from a homologous series share a class and are not independent draws; this is the
    only cluster key derivable from what the suite persists.
    """
    match = _LIPID_SHORTHAND.match(str(name or "").strip())
    return match.group(1).upper() if match else None


def _cluster_robust(clusters: dict[str, tuple[int, int]], z: float = Z_95) -> dict[str, Any] | None:
    """Linearised cluster-robust interval for a ratio, plus the design effect it implies.

    ``clusters`` maps a cluster key to ``(k, n)``. Needs at least two clusters; with one there is
    no between-cluster information and the honest answer is that no companion can be computed.
    """
    if len(clusters) < 2:
        return None
    total_k = sum(k for k, _ in clusters.values())
    total_n = sum(n for _, n in clusters.values())
    if total_n == 0:
        return None
    p_hat = total_k / total_n
    g = len(clusters)
    residual = sum((k - p_hat * n) ** 2 for k, n in clusters.values())
    variance = (g / ((g - 1) * total_n**2)) * residual
    binomial_variance = p_hat * (1 - p_hat) / total_n if total_n else 0.0
    half = z * math.sqrt(max(variance, 0.0))
    return {
        "method": "linearised cluster-robust variance for a ratio",
        "n_clusters": g,
        "estimate": p_hat,
        "lower": max(0.0, p_hat - half),
        "upper": min(1.0, p_hat + half),
        "half_width_pt": round(100 * half, 4),
        "design_effect": (variance / binomial_variance) if binomial_variance > 0 else None,
    }


def _assumption(
    *,
    cluster_key: str | None,
    clusters: dict[str, tuple[int, int]] | None = None,
    assertion: str | None = None,
) -> dict[str, Any]:
    return {
        "wilson_assumes": _WILSON_ASSUMPTION,
        "cluster_key": cluster_key,
        "cluster_robust": _cluster_robust(clusters) if clusters else None,
        "assertion": assertion,
    }


def _make_row(
    *,
    dataset: str,
    row_id: str,
    metric: str,
    correctness_flag: str,
    k: int,
    n: int,
    pins: dict[str, Any],
    independence_family: str,
    independence_role: str,
    independence_assumption: dict[str, Any],
    regime: str | None = None,
    arm: str | None = None,
    vocab: str | None = None,
    derived_from: list[str] | None = None,
    not_independent_of: str | None = None,
    paired_difference: dict[str, Any] | None = None,
    coverage: dict[str, Any] | None = None,
    note: str = "",
) -> dict[str, Any]:
    lower, upper = wilson_interval(k, n)
    assert independence_role in INDEPENDENCE_ROLES
    return {
        "dataset": dataset,
        "row_id": row_id,
        "regime": regime or "overall",
        "arm": arm,
        "vocab": vocab,
        "metric": metric,
        "correctness_flag": correctness_flag,
        "k": k,
        "n": n,
        "rate": (k / n) if n else None,
        "wilson": {"lower": lower, "upper": upper, "z": Z_95, "method": "score (Wilson) interval"},
        "half_width_pt": (round(100 * (upper - lower) / 2, 4) if n else None),
        "independence_family": independence_family,
        "independence_role": independence_role,
        "independence_assumption": independence_assumption,
        "not_independent_of": not_independent_of,
        "derived_from": derived_from,
        "paired_difference": paired_difference,
        "coverage": coverage,
        "note": note,
        # Per row, not only in the header: a single header pin is a claim about the whole table
        # that the table cannot support for as long as any row could come from a different run.
        "git_sha": pins.get("git_sha"),
        "kg_snapshot": pins.get("kg_snapshot"),
    }


def _paired_variant(
    per_row: list[dict[str, Any]],
    *,
    strict_key: str,
    variant_key: str,
    id_key: str,
    n: int,
    k_strict: int,
    k_variant: int,
) -> dict[str, Any] | None:
    """Paired difference between a strict flag and a relaxed variant over the same rows."""
    if not per_row:
        return None
    ids = [row.get(id_key) for row in per_row]
    if len(set(ids)) != len(ids):
        return {
            "unavailable": (
                f"per-row ids under {id_key!r} are not unique, so a paired contrast keyed on them "
                f"would manufacture discordant pairs; no difference statistic emitted"
            ),
            "family": "oracle_variant_contrasts",
            "mcnemar": {"p_exact": None, "p_midp": None, "b": None, "c": None},
            "lower": None,
            "upper": None,
            "b": None,
            "c": None,
            "p_adjusted": None,
            "n_tests_in_family": None,
        }
    b = sum(1 for row in per_row if bool(row.get(variant_key)) and not bool(row.get(strict_key)))
    c = sum(1 for row in per_row if bool(row.get(strict_key)) and not bool(row.get(variant_key)))
    interval = tango_paired_difference(b=b, c=c, n=len(per_row))
    test = mcnemar(b, c)
    mover = newcombe_paired_mover(k1=k_variant, k2=k_strict, b=b, c=c, n=n) if n == len(per_row) else None
    return {
        "contrast": f"{variant_key} minus {strict_key}",
        "family": "oracle_variant_contrasts",
        "b": b,
        "c": c,
        "n": len(per_row),
        "estimate": interval["estimate"],
        "lower": interval["lower"],
        "upper": interval["upper"],
        "method": interval["method"],
        "mover_companion": mover,
        "mcnemar": test,
        "p_adjusted": None,  # filled in once the family is complete
        "n_tests_in_family": None,
    }


# ------------------------------------------------------------------------------------------------
# Per-dataset extractors
# ------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class DatasetSpec:
    """How one dataset's results are found and turned into rows."""

    key: str
    patterns: tuple[str, ...]
    extractor: Callable[..., list[dict[str, Any]]]
    shape_note: str


_STRUCT_METRICS = (
    ("strict", "correct", "comparable_core"),
    ("charge_normalized", "charge_normalized_correct", "comparable_core_charge_normalized"),
    ("kg_equivalence_set", "kg_equivalence_set_correct", "comparable_core_kg_equivalence_set"),
)


def _structure_oracle_rows(
    dataset: str,
    payloads: list[tuple[Path, Any]],
    pins: dict[str, Any],
    *,
    cluster_by_name: bool = False,
    single_material_assertion: str | None = None,
) -> list[dict[str, Any]]:
    """Rows for a dataset carrying three nested correctness flags, optionally split by regime."""
    rows: list[dict[str, Any]] = []
    for path, payload in payloads:
        vocab = payload.get("vocab") or path.stem.split("_")[0]
        per_row = payload.get("per_row") or []
        regimes = payload.get("by_name_source_regime") or {}
        family = f"{dataset}:{vocab}"

        def _clusters(rows_subset: list[dict[str, Any]], flag: str) -> dict[str, tuple[int, int]] | None:
            if not cluster_by_name:
                return None
            buckets: dict[str, list[int]] = {}
            for row in rows_subset:
                key = _lipid_class(row.get("name"))
                if key is None:
                    continue
                buckets.setdefault(key, [0, 0])
                buckets[key][1] += 1
                buckets[key][0] += 1 if bool(row.get(flag)) else 0
            return {k: (v[0], v[1]) for k, v in buckets.items()} or None

        # Whole-dataset rows, one per correctness flag.
        strict_core = payload.get("comparable_core") or {}
        k_strict = int(strict_core.get("correct", 0))
        scored_rows = [r for r in per_row if r.get("scored")]
        overall_role = "derived_aggregate" if regimes else "primary"
        derived_from = [f"{dataset}:{vocab}:{name}:strict" for name in regimes] if regimes else None

        for metric, flag, core_key in _STRUCT_METRICS:
            core = payload.get(core_key)
            if not core:
                continue
            k = int(core.get("correct", 0))
            n = int(core.get("scored_denominator", 0))
            nested = metric != "strict"
            paired = None
            if nested and scored_rows:
                paired = _paired_variant(
                    scored_rows,
                    strict_key="correct",
                    variant_key=flag,
                    id_key="name",
                    n=n,
                    k_strict=k_strict,
                    k_variant=k,
                )
            role = "nested" if nested else overall_role
            rows.append(
                _make_row(
                    dataset=dataset,
                    row_id=f"{dataset}:{vocab}:overall:{metric}",
                    metric=metric,
                    correctness_flag=flag,
                    k=k,
                    n=n,
                    pins=pins,
                    vocab=vocab,
                    independence_family=family,
                    independence_role=role,
                    independence_assumption=_assumption(
                        cluster_key="lipid_class" if cluster_by_name else None,
                        clusters=_clusters(scored_rows, flag),
                        assertion=single_material_assertion,
                    ),
                    not_independent_of=(f"{dataset}:{vocab}:overall:strict" if nested else None),
                    derived_from=derived_from if not nested else None,
                    paired_difference=paired,
                    coverage=payload.get("coverage"),
                    note=core.get("metric", ""),
                )
            )

        # Regime rows. Emitted separately with their own denominators: a regime rate printed
        # against the dataset denominator is off by about a factor of two on half-width.
        for regime_name, regime_payload in regimes.items():
            regime_rows = [r for r in scored_rows if _regime_of(r) == regime_name]
            regime_strict = regime_payload.get("comparable_core") or {}
            k_regime_strict = int(regime_strict.get("correct", 0))
            for metric, flag, core_key in _STRUCT_METRICS:
                core = regime_payload.get(core_key)
                if not core:
                    continue
                k = int(core.get("correct", 0))
                n = int(core.get("scored_denominator", 0))
                nested = metric != "strict"
                paired = None
                if nested and regime_rows:
                    paired = _paired_variant(
                        regime_rows,
                        strict_key="correct",
                        variant_key=flag,
                        id_key="name",
                        n=n,
                        k_strict=k_regime_strict,
                        k_variant=k,
                    )
                rows.append(
                    _make_row(
                        dataset=dataset,
                        row_id=f"{dataset}:{vocab}:{regime_name}:{metric}",
                        metric=metric,
                        correctness_flag=flag,
                        k=k,
                        n=n,
                        pins=pins,
                        vocab=vocab,
                        regime=regime_name,
                        independence_family=f"{family}:{regime_name}",
                        independence_role="nested" if nested else "primary",
                        independence_assumption=_assumption(
                            cluster_key="lipid_class" if cluster_by_name else None,
                            clusters=_clusters(regime_rows, flag),
                            assertion=single_material_assertion,
                        ),
                        not_independent_of=(f"{dataset}:{vocab}:{regime_name}:strict" if nested else None),
                        paired_difference=paired,
                        coverage=regime_payload.get("coverage"),
                        note=core.get("metric", ""),
                    )
                )
    return rows


def _regime_of(row: dict[str, Any]) -> str:
    """Map a per-row name source onto its regime label."""
    source = str(row.get("name_source") or "").strip().lower()
    if source in {"shorthand", "abbreviation"}:
        return "shorthand"
    if source:
        return "common_systematic"
    return "unlabelled"


def _refmet_rows(dataset, payloads, pins):
    return _structure_oracle_rows(
        dataset,
        payloads,
        pins,
        single_material_assertion=(
            "a curated cross-source reference list; no clustering structure is asserted, so the "
            "plain interval is the one to read"
        ),
    )


def _necs_rows(dataset, payloads, pins):
    return _structure_oracle_rows(
        dataset,
        payloads,
        pins,
        single_material_assertion=(
            "one vendor delivery for one cohort; items are distinct compounds, so no cluster key "
            "is asserted, but the delivery is a single source and the rate does not generalise "
            "beyond it"
        ),
    )


def _srm1950_rows(dataset, payloads, pins):
    return _structure_oracle_rows(
        dataset,
        payloads,
        pins,
        single_material_assertion=(
            "a SINGLE certified reference material: the items are one material's constituents, not "
            "a sample from a population of materials, so the interval covers sampling error over "
            "these items only and generalises to no wider population"
        ),
    )


def _lmsd_rows(dataset, payloads, pins):
    return _structure_oracle_rows(dataset, payloads, pins, cluster_by_name=True)


def _hajjar_rows(dataset, payloads, pins):
    """Results are wrapped under an extra level; the sibling key is a different task entirely."""
    rows: list[dict[str, Any]] = []
    for path, payload in payloads:
        wrapped = payload.get("structure") or {}
        vocab = path.stem.split("_")[0]
        core = wrapped.get("comparable_core") or {}
        if not core:
            continue
        rows.append(
            _make_row(
                dataset=dataset,
                row_id=f"{dataset}:{vocab}:overall:strict",
                metric="strict",
                correctness_flag="correct",
                k=int(core.get("correct", 0)),
                n=int(core.get("scored_denominator", 0)),
                pins=pins,
                vocab=vocab,
                independence_family=f"{dataset}:curated-100",
                independence_role="primary",
                independence_assumption=_assumption(
                    cluster_key=None,
                    assertion=(
                        "a hand-curated list of distinct compounds; no clustering structure is "
                        "asserted. The sibling 'paper' block in this file is a DIFFERENT task "
                        "(round-trip consistency on identifier inputs) and is never merged here"
                    ),
                ),
                note="structure oracle",
            )
        )
    return rows


def _hgnc_rows(dataset, payloads, pins):
    """Per-namespace subsets overlap; the any-namespace figure is a union over them."""
    rows: list[dict[str, Any]] = []
    for path, payload in payloads:
        vocab = payload.get("vocab") or path.stem.split("_")[0]
        core = payload.get("comparable_core") or {}
        per_namespace = payload.get("per_namespace") or {}
        family = f"{dataset}:symbol-sample"
        rows.append(
            _make_row(
                dataset=dataset,
                row_id=f"{dataset}:{vocab}:any-namespace:strict",
                metric="strict",
                correctness_flag="correct",
                k=int(core.get("correct", 0)),
                n=int(core.get("scored_denominator", 0)),
                pins=pins,
                vocab=vocab,
                arm=payload.get("arm"),
                independence_family=family,
                independence_role="derived_union",
                derived_from=[f"{dataset}:{vocab}:{ns}:strict" for ns in per_namespace],
                independence_assumption=_assumption(
                    cluster_key=None,
                    assertion=(
                        "a union over OVERLAPPING per-namespace subsets of the same symbols; the "
                        "sub-rows are not independent of this row or of each other, so the four "
                        "intervals must not be read side by side as separate measurements"
                    ),
                ),
                note="any-namespace union",
            )
        )
        for namespace, stats in per_namespace.items():
            rows.append(
                _make_row(
                    dataset=dataset,
                    row_id=f"{dataset}:{vocab}:{namespace}:strict",
                    metric="strict",
                    correctness_flag="correct",
                    k=int(stats.get("correct", 0)),
                    n=int(stats.get("scored", 0)),
                    pins=pins,
                    vocab=vocab,
                    regime=namespace,
                    arm=payload.get("arm"),
                    independence_family=family,
                    independence_role="nested",
                    not_independent_of=f"{dataset}:{vocab}:any-namespace:strict",
                    independence_assumption=_assumption(
                        cluster_key=None,
                        assertion=(
                            "an overlapping subset of the same symbol sample; not independent of "
                            "the other namespaces or of the union row"
                        ),
                    ),
                    note="per-namespace subset",
                )
            )
    return rows


def _metabench_rows(dataset, payloads, pins):
    """The whole is the exact sum of its sub-rows, so the whole is derived and marked so."""
    rows: list[dict[str, Any]] = []
    for _path, payload in payloads:
        core = payload.get("comparable_core") or {}
        per_namespace = payload.get("per_namespace") or {}
        family = f"{dataset}:grounding"
        rows.append(
            _make_row(
                dataset=dataset,
                row_id=f"{dataset}:overall:strict",
                metric="strict",
                correctness_flag="correct",
                k=int(core.get("correct", 0)),
                n=int(core.get("scored_denominator", 0)),
                pins=pins,
                arm=payload.get("arm"),
                independence_family=family,
                independence_role="derived_aggregate",
                derived_from=[f"{dataset}:{ns}:strict" for ns in per_namespace],
                independence_assumption=_assumption(
                    cluster_key=None,
                    assertion=(
                        "the exact sum of the target-namespace sub-rows below, which partition "
                        "this population; it carries no information the sub-rows do not"
                    ),
                ),
            )
        )
        for namespace, stats in per_namespace.items():
            rows.append(
                _make_row(
                    dataset=dataset,
                    row_id=f"{dataset}:{namespace}:strict",
                    metric="strict",
                    correctness_flag="correct",
                    k=int(stats.get("correct", 0)),
                    n=int(stats.get("scored", 0)),
                    pins=pins,
                    regime=namespace,
                    independence_family=family,
                    independence_role="primary",
                    independence_assumption=_assumption(
                        cluster_key=None,
                        assertion="a disjoint stratum of the grounding set; strata partition the population",
                    ),
                )
            )
    return rows


def _name_hit_rows(dataset, payloads, pins):
    """Per-mode subdirectories; the per-row key is a coverage flag with no gold/predicted pair."""
    rows: list[dict[str, Any]] = []
    for path, payload in payloads:
        mode = payload.get("mode") or path.parent.name
        core = payload.get("comparable_core") or {}
        # The numerator key differs from every other scorer's; read it explicitly rather than
        # falling back to zero, which would publish a rate of nothing as if it were a measurement.
        numerator_keys = ("matched", "hits", "correct")
        present = [key for key in numerator_keys if key in core]
        if not present:
            raise UnregisteredDatasetError(
                f"{dataset}: the name-hit core in {path} carries none of {numerator_keys!r}; its "
                f"shape has changed and the reader must be updated rather than reporting zero"
            )
        k = int(core[present[0]])
        n = int(core.get("total", core.get("scored_denominator", 0)))
        rows.append(
            _make_row(
                dataset=dataset,
                row_id=f"{dataset}:{mode}:name_hit",
                metric="name_hit_rate",
                correctness_flag="hit",
                k=k,
                n=n,
                pins=pins,
                arm=mode,
                independence_family=f"{dataset}:{mode}",
                independence_role="standalone",
                independence_assumption=_assumption(
                    cluster_key=None,
                    assertion=("unique curated names from independent studies; no clustering structure is asserted"),
                ),
                note=(
                    "COVERAGE, not correctness: the flag records that an identifier was produced, "
                    "never that it matches the study's own annotation"
                ),
            )
        )
    return rows


def _metlinkr_rows(dataset, payloads, pins):
    """Two labelled oracles, never merged; the per-row correctness key is a third vocabulary."""
    rows: list[dict[str, Any]] = []
    for _path, payload in payloads:
        agreement = payload.get("curator_agreement") or {}
        rows.append(
            _make_row(
                dataset=dataset,
                row_id=f"{dataset}:curator_agreement",
                metric="curator_agreement_rate",
                correctness_flag="linked",
                k=int(agreement.get("linked", 0)),
                n=int(agreement.get("curator_cross_pairs", 0)),
                pins=pins,
                independence_family=f"{dataset}:curator-pairs",
                independence_role="standalone",
                independence_assumption=_assumption(
                    cluster_key=None,
                    assertion=(
                        "curator-asserted cross-dataset pairs; pairs sharing a member are not fully "
                        "independent, and no cluster key for that structure is persisted, so the "
                        "plain half-width is an upper bound on precision"
                    ),
                ),
                note="link recall on the curators' asserted cross-links",
            )
        )
        structural = payload.get("inchikey_structural_concordance")
        if structural:
            per_row = structural.get("struct_per_row") or []
            rows.append(
                _make_row(
                    dataset=dataset,
                    row_id=f"{dataset}:structural_concordance",
                    metric="inchikey_structural_concordance",
                    correctness_flag="concordant",
                    k=int(structural.get("concordant", 0)),
                    n=int(structural.get("scored", 0)),
                    pins=pins,
                    independence_family=f"{dataset}:structural",
                    independence_role="standalone",
                    independence_assumption=_assumption(
                        cluster_key=None,
                        assertion=(
                            "rows the external source could cover; rows it could not are held out "
                            "as needs-verification rather than scored either way"
                        ),
                    ),
                    note=(
                        "per-row rows persisted: "
                        + ("yes" if per_row else "no")
                        + "; the per-row correctness key here is 'concordant', a third vocabulary "
                        "distinct from the other scorers'"
                    ),
                )
            )
    return rows


def _nlmgene_rows(dataset, payloads, pins):
    """No conventionally named results file: two differently-named files instead."""
    rows: list[dict[str, Any]] = []
    for path, payload in payloads:
        if path.name == "unambiguous_accuracy.json":
            rows.append(
                _make_row(
                    dataset=dataset,
                    row_id=f"{dataset}:unambiguous:accuracy",
                    metric="unambiguous_accuracy",
                    correctness_flag="correct",
                    k=int(payload.get("correct", 0)),
                    n=int(payload.get("scored", 0)),
                    pins=pins,
                    independence_family=f"{dataset}:mentions",
                    independence_role="primary",
                    independence_assumption=_assumption(
                        cluster_key=None,
                        assertion=(
                            "gene mentions drawn from a corpus of abstracts; mentions within one "
                            "abstract are not independent, and no per-abstract key is persisted, "
                            "so the plain half-width is an upper bound on precision"
                        ),
                    ),
                )
            )
        elif path.name == "ambiguous_flagrate.json":
            rows.append(
                _make_row(
                    dataset=dataset,
                    row_id=f"{dataset}:ambiguous:flag_rate",
                    metric="ambiguous_flag_rate",
                    correctness_flag="flagged",
                    k=int(payload.get("flagged", 0)),
                    n=int(payload.get("total", 0)),
                    pins=pins,
                    independence_family=f"{dataset}:ambiguous",
                    independence_role="standalone",
                    independence_assumption=_assumption(
                        cluster_key=None,
                        assertion="a flag rate, not an accuracy; no correctness oracle is involved",
                    ),
                    note="RATE OF FLAGGING, not correctness",
                )
            )
    return rows


def _no_rows(dataset, payloads, pins):
    """A dataset the suite deliberately does not run unattended."""
    return []


REGISTRY: dict[str, DatasetSpec] = {
    "refmet": DatasetSpec("refmet", ("*_results.json",), _refmet_rows, "three nested correctness flags"),
    "necs": DatasetSpec("necs", ("*_results.json",), _necs_rows, "three nested correctness flags"),
    "srm1950": DatasetSpec("srm1950", ("*_results.json",), _srm1950_rows, "single reference material"),
    "lmsd": DatasetSpec("lmsd", ("*_results.json",), _lmsd_rows, "regime split + lipid-class clustering"),
    "hajjar": DatasetSpec("hajjar", ("*_results.json",), _hajjar_rows, "results wrapped under an extra level"),
    "hgnc": DatasetSpec("hgnc", ("*_results.json",), _hgnc_rows, "per-namespace union over overlapping subsets"),
    "metabench": DatasetSpec("metabench", ("*_results.json",), _metabench_rows, "aggregate is an exact partition sum"),
    "metaboliteannotator": DatasetSpec(
        "metaboliteannotator",
        ("*/name_hit_results.json",),
        _name_hit_rows,
        "per-mode subdirectories; per-row key is a coverage flag",
    ),
    "metlinkr": DatasetSpec("metlinkr", ("metlinkr_results.json",), _metlinkr_rows, "per-row key is 'concordant'"),
    "nlmgene": DatasetSpec(
        "nlmgene",
        ("unambiguous_accuracy.json", "ambiguous_flagrate.json"),
        _nlmgene_rows,
        "NO conventionally named results file; a glob drops this dataset silently",
    ),
    "swisslipids": DatasetSpec("swisslipids", ("*_results.json",), _refmet_rows, "same shape as the other lipid sets"),
    "provided-id": DatasetSpec("provided-id", ("*_results.json",), _no_rows, "not run unattended"),
    "pham": DatasetSpec("pham", ("*_results.json",), _no_rows, "not run unattended"),
}


# ------------------------------------------------------------------------------------------------
# Reading a suite
# ------------------------------------------------------------------------------------------------
def _load_payloads(dataset_dir: Path, patterns: Iterable[str]) -> list[tuple[Path, Any]]:
    found: list[tuple[Path, Any]] = []
    for pattern in patterns:
        for path in sorted(dataset_dir.glob(pattern)):
            if path.name.endswith("_manifest.json") or path.name == "dataset_card.json":
                continue
            try:
                found.append((path, json.loads(path.read_text())))
            except json.JSONDecodeError:  # pragma: no cover - a corrupt artifact is worth naming
                continue
    return found


def _off_category_weighting(suite_id: str) -> dict[str, Any]:
    """The deduplicated cross-dataset rate, which is the one to quote.

    A dataset that ships several target-vocabulary files carrying identical resolutions enters the
    file-weighted total once per file. That figure is pointed at BY FIELD NAME rather than restated
    here, so it cannot be quoted from this artifact by accident.
    """
    block: dict[str, Any] = {
        "quote_this": "deduplicated",
        "weighting_warning": (
            "the file-weighted cross-dataset rate multiplies a dataset by the number of "
            "target-vocabulary files it ships, and those files carry identical resolutions. Quote "
            "the deduplicated figure below; the file-weighted one is named, not carried, so it "
            "cannot be lifted from here"
        ),
        "file_weighted_field": "metabolite_total.pct_off_category in the off-category audit artifact",
        "source_artifact": None,
        "deduplicated": None,
    }
    candidate = OFF_CATEGORY_RESULTS_DIR / f"off_category_audit_{suite_id}.json"
    if candidate.exists():
        audit = json.loads(candidate.read_text())
        dedup = audit.get("metabolite_total_deduplicated") or {}
        block["source_artifact"] = str(candidate)
        block["deduplicated"] = {
            "definition": dedup.get("definition"),
            "n_rows_with_commit": dedup.get("n_rows_with_commit"),
            "n_off_category": dedup.get("n_off_category"),
            "pct_off_category": dedup.get("pct_off_category"),
            "representative_files": dedup.get("representative_files"),
        }
    return block


def build_report(suite_dir: Path | str) -> dict[str, Any]:
    """Read a suite directory already on disk and build the full interval report."""
    suite_dir = Path(suite_dir)
    manifest = json.loads((suite_dir / "suite_manifest.json").read_text())
    pins = manifest.get("pins") or {}
    suite_id = suite_dir.name

    rows: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for entry in manifest.get("datasets", []):
        key = entry["dataset"]
        spec = REGISTRY.get(key)
        if spec is None:
            raise UnregisteredDatasetError(
                f"{key!r} appears in the suite manifest but has no registered reader. Register it "
                f"(with the shape its results file actually has) rather than letting the table "
                f"lose a row without saying so."
            )
        dataset_dir = suite_dir / key
        payloads = _load_payloads(dataset_dir, spec.patterns) if dataset_dir.exists() else []
        produced = spec.extractor(key, payloads, pins) if payloads else []
        rows.extend(produced)
        if not produced:
            missing.append(
                {
                    "dataset": key,
                    "suite_status": entry.get("status"),
                    "reason": entry.get("error") or entry.get("reason") or "no results file matched this dataset",
                    "patterns_tried": list(spec.patterns),
                    "shape_note": spec.shape_note,
                }
            )
        elif entry.get("status") != "ok":
            # Partial completion: one arm produced usable results on disk under a dataset-level
            # failed status. Both facts are recorded, so the completed arm is not invisible.
            missing.append(
                {
                    "dataset": key,
                    "suite_status": entry.get("status"),
                    "reason": entry.get("error") or entry.get("reason") or "",
                    "partial": True,
                    "arms_present": sorted({row["row_id"] for row in produced}),
                }
            )

    _apply_declared_corrections(rows)

    metagraph = pins.get("kg_metagraph") or {}
    header = {
        "report": "confidence_intervals",
        "suite_id": suite_id,
        "suite_dir": str(suite_dir),
        "generated_utc": _dt.datetime.now(_dt.UTC).isoformat(),
        "git_sha": pins.get("git_sha"),
        "kg_snapshot": pins.get("kg_snapshot"),
        "biolink_version": pins.get("biolink_version"),
        "backend": pins.get("backend"),
        "graph_census": metagraph.get("summary") or metagraph,
        # Recorded as-is rather than omitted: omitting the field leaves a reader unable to tell
        # "not recorded" from "not asked", and the node count is the available fingerprint.
        "chebi_release": pins.get("chebi_release", "unrecorded"),
        "chebi_node_count": pins.get("chebi_node_count") or metagraph.get("chebi_node_count"),
        "interval_method": "score (Wilson) for single proportions; score interval for paired differences",
        "z": Z_95,
        "interval_simultaneity": "marginal",
        "forbidden_inference": _FORBIDDEN_INFERENCE,
        "preregistration": load_prereg(),
        "seed_free": True,
    }
    return {
        "header": header,
        "rows": rows,
        "missing_datasets": missing,
        "off_category_weighting": _off_category_weighting(suite_id),
    }


def _apply_declared_corrections(rows: list[dict[str, Any]]) -> None:
    """Apply each declared family's correction across every test in that family."""
    by_family: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        diff = row.get("paired_difference")
        if not diff or diff.get("mcnemar", {}).get("p_exact") is None:
            continue
        by_family.setdefault(diff["family"], []).append(diff)
    for family_id, entries in by_family.items():
        flat = [{"p": entry["mcnemar"]["p_exact"]} for entry in entries]
        adjusted = adjust_within_family(flat, family_id=family_id, p_key="p")
        for entry, value in zip(entries, adjusted):
            entry["p_adjusted"] = value
            entry["n_tests_in_family"] = len(entries)


# ------------------------------------------------------------------------------------------------
# Rendering + writing
# ------------------------------------------------------------------------------------------------
def render_markdown(report: dict[str, Any]) -> str:
    header = report["header"]
    lines = [
        f"# Confidence intervals — {header['suite_id']}",
        "",
        f"- backend: `{header['backend']}`",
        f"- commit: `{header['git_sha']}`",
        f"- graph snapshot: `{header['kg_snapshot']}`",
        f"- biolink: `{header['biolink_version']}`",
        f"- ChEBI release: `{header['chebi_release']}` (node-count fingerprint: `{header['chebi_node_count']}`)",
        "",
        "> " + header["forbidden_inference"],
        "",
        "Intervals are **marginal**, seed-free and closed-form.",
        "",
        "| row | dataset | regime | metric | flag | k | n | rate | interval | ±pt | role | family |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in report["rows"]:
        interval = row["wilson"]
        lo = "" if interval["lower"] is None else f"{interval['lower']:.4f}"
        hi = "" if interval["upper"] is None else f"{interval['upper']:.4f}"
        rate = "" if row["rate"] is None else f"{row['rate']:.4f}"
        lines.append(
            f"| `{row['row_id']}` | {row['dataset']} | {row['regime']} | {row['metric']} | "
            f"`{row['correctness_flag']}` | {row['k']} | {row['n']} | {rate} | [{lo}, {hi}] | "
            f"{row['half_width_pt']} | {row['independence_role']} | `{row['independence_family']}` |"
        )

    paired = [(row, row["paired_difference"]) for row in report["rows"] if row.get("paired_difference")]
    if paired:
        lines += [
            "",
            "## Paired differences (nested contrasts)",
            "",
            "Reported as differences rather than as two side-by-side intervals: the relaxed flag is a",
            "superset of the strict one over the same rows, so their marginal intervals overlap by",
            "construction and reading them as independent understates the contrast.",
            "",
            "| row | contrast | b | c | difference | interval | exact p | adjusted p | family |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for row, diff in paired:
            if diff.get("unavailable"):
                lines.append(f"| `{row['row_id']}` | - | - | - | - | - | - | - | {diff['unavailable']} |")
                continue
            # A contrast with no discordant rows has no test statistic. Rendered as undefined
            # rather than as a large p-value, which would assert an absence the data cannot show.
            p_exact = diff["mcnemar"]["p_exact"]
            p_exact_text = "undefined" if p_exact is None else f"{p_exact:.3g}"
            p_adj_text = "undefined" if diff["p_adjusted"] is None else f"{diff['p_adjusted']:.3g}"
            lines.append(
                f"| `{row['row_id']}` | {diff['contrast']} | {diff['b']} | {diff['c']} | "
                f"{diff['estimate']:.5f} | [{diff['lower']:.5f}, {diff['upper']:.5f}] | "
                f"{p_exact_text} | {p_adj_text} | `{diff['family']}` |"
            )

    if report["missing_datasets"]:
        lines += [
            "",
            "## Datasets absent or partial",
            "",
            "Listed rather than dropped: an omitted dataset is indistinguishable from one that",
            "scored badly.",
            "",
            "| dataset | suite status | reason |",
            "|---|---|---|",
        ]
        for entry in report["missing_datasets"]:
            lines.append(f"| {entry['dataset']} | {entry['suite_status']} | {entry['reason']} |")

    weighting = report["off_category_weighting"]
    dedup = weighting.get("deduplicated")
    lines += ["", "## Cross-dataset weighting", "", weighting["weighting_warning"], ""]
    if dedup and dedup.get("pct_off_category") is not None:
        lines.append(
            f"Deduplicated off-category rate: **{dedup['pct_off_category']}%** "
            f"({dedup['n_off_category']} of {dedup['n_rows_with_commit']} committed rows)."
        )
    else:
        lines.append("The off-category audit artifact for this suite is not present; no rate is quoted.")
    lines.append("")
    return "\n".join(lines)


def write_report(suite_dir: Path | str, out: Path | str | None = None) -> dict[str, Path]:
    """Build and SAVE the report. Saving is the default; ``out`` is an override, not the switch.

    A run that is expensive to reproduce must not depend on a flag to persist its results.
    """
    report = build_report(suite_dir)
    suite_id = report["header"]["suite_id"]
    target_dir = Path(out) if out is not None else RESULTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    json_path = target_dir / f"confidence_intervals_{suite_id}.json"
    md_path = target_dir / f"confidence_intervals_{suite_id}.md"
    json_path.write_text(json.dumps(report, indent=2))
    md_path.write_text(render_markdown(report))
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    return {"json": json_path, "md": md_path}


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    import argparse

    parser = argparse.ArgumentParser(description="Regenerate interval estimates from a suite directory on disk.")
    parser.add_argument("suite_dir", type=Path)
    parser.add_argument("--out", type=Path, default=None, help="override the default results directory")
    args = parser.parse_args(argv)
    write_report(args.suite_dir, out=args.out)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
