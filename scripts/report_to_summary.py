#!/usr/bin/env python3
"""Render a biomapper2 test report (``reports/*.json``) as GitHub-flavored markdown.

CI uses this to funnel test outcome + run provenance into the GitHub Actions step
summary, so every run on the PR/run page shows *what passed and against which KG
build*. Reads the newest ``reports/*.json`` by default, or a path given as argv[1].
Prints markdown to stdout; CI appends it to ``$GITHUB_STEP_SUMMARY``.
"""

from __future__ import annotations

import glob
import json
import os
import sys


def newest_report(reports_dir: str = "reports") -> str | None:
    """Path to the most recently written report, or None if none exist."""
    reports = glob.glob(os.path.join(reports_dir, "*.json"))
    if not reports:
        return None
    return max(reports, key=os.path.getmtime)


def render(report: dict) -> str:
    """Render a report dict (metadata + test_counts + performance) as markdown."""
    meta = report.get("metadata", {})
    kg = meta.get("kg_build", {})
    counts = report.get("test_counts", {})
    perf = report.get("performance", {})

    passed = counts.get("passed", 0)
    failed = counts.get("failed", 0)
    error = counts.get("error", 0)
    skipped = counts.get("skipped", 0)
    status = "✅ pass" if (failed == 0 and error == 0) else "❌ fail"

    sources = kg.get("sources") or []
    lines = [
        "## biomapper2 test report",
        "",
        f"**Result:** {status} — {passed} passed, {failed} failed, {error} error, {skipped} skipped",
        "",
        "### Run provenance",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| biomapper2 | `{meta.get('biomapper2_version', '?')}` |",
        f"| kestrel | `{meta.get('kestrel_version', '?')}` |",
        f"| kestrel_url | {meta.get('kestrel_url', '?')} |",
        f"| KG version | `{kg.get('kg_version', '?')}` |",
        f"| KG build commit | `{kg.get('git_commit', '?')}` |",
        f"| KG sources | {', '.join(sources) if sources else '—'} |",
        f"| biomapper2 commit | `{meta.get('git_commit', '?')}` |",
        f"| tag | `{meta.get('tag', '?')}` |",
        f"| run timestamp | {meta.get('run_timestamp', '?')} |",
        "",
    ]

    if meta.get("kestrel_version") == "unknown" or kg.get("kg_version") == "unknown":
        lines += [
            "> ⚠️ KG build metadata unavailable (`unknown`) — the deployed Kestrel predates "
            "the `build_info` feature, or `/health` was unreachable.",
            "",
        ]

    if perf:
        lines += ["### Performance", "", "| Step | Metric | Value |", "| --- | --- | --- |"]
        for step, metrics in perf.items():
            if isinstance(metrics, dict):
                for metric, value in metrics.items():
                    lines.append(f"| {step} | {metric} | {value} |")
            else:
                lines.append(f"| {step} | | {metrics} |")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else newest_report()
    if not path or not os.path.exists(path):
        print("## biomapper2 test report\n\n_No report file found._")
        return 0
    with open(path) as f:
        report = json.load(f)
    print(render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
