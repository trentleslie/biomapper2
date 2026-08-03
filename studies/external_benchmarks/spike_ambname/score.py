"""Unit 3 - the two scoring variants, at both match granularities.

Both variants are computed from the SAME set of resolved model referents, at
two InChIKey granularities:

* ``block``    - first block (2-D connectivity skeleton). Avoids protonation /
                 stereo false-negatives (the #6 charge-state issue).
* ``full``     - the full InChIKey.

Variant 1 - ANY-MEMBER: did ANY resolved model InChIKey land in the gold
referent set? Per-name pass/fail; report % passing. (Expected high - this is the
softness test that the spike exists to run.)

Variant 2 - FULL-SET RECALL: precision / recall / F1 of the model's enumerated
referent set vs the gold set. (Expected low - the potentially TB-Science-worthy
framing.)

BioMapper's 41.7% is carried as a reference anchor by the caller; it is not
recomputed here.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .resolve import first_block


def _project(keys: Iterable[str], granularity: str) -> set[str]:
    if granularity == "block":
        return {b for b in (first_block(k) for k in keys) if b}
    if granularity == "full":
        return {k.strip() for k in keys if k and k.strip()}
    raise ValueError(f"granularity must be 'block' or 'full', got {granularity!r}")


@dataclass(frozen=True)
class NameScore:
    name: str
    granularity: str
    any_member: bool
    precision: float | None
    recall: float | None
    f1: float | None
    gold_size: int
    predicted_size: int
    tp: int


def score_name(
    *,
    name: str,
    gold_inchikeys: Iterable[str],
    predicted_inchikeys: Iterable[str],
    granularity: str,
) -> NameScore:
    gold = _project(gold_inchikeys, granularity)
    pred = _project(predicted_inchikeys, granularity)
    tp = len(gold & pred)

    precision = (tp / len(pred)) if pred else None
    recall = (tp / len(gold)) if gold else None
    if precision is not None and recall is not None and (precision + recall) > 0:
        f1: float | None = 2 * precision * recall / (precision + recall)
    else:
        f1 = None

    return NameScore(
        name=name,
        granularity=granularity,
        any_member=tp > 0,
        precision=precision,
        recall=recall,
        f1=f1,
        gold_size=len(gold),
        predicted_size=len(pred),
        tp=tp,
    )


@dataclass(frozen=True)
class Aggregate:
    granularity: str
    n_names: int
    any_member_rate: float | None
    any_member_passes: int
    mean_precision: float | None
    mean_recall: float | None
    mean_f1: float | None

    def as_dict(self) -> dict:
        return {
            "granularity": self.granularity,
            "n_names": self.n_names,
            "any_member": {
                "rate": self.any_member_rate,
                "passes": self.any_member_passes,
                "denominator": self.n_names,
            },
            "full_set_recall": {
                "macro_precision": self.mean_precision,
                "macro_recall": self.mean_recall,
                "macro_f1": self.mean_f1,
            },
        }


def _mean(xs: list[float]) -> float | None:
    vals = [x for x in xs if x is not None]
    return (sum(vals) / len(vals)) if vals else None


def aggregate(scores: list[NameScore], granularity: str) -> Aggregate:
    rows = [s for s in scores if s.granularity == granularity]
    n = len(rows)
    passes = sum(1 for s in rows if s.any_member)
    return Aggregate(
        granularity=granularity,
        n_names=n,
        any_member_rate=(passes / n) if n else None,
        any_member_passes=passes,
        mean_precision=_mean([s.precision for s in rows]),  # type: ignore[misc]
        mean_recall=_mean([s.recall for s in rows]),  # type: ignore[misc]
        mean_f1=_mean([s.f1 for s in rows]),  # type: ignore[misc]
    )
