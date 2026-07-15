"""Scripted HTTP fakes for the competitor tests — the suite NEVER hits a live API.

``ScriptedTransport`` records every call and delegates to a handler that returns an
``HttpResponse``. A handler may be a fixed response, a url-dispatch dict, or a stateful callable
(used for the UniProt run/poll/results sequence).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from studies.external_benchmarks.competitors.base import HttpResponse


class ScriptedTransport:
    """A fake ``HttpTransport`` driven by a handler ``(method, url, **kwargs) -> HttpResponse``."""

    def __init__(self, handler: Callable[..., HttpResponse]) -> None:
        self._handler = handler
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> HttpResponse:
        self.calls.append((method, url, kwargs))
        return self._handler(method, url, **kwargs)

    @property
    def n_calls(self) -> int:
        return len(self.calls)


def json_response(body: Any, *, status: int = 200, headers: dict[str, str] | None = None) -> HttpResponse:
    return HttpResponse(status_code=status, headers=headers or {}, json_body=body)


def fixed(body: Any, *, status: int = 200, headers: dict[str, str] | None = None) -> Callable[..., HttpResponse]:
    """Handler that always returns the same response."""

    def _h(method: str, url: str, **kwargs: Any) -> HttpResponse:
        return json_response(body, status=status, headers=headers)

    return _h


def no_sleep(_seconds: float) -> None:
    """Injectable sleep that never blocks the test suite."""
    return None
