"""Unit B7 — live-runner import smoke + delegation + no-config operator error (NO network).

The live resolve/replicate loop is a supervised operator step (``# pragma: no cover``, never exercised
in pytest). What IS covered here: the module imports cleanly, the two former stubs now DELEGATE to it
(they no longer raise ``NotImplementedError``), and calling any live entry WITHOUT an arms config
raises a clear operator ``ValueError`` before touching the network. The autouse network-deny fixture
guarantees no live call escapes.
"""

from __future__ import annotations

import pytest

from studies.external_benchmarks import run_conflation_gate_live
from studies.external_benchmarks.conflation_gate import run_conflation_gate
from studies.external_benchmarks.cross_cohort_devapi_sweep import resolve_and_persist


def test_module_imports_and_exposes_run_live():
    assert hasattr(run_conflation_gate_live, "run_live")
    assert hasattr(run_conflation_gate_live, "resolve_and_persist_live")


def test_run_live_without_config_raises_operator_error():
    with pytest.raises(ValueError, match="config|operator"):
        run_conflation_gate_live.run_live(None)


def test_run_conflation_gate_stub_delegates_not_notimplemented():
    # The conflation_gate stub now delegates to run_live -> a no-config call is a clear operator error,
    # NOT NotImplementedError.
    with pytest.raises(ValueError, match="config|operator"):
        run_conflation_gate(None)


def test_resolve_and_persist_stub_delegates_not_notimplemented():
    with pytest.raises(ValueError, match="config|operator"):
        resolve_and_persist(None)
