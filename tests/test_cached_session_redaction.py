"""Every ``requests_cache.CachedSession`` construction site under ``src/`` must pass
``ignored_parameters=CACHE_IGNORED_PARAMETERS``.

``requests_cache`` redacts a default list of secret-ish parameter names, but matches them
case-sensitively, so a site that omits the explicit list will persist an API key or Authorization
header in cleartext into the on-disk cache (the Kestrel incident,
docs/solutions/security-issues/kestrel-api-key-persisted-in-cleartext-to-http-cache-2026-08-05.md).
This is a static AST guard so a fifth site cannot silently reintroduce the leak. The at-rest byte
check for the Kestrel session lives in ``test_kestrel_auth_header.py``; this test covers the
enumeration of construction sites.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "biomapper2"


def _cached_session_calls() -> list[tuple[Path, ast.Call]]:
    """Every call whose callee name is ``CachedSession`` (direct or attribute) under ``src/``.

    A ``class Foo(requests_cache.CachedSession)`` base is a ClassDef, not a Call, so subclass
    definitions are not flagged. Subclass instantiations (a different callee name) are covered by
    their own construction site.
    """
    calls: list[tuple[Path, ast.Call]] = []
    for py in SRC_ROOT.rglob("*.py"):
        tree = ast.parse(py.read_text(), filename=str(py))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
            if name == "CachedSession":
                calls.append((py, node))
    return calls


def test_at_least_one_cached_session_site_is_scanned() -> None:
    """Guard the guard: if the enumeration finds nothing, the test would pass vacuously."""
    assert _cached_session_calls(), "no CachedSession construction sites found under src/biomapper2"


def test_every_cached_session_passes_ignored_parameters() -> None:
    offenders: list[str] = []
    for py, node in _cached_session_calls():
        kw = {k.arg: k.value for k in node.keywords}
        value = kw.get("ignored_parameters")
        rel = py.relative_to(SRC_ROOT.parents[1])
        if value is None:
            offenders.append(f"{rel}:{node.lineno} missing ignored_parameters")
        elif not (isinstance(value, ast.Name) and value.id == "CACHE_IGNORED_PARAMETERS"):
            offenders.append(f"{rel}:{node.lineno} ignored_parameters is not CACHE_IGNORED_PARAMETERS")
    assert not offenders, "CachedSession sites persist credentials in cleartext:\n" + "\n".join(offenders)
