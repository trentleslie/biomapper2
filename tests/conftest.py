import pytest

from biomapper2 import utils
from biomapper2.mapper import Mapper
from biomapper2.utils import setup_logging

# Setup logging once for all tests
setup_logging()


@pytest.fixture(autouse=True)
def _reset_process_globals():
    """Clear every process-global in the client between tests.

    This tree had no autouse fixture at all, and the client is accumulating process-globals: the
    single lazily-built session, the per-endpoint request counters, and the one-shot credential
    warning. Shared state without a reset makes results depend on test ORDER -- a test that primes
    a session or a counter silently satisfies a later test that expected neither.
    """
    utils.reset_session()
    utils.reset_request_counters()
    yield
    utils.reset_session()
    utils.reset_request_counters()


@pytest.fixture(scope="session")
def shared_mapper():
    """
    Creates a session-scoped instantiation of Mapper that is created once per test run and shared across all
    pytest files.
    """
    mapper = Mapper()
    yield mapper
