"""Unit D — sweep driver scoring + confound guard (pure; NO live call).

An autouse fixture blocks socket connects so a stray dev-API/oracle call would FAIL the test rather
than silently hit localhost:8003 (the review's stray-live-call risk). The scoring is pure, so the
tests pass under the block — proving isolation.
"""

from __future__ import annotations

import socket

import pytest

from studies.external_benchmarks.cross_cohort_devapi_sweep import (
    arms_look_confounded,
    score_arm,
)

L_GLU = "WHUUTDBJXJRKMK-VKHMYHEASA-N"
UREA = "XSQUKJJJFZCRTK-UHFFFAOYSA-N"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _blocked(*a, **k):
        raise AssertionError("network access in a Unit-D scoring test — must be pure/offline")

    monkeypatch.setattr(socket.socket, "connect", _blocked)


def _row(chosen):
    return {"chosen_kg_id": chosen, "kg_equivalent_ids": {"CHEBI": [chosen.split(":", 1)[1]]}}


def test_score_arm_curie_link_certified_when_independent_agrees():
    a = {"glutamate": _row("CHEBI:29987")}
    b = {"glutamic acid": _row("CHEBI:29987")}  # same node -> CURIE link
    s = score_arm(a, b, {"glutamate": L_GLU}, {"glutamic acid": L_GLU})
    assert s.curie.n_links == 1
    assert s.certified.certified == 1 and s.certified.refuted == 0


def test_score_arm_certified_metric_refutes_a_shared_generic_node_false_positive():
    # The exact Xu-style inflation: two names share ONE KG node (CURIE-linked) but their INDEPENDENT
    # structures disagree -> the trust metric refutes the link the CURIE overlap counted.
    a = {"m1": _row("CHEBI:99999")}
    b = {"m2": _row("CHEBI:99999")}
    s = score_arm(a, b, {"m1": L_GLU}, {"m2": UREA})
    assert s.curie.n_links == 1  # CURIE overlap counts it
    assert s.certified.refuted == 1 and s.certified.certified == 0  # trust metric rejects it


def test_arms_look_confounded_flags_identical_caches():
    a = {"x": _row("CHEBI:1"), "y": _row("CHEBI:2")}
    identical = {"x": _row("CHEBI:1"), "y": _row("CHEBI:2")}
    distinct = {"x": _row("CHEBI:1"), "y": _row("CHEBI:3")}
    assert arms_look_confounded({"arm_a": a, "arm_b": identical}) == [("arm_a", "arm_b")]
    assert arms_look_confounded({"arm_a": a, "arm_c": distinct}) == []
