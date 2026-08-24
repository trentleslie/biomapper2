import importlib.util
from pathlib import Path

import pytest

# Load the script module directly — it lives in scripts/, not the package.
_SPEC = importlib.util.spec_from_file_location(
    "report_to_summary", Path(__file__).resolve().parents[1] / "scripts" / "report_to_summary.py"
)
assert _SPEC and _SPEC.loader
report_to_summary = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(report_to_summary)


def _report(kg_version: str = "2026.06.0", failed: int = 0) -> dict:
    return {
        "metadata": {
            "biomapper2_version": "0.1.0",
            "kestrel_version": "0.4.1",
            "kestrel_url": "https://kestrel.example/api",
            "run_timestamp": "2026-06-16T20:20:48+00:00",
            "kg_build": {"kg_version": kg_version, "git_commit": "a1b9f3c", "sources": ["kg2", "spoke"]},
            "git_commit": "deadbeef",
            "tag": "ci-live",
        },
        "test_counts": {"passed": 208, "failed": failed, "error": 0, "skipped": 1},
        "performance": {},
    }


@pytest.mark.unit
def test_render_pass_shows_provenance_and_pass_status():
    md = report_to_summary.render(_report())
    assert "✅ pass" in md
    assert "208 passed" in md
    assert "`2026.06.0`" in md  # KG version surfaced
    assert "kg2, spoke" in md  # sources surfaced


@pytest.mark.unit
def test_render_failure_shows_fail_status():
    md = report_to_summary.render(_report(failed=3))
    assert "❌ fail" in md
    assert "3 failed" in md


@pytest.mark.unit
def test_render_flags_degraded_unknown_metadata():
    md = report_to_summary.render(_report(kg_version="unknown"))
    assert "KG build metadata unavailable" in md


@pytest.mark.unit
def test_newest_report_returns_none_when_empty(tmp_path):
    assert report_to_summary.newest_report(str(tmp_path)) is None
