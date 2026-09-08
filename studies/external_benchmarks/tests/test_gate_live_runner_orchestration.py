"""Unit B7 — the live gate orchestration runs END-TO-END offline (Greptile #62: harness must execute).

``_run_gate_flow`` is the injectable core of the operator harness: dev-API resolution, the PubChem
oracle, and the KG-build fetch are all passed in, so this drives the whole build-prereg -> persist ->
observe -> gate -> persist-result flow with fakes and NO network. It proves the harness executes (no
NotImplementedError), that the prereg is persisted BEFORE observation (pre-registration, R4/R23), and
that the positive-control plant is detected. Only the thin live-provider wiring in ``_execute_gate``
(the /tmp/.bmk key read + real HTTP) stays ``# pragma: no cover``.
"""

from __future__ import annotations

import json
import socket
from types import SimpleNamespace

import pytest

from studies.external_benchmarks import run_conflation_gate_live as R
from studies.external_benchmarks.conflation_gate import GateResult, Thresholds
from studies.external_benchmarks.gate_live_config import parse_arms_config

_BLOCK = {  # name -> independent InChIKey block (alpha/alpha2 agree; beta/beta2 agree; distinct otherwise)
    "alpha": "AAAAAAAAAAAAAA-AAAAAAAA",
    "alpha2": "AAAAAAAAAAAAAA-AAAAAAAA",
    "beta": "BBBBBBBBBBBBBB-BBBBBBBB",
    "beta2": "BBBBBBBBBBBBBB-BBBBBBBB",
    "gamma": "GGGGGGGGGGGGGG-GGGGGGGG",
}
_A_NAMES = ["alpha", "beta", "gamma"]
_B_NAMES = ["alpha2", "beta2"]
_KEPT = [("alpha", "alpha2"), ("beta", "beta2")]


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _blocked(*a, **k):
        raise AssertionError("network access in the offline orchestration test")

    monkeypatch.setattr(socket.socket, "connect", _blocked)


class _FakeOracle:
    def block_for_name(self, name):
        return _BLOCK.get(name)


def _resolve_fn(api_base, names):
    # alpha/alpha2 share CHEBI:1, beta/beta2 share CHEBI:2 (both certified links); gamma's CURIE differs
    # by arm so baseline/treatment caches are NOT byte-identical (else the A2 confound guard ABSTAINs),
    # while the kept links are identical across arms (-> NOOP verdict).
    base = {"alpha": "CHEBI:1", "alpha2": "CHEBI:1", "beta": "CHEBI:2", "beta2": "CHEBI:2"}
    rows = {}
    for n in names:
        cid = base.get(n) or ("CHEBI:100" if "base" in api_base else "CHEBI:200")  # gamma diverges per arm
        rows[n] = {"chosen_kg_id": cid, "kg_equivalent_ids": {}, "error": None}
    return rows


def _fake_fetch(url):
    return ("2.0.1", SimpleNamespace(kg_version="v1", git_commit="abc123"))


def _arms():
    return parse_arms_config(
        {
            "baseline": {
                "api_base": "http://base", "kestrel_url": "http://kb",
                "deployed_commit": "c1", "attestation_token": "COLD",
            },
            "treatment": {
                "api_base": "http://treat", "kestrel_url": "http://kt",
                "deployed_commit": "c2", "attestation_token": "COLD",
            },
        }
    )


def _flow(tmp_path, resolve_fn=_resolve_fn, **over):
    known = tmp_path / "refuted_pairs.json"
    known.write_text(json.dumps([["alpha", "beta2"]]))  # planted conflation: distinct blocks -> refuted
    masks = {a: {p: frozenset({f"RM:{i}"}) for i, p in enumerate(_KEPT)} for a in ("baseline", "treatment")}
    kw = dict(
        arms_specs=_arms(),
        a_names=_A_NAMES,
        b_names=_B_NAMES,
        replicates=3,
        resolve_fn=resolve_fn,
        oracle_resolver=_FakeOracle(),
        masks_by_arm=masks,
        adjudicable_pairs=_KEPT,
        known_conflations_path=str(known),
        baseline_refused_fraction=0.1,  # PRE-REGISTERED input, not computed from this run's baseline
        thresholds=Thresholds(),
        cold_canary_expected="COLD",
        pair_id="necs__xuetal",
        fetch=_fake_fetch,
    )
    kw.update(over)
    out = tmp_path / "run"
    return R._run_gate_flow(out, **kw), out


def test_run_gate_flow_runs_offline_and_detects_the_plant(tmp_path):
    result, out = _flow(tmp_path)
    assert isinstance(result, GateResult)
    assert result.decision not in ("ABORT", "ABSTAIN")  # not invalidated, not confounded
    assert result.positive_control_ok is True  # the plant's refutation was detected
    assert (out / "prereg.json").exists() and (out / "result.json").exists()
    loaded = json.loads((out / "result.json").read_text())
    assert loaded["decision"] == result.decision


def test_prereg_is_persisted_before_any_arm_is_observed(tmp_path):
    seen = {"prereg_at_first_resolve": None}

    def _checking_resolve(api_base, names):
        if seen["prereg_at_first_resolve"] is None:
            # the FIRST network call must find the pre-registration contract already on disk (R4/R23)
            seen["prereg_at_first_resolve"] = (tmp_path / "run" / "prereg.json").exists()
        return _resolve_fn(api_base, names)

    result, out = _flow(tmp_path, resolve_fn=_checking_resolve)
    assert seen["prereg_at_first_resolve"] is True  # prereg persisted BEFORE the first observation
    assert isinstance(result, GateResult)


def test_require_kwarg_raises_naming_the_missing_input():
    with pytest.raises(ValueError, match="a_names"):
        R._require_kwarg({}, "a_names")
