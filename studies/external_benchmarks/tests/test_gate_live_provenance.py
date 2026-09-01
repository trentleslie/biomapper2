"""Unit B5 — Prereg + manifest assembly with all reproducibility pins (pure/offline; fetch mocked).

The prereg is pinned BEFORE arms are observed. It must carry: per-arm deployed_commit + Kestrel
build fingerprint (via ``fetch_kg_build_info``, injected/mocked), the RefMet masks + the declared
adjudicable population (A3's expectation), the attestation tokens, the known-conflation set, and the
baseline refused fraction. The positive control is the ``plant`` arm, required to ``FAIL``. Missing
thresholds or a missing mask declaration raise — no silent default gate.
"""

from __future__ import annotations

import pytest

from biomapper2.provenance import KgBuildInfo
from studies.external_benchmarks.conflation_gate import Thresholds
from studies.external_benchmarks.gate_live_config import ArmSpec
from studies.external_benchmarks.gate_live_provenance import build_prereg


def _arms():
    return {
        "baseline": ArmSpec("baseline", "http://localhost:8003", "http://localhost:8001", "aaaa1111", "COLD_x"),
        "treatment": ArmSpec("treatment", "http://localhost:8003", "http://localhost:8001", "bbbb2222", "COLD_x"),
    }


def _fetch_ok(kestrel_url):
    return "kestrel-9.9", KgBuildInfo(kg_version="2.0.1", git_commit="kg-sha-1", kg_label="krakenkg")


def _fetch_degraded(kestrel_url):
    return "unknown", KgBuildInfo()  # all-unknown, as fetch_kg_build_info degrades on failure


def _build(**over):
    kwargs = dict(
        arms=_arms(),
        refmet_masks={
            "baseline": {("a", "b"): frozenset({"a"})},
            "treatment": {("a", "b"): frozenset({"a"})},
        },
        adjudicable_pairs=[("a", "b")],
        known_conflations=[("D-Xylose", "D-Glucose")],
        baseline_refused_fraction=0.42,
        thresholds=Thresholds(),
        cold_canary_expected="COLD_x",
        pair_ids=("necs__xuetal",),
        fetch=_fetch_ok,
    )
    kwargs.update(over)
    return build_prereg(**kwargs)


def test_prereg_and_manifest_complete_and_reproducible():
    prereg, manifest = _build()
    assert prereg.positive_control_arm == "plant"
    assert prereg.positive_control_required == "FAIL"
    assert prereg.adjudicable_pairs == (("a", "b"),)
    # per-arm pins present
    assert manifest["arms"]["baseline"]["deployed_commit"] == "aaaa1111"
    assert manifest["arms"]["treatment"]["deployed_commit"] == "bbbb2222"
    assert "2.0.1" in manifest["arms"]["treatment"]["kg_fingerprint"]
    assert manifest["baseline_refused_fraction"] == 0.42
    assert manifest["known_conflations"] == [["D-Xylose", "D-Glucose"]]
    assert manifest["cold_canary_expected"] == "COLD_x"
    # reproducible: same inputs -> identical manifest
    _, manifest2 = _build()
    assert manifest == manifest2


def test_degraded_fetch_records_unknown_without_raising():
    prereg, manifest = _build(fetch=_fetch_degraded)
    assert "unknown" in manifest["arms"]["treatment"]["kg_fingerprint"]


def test_missing_thresholds_raises():
    with pytest.raises(ValueError, match="thresholds"):
        _build(thresholds=None)


def test_missing_adjudicable_declaration_raises():
    with pytest.raises(ValueError, match="adjudicable|mask"):
        _build(adjudicable_pairs=[])


def test_mask_not_covering_adjudicable_raises():
    # A3's expectation must hold at prereg time too: a declared adjudicable pair with no mask on an arm
    # is a mask-declaration gap -> raise.
    with pytest.raises(ValueError, match="mask|adjudicable"):
        _build(refmet_masks={"baseline": {("a", "b"): frozenset({"a"})}, "treatment": {}})
