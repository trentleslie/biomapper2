"""Unit tests for Kestrel fault isolation and transport resilience mechanisms."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from biomapper2.provenance import fetch_kg_build_info
from biomapper2.utils import (
    CircuitBreaker,
    get_current_api_context,
    get_session,
    kestrel_request,
    reset_api_context,
    reset_circuit_breaker,
    reset_session,
    set_api_context,
)


@pytest.mark.unit
def test_circuit_breaker_trips_and_fast_fails() -> None:
    """Circuit breaker opens after reaching failure threshold and rejects further attempts."""
    threshold = 3
    cooldown = 10.0
    breaker = CircuitBreaker(failure_threshold=threshold, cooldown_s=cooldown)

    assert breaker.can_attempt() is True
    for _ in range(threshold - 1):
        breaker.record_failure()
        assert breaker.can_attempt() is True

    breaker.record_failure()
    assert breaker.can_attempt() is False


@pytest.mark.unit
def test_circuit_breaker_half_open_probe_and_recovery() -> None:
    """Circuit breaker allows single probe after cooldown and recovers on success."""
    breaker = CircuitBreaker(failure_threshold=2, cooldown_s=0.05)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.can_attempt() is False

    time.sleep(0.08)
    assert breaker.can_attempt() is True
    breaker.record_success()
    assert breaker.state == "closed"
    assert breaker.can_attempt() is True


@pytest.mark.unit
def test_thread_local_session_isolation() -> None:
    """Requests sessions are distinct per thread and cleared completely by reset_session."""
    session_ids: set[int] = set()
    lock = threading.Lock()

    def worker() -> None:
        sess = get_session()
        with lock:
            session_ids.add(id(sess))

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(session_ids) == 2
    reset_session()


@pytest.mark.unit
def test_api_request_context_propagation_and_timeout_override() -> None:
    """ApiRequestContext configures timeout settings and resets cleanly via token."""
    assert get_current_api_context() is None

    token = set_api_context(timeout_s=1.5, max_retries=0)
    try:
        ctx = get_current_api_context()
        assert ctx is not None
        assert ctx.timeout_s == 1.5
        assert ctx.max_retries == 0
    finally:
        reset_api_context(token)

    assert get_current_api_context() is None


@pytest.mark.unit
def test_kestrel_request_fast_retry_on_5xx() -> None:
    """kestrel_request performs fast retry on server error when API context is active."""
    token = set_api_context(timeout_s=1.0, max_retries=1, retry_backoff_base=0.01)
    call_count = 0

    def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.status_code = 500
        resp.text = "Internal Server Error"
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
        return resp

    reset_circuit_breaker()
    try:
        with patch("biomapper2.utils.get_session") as mock_get_sess:
            mock_sess = MagicMock()
            mock_sess.request.side_effect = mock_post
            mock_get_sess.return_value = mock_sess

            with pytest.raises(requests.HTTPError):
                kestrel_request(
                    method="POST",
                    endpoint="test-endpoint",
                    batch_field="items",
                    batch_items=["item1"],
                    batch_size=1,
                    json={},
                )

        assert call_count == 2
    finally:
        reset_api_context(token)
        reset_circuit_breaker()


@pytest.mark.unit
def test_provenance_fetch_kg_build_info_degrades_gracefully_under_fault() -> None:
    """fetch_kg_build_info falls back to unknown build info without raising exceptions."""
    token = set_api_context(timeout_s=0.5, max_retries=0)
    try:
        with patch("biomapper2.provenance.requests.get", side_effect=requests.Timeout("Mock hang")):
            raw_info, info = fetch_kg_build_info("http://127.0.0.1:9999")
            assert raw_info == "unknown"
            assert info.kg_version == "unknown"
            assert info.biolink_version == "unknown"
    finally:
        reset_api_context(token)
