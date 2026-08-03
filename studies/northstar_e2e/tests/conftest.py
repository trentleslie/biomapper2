"""Shared offline fixtures for the northstar_e2e slice.

Everything here is network-isolated: no live Kestrel / KEGG / Anthropic calls.
Later tasks extend this file with FakeMapper / FakeKestrel / fake_llm_fn.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def anon():
    """Placeholder fixture so pytest collects this package before real fixtures land."""
    return object()
