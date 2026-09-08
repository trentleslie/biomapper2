"""Loader tests for the pinned RefMet freeze (core/annotators/refmet_snapshot.py).

Fixture-only: the loader reads a committed 2-row freeze TSV under tests/fixtures/. No network, no
real data file. ``REFMET_SNAPSHOT_PATH`` is pointed at the fixture per test and the module cache is
reset around each so the process-global singleton never leaks a snapshot into the rest of the suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from biomapper2.core.annotators import refmet_snapshot

pytestmark = pytest.mark.unit

FIXTURE = Path(__file__).parent / "fixtures" / "refmet_freeze_fixture.tsv"


@pytest.fixture(autouse=True)
def _reset_snapshot_cache():
    refmet_snapshot.reset()
    yield
    refmet_snapshot.reset()


@pytest.fixture
def loaded(monkeypatch):
    monkeypatch.setenv("REFMET_SNAPSHOT_PATH", str(FIXTURE))
    refmet_snapshot.reset()
    return refmet_snapshot


def test_is_present_false_when_unconfigured(monkeypatch):
    monkeypatch.delenv("REFMET_SNAPSHOT_PATH", raising=False)
    refmet_snapshot.reset()
    assert refmet_snapshot.is_present() is False
    assert refmet_snapshot.version() is None
    assert refmet_snapshot.lookup("Cholic acid") is None


def test_is_present_true_when_configured(loaded):
    assert loaded.is_present() is True


def test_voted_hit(loaded):
    hit = loaded.lookup("Cholic acid")
    assert hit is not None
    assert hit.status == "voted"
    assert hit.refmet_id == "RM0041813"
    assert hit.extra["formula"] == "C24H40O5"


def test_no_match_hit(loaded):
    hit = loaded.lookup("definitely not a real metabolite")
    assert hit is not None
    assert hit.status == "no_match"
    assert hit.refmet_id is None


def test_miss_returns_none(loaded):
    assert loaded.lookup("a name that is not in the freeze at all") is None


def test_version_reported_from_sidecar(loaded):
    assert loaded.version() == "fixture-v1"
    assert loaded.lookup("Cholic acid").version == "fixture-v1"


def test_normalized_fallback_matches_case_and_whitespace(loaded):
    hit = loaded.lookup("  cholic   ACID ")
    assert hit is not None
    assert hit.refmet_id == "RM0041813"
