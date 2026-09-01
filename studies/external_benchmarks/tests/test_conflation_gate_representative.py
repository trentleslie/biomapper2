"""Unit F — the representative replicate is chosen over the SAME retained population it is scored on.

Ranking replicates by their full ``CertifiedOverlap`` totals while the gate then measures the floor and
deltas over the RefMet-parity-retained links only is a population mismatch: parity-excluded variability
could reorder the replicates and pick a different median than the retained-link decision is taken on.
So ``representative(arm, kept)`` must rank by the kept-link counts. Pure/offline.
"""

from __future__ import annotations

import socket

import pytest

from studies.external_benchmarks.conflation_gate import ArmReplicates, representative
from studies.external_benchmarks.cross_cohort_devapi_sweep import ArmScore
from studies.external_benchmarks.scorers.cross_cohort_overlap import OverlapResult
from studies.external_benchmarks.scorers.independent_link_certificate_overlap import CertifiedOverlap


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _blocked(*a, **k):
        raise AssertionError("network access in a Unit-F test — must be pure/offline")

    monkeypatch.setattr(socket.socket, "connect", _blocked)


_EMPTY_OV = OverlapResult(links=(), n_links=0, n_a_linked=0, n_b_linked=0, n_a_comparable=0, n_b_comparable=0)


def _score(certified, refuted, refused, per_link=()) -> ArmScore:
    return ArmScore(
        curie=_EMPTY_OV,
        stability=_EMPTY_OV,
        certified=CertifiedOverlap(certified=certified, refuted=refuted, refused=refused, per_link=tuple(per_link)),
    )


def _arm(reps) -> ArmReplicates:
    return ArmReplicates(name="t", replicates=tuple(reps), canary_reading="COLD", refmet_mask={})


def test_representative_ranks_over_kept_not_full_totals():
    kept = {("x", "a")}
    # Full-total order is r1 < r2 < r3 (median r2); but restricted to the retained link ("x","a") r2
    # scores as a refusal (0 certified) so the kept-median is r1 instead.
    r1 = _score(1, 0, 0, per_link=[("x", "a", "certified")])
    r2 = _score(2, 0, 0, per_link=[("x", "a", "refused"), ("y", "b", "certified")])
    r3 = _score(3, 0, 0, per_link=[("x", "a", "certified"), ("y", "b", "certified")])
    arm = _arm([r1, r2, r3])
    assert representative(arm) is r2  # no mask -> full-total median (no-mask contract)
    assert representative(arm, kept) is r1  # retained-link median differs -> the fix


def test_empty_kept_falls_back_to_full_total_order():
    r1 = _score(1, 0, 0, per_link=[("x", "a", "certified")])
    r2 = _score(2, 0, 0, per_link=[("x", "a", "refused")])
    r3 = _score(3, 0, 0, per_link=[("x", "a", "certified")])
    arm = _arm([r1, r2, r3])
    assert representative(arm, set()) is r2  # empty mask == no mask
