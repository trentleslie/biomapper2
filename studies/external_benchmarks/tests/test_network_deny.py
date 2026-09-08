"""Unit A0 — the autouse network-deny fixture is real, not conventional.

The whole studies suite claims to be offline. This proves the claim is ENFORCED: an un-injected
live PubChem call cannot reach the network, and a raw external connect fails loudly. The positive
control (a deliberate external connect) MUST raise — a guard that cannot fire is worthless.
"""

from __future__ import annotations

import socket

import pytest

from studies.external_benchmarks.scorers.independent_inchikey import PubChemInChIKeyResolver
from studies.external_benchmarks.tests.conftest import ExternalNetworkDenied


def test_external_connect_is_denied():
    # Positive control: a deliberate external connect must raise under the autouse fixture.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(ExternalNetworkDenied):
            s.connect(("pubchem.ncbi.nlm.nih.gov", 443))
    finally:
        s.close()


def test_local_connect_is_allowed_to_fail_normally():
    # A local connect is NOT denied by the guard: it passes through and fails with the OS error
    # (connection refused), never ExternalNetworkDenied. This proves the guard scopes to external.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.2)
    try:
        with pytest.raises(OSError) as exc:
            s.connect(("127.0.0.1", 1))  # nothing listening -> ConnectionRefused, not our guard
        assert not isinstance(exc.value, ExternalNetworkDenied)
    finally:
        s.close()


def test_uninjected_pubchem_resolver_cannot_reach_the_network():
    # An un-mocked resolver is fail-soft (returns None), but the point is it NEVER escapes to the
    # live service: the denied connect is swallowed into None rather than a real PubChem answer.
    block = PubChemInChIKeyResolver().block_for_name("D-Glucose")
    assert block is None
