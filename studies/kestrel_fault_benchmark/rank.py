"""Mechanical ranking and sensitivity analysis for Kestrel fault isolation competition.

Ranks candidates by:
1. worst_health_p99_ms (max across all runs, ascending)
2. hang_non_kestrel_rps (mean non-Kestrel throughput under hang, descending)
3. max_time_to_recover_s (max time to recover in recovering mode, ascending)
4. src_diff_lines (total diff lines in src/biomapper2 vs shared-base, ascending)

Supports --verify to independently validate ranking artifacts and --sensitivity to
verify leader stability across dropped modes.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MODES = ["healthy", "slow-30s", "hang", "50% 5xx", "recovering"]


def compute_src_diff_lines(worktree_path: Path, shared_base_sha: str) -> int:
    """Compute added + deleted lines in src/biomapper2 vs shared_base_sha."""
    try:
        cmd = ["git", "diff", "--numstat", f"{shared_base_sha}..HEAD", "--", "src/biomapper2"]
        out = subprocess.check_output(cmd, cwd=worktree_path, stderr=subprocess.DEVNULL).decode()
        total = 0
        for line in out.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2:
                added = int(parts[0]) if parts[0].isdigit() else 0
                deleted = int(parts[1]) if parts[1].isdigit() else 0
                total += added + deleted
        return total
    except Exception:
        return 0


def load_summaries(bench_root: Path) -> list[dict[str, Any]]:
    """Recursively discover and load all summary.json files under bench_root."""
    summaries: list[dict[str, Any]] = []
    for path in bench_root.glob("**/summary.json"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                data["_source_path"] = str(path)
                summaries.append(data)
        except Exception as exc:
            logger.warning("Failed to load %s: %s", path, exc)
    return summaries


def derive_candidate_metrics(
    runs: list[dict[str, Any]],
    worktree: Path | None,
    shared_base_sha: str,
    dropped_mode: str | None = None,
) -> dict[str, Any]:
    """Derive mechanical metric scores for a candidate."""
    filtered_runs = [r for r in runs if r.get("mode") != dropped_mode] if dropped_mode else list(runs)
    if not filtered_runs:
        return {}

    candidate = filtered_runs[0].get("candidate", "unknown")

    # 1. worst_health_p99_ms
    worst_p99 = max(r.get("health_p99_ms", 0.0) for r in filtered_runs)

    # 2. hang_non_kestrel_rps
    if dropped_mode == "hang":
        # When hang is dropped, use mean across remaining fault modes
        fault_runs = [r for r in filtered_runs if r.get("mode") != "healthy"]
        hang_rps = (
            sum(r.get("non_kestrel_rps", 0.0) for r in fault_runs) / max(1, len(fault_runs))
            if fault_runs
            else 0.0
        )
    else:
        hang_runs = [r for r in filtered_runs if r.get("mode") == "hang"]
        hang_rps = (
            sum(r.get("non_kestrel_rps", 0.0) for r in hang_runs) / max(1, len(hang_runs))
            if hang_runs
            else 0.0
        )

    # 3. max_time_to_recover_s
    if dropped_mode == "recovering":
        max_recover_s = 0.0
    else:
        rec_runs = [r for r in filtered_runs if r.get("mode") == "recovering"]
        max_recover_s = (
            max(r.get("time_to_recover_s") or 0.0 for r in rec_runs) if rec_runs else 0.0
        )

    # 4. src_diff_lines
    src_diff = compute_src_diff_lines(worktree, shared_base_sha) if worktree else 0

    return {
        "candidate": candidate,
        "run_count": len(filtered_runs),
        "worst_health_p99_ms": round(worst_p99, 1),
        "hang_non_kestrel_rps": round(hang_rps, 1),
        "max_time_to_recover_s": round(max_recover_s, 1),
        "src_diff_lines": src_diff,
    }


def compute_ranking(
    bench_root: Path,
    shared_base_sha: str,
    worktrees: dict[str, Path],
    dropped_mode: str | None = None,
) -> list[dict[str, Any]]:
    """Compute mechanical ranking across all candidates."""
    all_runs = load_summaries(bench_root)
    by_candidate: dict[str, list[dict[str, Any]]] = {}
    for r in all_runs:
        cand = r.get("candidate", "unknown")
        by_candidate.setdefault(cand, []).append(r)

    metrics_list: list[dict[str, Any]] = []
    for cand, runs in by_candidate.items():
        wt = worktrees.get(cand)
        m = derive_candidate_metrics(runs, wt, shared_base_sha, dropped_mode=dropped_mode)
        if m:
            metrics_list.append(m)

    # Rank key: worst_p99 asc, hang_rps desc, max_recover asc, src_diff asc
    def sort_key(item: dict[str, Any]) -> tuple[float, float, float, int, str]:
        return (
            item["worst_health_p99_ms"],
            -item["hang_non_kestrel_rps"],
            item["max_time_to_recover_s"],
            item["src_diff_lines"],
            item["candidate"],
        )

    metrics_list.sort(key=sort_key)
    for rank_idx, item in enumerate(metrics_list, start=1):
        item["rank"] = rank_idx

    return metrics_list


def run_sensitivity_check(
    bench_root: Path,
    shared_base_sha: str,
    worktrees: dict[str, Path],
    baseline_leader: str,
) -> tuple[bool, dict[str, str]]:
    """Check if leader changes when dropping any single mode."""
    dropped_leaders: dict[str, str] = {}
    stable = True

    for mode in MODES:
        sub_rank = compute_ranking(bench_root, shared_base_sha, worktrees, dropped_mode=mode)
        sub_leader = sub_rank[0]["candidate"] if sub_rank else "none"
        dropped_leaders[mode] = sub_leader
        if sub_leader != baseline_leader:
            stable = False

    return stable, dropped_leaders


def main() -> None:
    """CLI entrypoint for mechanical ranker."""
    parser = argparse.ArgumentParser(description="Mechanical Ranking & Sensitivity Analysis")
    parser.add_argument("bench_root", help="Root directory containing benchmark runs")
    parser.add_argument("--shared-base-sha", required=True, help="Git SHA of feat/kestrel-fault-shared-base")
    parser.add_argument(
        "--worktrees",
        default="",
        help="Comma-separated cand=path pairs (e.g. team-a=pathA,team-b=pathB)",
    )
    parser.add_argument("--out", default=None, help="Output path for ranking JSON")
    parser.add_argument("--verify", default=None, help="Path to existing ranking JSON to verify")
    parser.add_argument("--sensitivity", action="store_true", help="Run drop-one-mode sensitivity analysis")
    args = parser.parse_args()

    bench_root = Path(args.bench_root).resolve()
    worktrees: dict[str, Path] = {}
    if args.worktrees:
        for pair in args.worktrees.split(","):
            if "=" in pair:
                cand, p = pair.split("=", 1)
                worktrees[cand.strip()] = Path(p.strip()).resolve()

    ranking = compute_ranking(bench_root, args.shared_base_sha, worktrees)
    leader = ranking[0]["candidate"] if ranking else "none"

    output_dict: dict[str, Any] = {
        "leader": leader,
        "ranking": ranking,
    }

    if args.sensitivity:
        stable, per_dropped = run_sensitivity_check(bench_root, args.shared_base_sha, worktrees, leader)
        output_dict["leader_stable"] = stable
        output_dict["sensitivity_dropped_mode_leaders"] = per_dropped

    if args.out:
        out_path = Path(args.out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output_dict, f, indent=2)

    if args.verify:
        verify_path = Path(args.verify).resolve()
        if not verify_path.exists():
            print(f"Verify file not found: {verify_path}", file=sys.stderr)
            sys.exit(1)
        with open(verify_path, "r", encoding="utf-8") as f:
            existing = json.load(f)

        existing_norm = json.dumps(existing, sort_keys=True)
        current_norm = json.dumps(output_dict, sort_keys=True)
        if existing_norm == current_norm:
            print("VERIFIED: Ranking output is identical to existing artifact.")
            sys.exit(0)
        else:
            print("FAILED: Ranking mismatch with existing artifact.", file=sys.stderr)
            sys.exit(1)

    print(json.dumps(output_dict, indent=2))
    if args.sensitivity and not output_dict.get("leader_stable", True):
        sys.exit(2)


if __name__ == "__main__":
    main()
