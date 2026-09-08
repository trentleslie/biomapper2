"""Shared fixtures for the external-benchmarks tests.

Everything is network-isolated: fixtures build in-memory DataFrames / fake resolvers so
the suite runs offline and deterministically. No live Kestrel/MW/PubChem calls.

Network isolation is now ENFORCED, not conventional: ``_deny_external_network`` is an autouse
fixture that raises on any ``socket.socket.connect`` to a non-local host. A study test that
forgets to inject a fake resolver and reaches for live PubChem/Kestrel fails loudly here instead
of silently hitting the network (or, for fail-soft resolvers, silently degrading). Local/AF_UNIX
connects are still allowed so in-process fakes and any local fixtures keep working. Tests inject
fakes via DI/monkeypatch as before — this is a backstop, not the primary isolation mechanism.
"""

from __future__ import annotations

import socket

import pandas as pd
import pytest

from studies.external_benchmarks.config import HAJJAR

_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "0.0.0.0"})


class ExternalNetworkDenied(RuntimeError):
    """Raised when a study test attempts to connect to a non-local host."""


@pytest.fixture(autouse=True)
def _deny_external_network(monkeypatch):
    """Deny external ``socket.socket.connect`` for every studies test (enforced isolation).

    AF_UNIX (str address) and local AF_INET connects pass through so in-process fixtures still
    work; any external host raises ``ExternalNetworkDenied``. This is the guard R-Core asks for:
    an un-mocked live call fails the test instead of silently escaping.
    """
    real_connect = socket.socket.connect

    def guarded(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else None
        if host is None or host in _LOCAL_HOSTS:
            return real_connect(self, address, *args, **kwargs)
        raise ExternalNetworkDenied(f"external network denied in tests: {address!r}")

    monkeypatch.setattr(socket.socket, "connect", guarded)


@pytest.fixture(autouse=True)
def _reset_metagraph_cache():
    """Clear the process-global metagraph memo between tests.

    ``runner._fetch_metagraph`` caches for the life of the process so a 10-dataset suite pays the
    probe once rather than once per dataset. That cache is shared state: without this reset a test
    that primed it with a fake build would silently satisfy a later test expecting a probe failure,
    making results depend on test ORDER.
    """
    from studies.external_benchmarks import runner as _runner

    _runner._METAGRAPH_CACHE = None
    yield
    _runner._METAGRAPH_CACHE = None


@pytest.fixture
def hajjar_config():
    return HAJJAR


@pytest.fixture
def raw_hajjar_df():
    """A tiny stand-in for the Hajjar supplement table (raw column names).

    Five rows exercising the meaningful cases: a clean row, a row where the predicted
    ChEBI will differ from gold but share connectivity, a wrong-connectivity row, a row
    with no gold InChIKey (no-structure), and a row with SMILES for the RDKit check.
    """
    return pd.DataFrame(
        {
            "Metabolite name": ["D-Glucose", "L-Alanine", "Caffeine", "Mystery lipid", "Ethanol"],
            "ChEBI ID": ["CHEBI:4167", "CHEBI:16977", "CHEBI:27732", "CHEBI:99999", "CHEBI:16236"],
            "InChIKey": [
                "WQZGKKKJIJFFOK-GASJEMHNSA-N",  # glucose
                "QNAYBMKLOCPYGJ-REOHCLBHSA-N",  # L-alanine
                "RYYVLZVUVIJVGH-UHFFFAOYSA-N",  # caffeine
                "",  # no gold structure
                "LFQSCWFLJHTTHZ-UHFFFAOYSA-N",  # ethanol
            ],
            "SMILES": [
                "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
                "C[C@@H](C(=O)O)N",
                "Cn1cnc2c1c(=O)n(C)c(=O)n2C",
                "",
                "CCO",
            ],
        }
    )


class FakeOracle:
    """Test double for the KG structure oracle.

    ``kg_block`` returns the InChIKey first-block from the KG record only (None if the KG
    has no structure). ``resolved_block`` additionally consults the name fallback. The gap
    between them is exactly the fallback-segregation signal the scorer flags.
    """

    def __init__(self, kg_blocks: dict[str, str | None], fallback_blocks: dict[str, str | None] | None = None):
        self._kg = kg_blocks
        self._fb = fallback_blocks or {}

    def kg_block(self, node_id):
        return self._kg.get(node_id)

    def resolved_block(self, node_id):
        b = self._kg.get(node_id)
        if b is not None:
            return b
        return self._fb.get(node_id)


@pytest.fixture
def fake_oracle_factory():
    return FakeOracle
