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
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logger = logging.getLogger(__name__)

MODES = ["healthy", "slow-30s", "hang", "50% 5xx", "recovering"]
PENALTY_SCORE = 999999.0


def compute_src_diff_lines(
    worktree_path: Path | None,
    shared_base_sha: str,
    candidate_sha: str,
) -> int:
    """Compute added + deleted lines in src/biomapper2 for shared_base_sha..candidate_sha."""
    if worktree_path is None or not worktree_path.is_dir():
        raise ValueError(f"Valid candidate worktree directory is required, got: {worktree_path}")
    if not shared_base_sha or not candidate_sha or candidate_sha == "unknown":
        raise ValueError(
            f"Valid shared_base_sha and candidate git_sha are required, got {shared_base_sha!r}..{candidate_sha!r}"
        )

    cmd = ["git", "diff", "--numstat", f"{shared_base_sha}..{candidate_sha}", "--", "src/biomapper2"]
    try:
        proc = subprocess.run(cmd, cwd=worktree_path, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        stderr = getattr(exc, "stderr", "") or str(exc)
        raise ValueError(
            f"Failed git diff in {worktree_path} for {shared_base_sha}..{candidate_sha}: {stderr.strip()}"
        ) from exc

    total = 0
    for line in proc.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            if not parts[0].isdigit() or not parts[1].isdigit():
                raise ValueError(f"Non-numeric diff stat in src/biomapper2: {line!r}")
            total += int(parts[0]) + int(parts[1])
    return total


def load_summaries(bench_root: Path) -> list[dict[str, Any]]:
    """Recursively discover and load all summary.json files under bench_root."""
    summaries: list[dict[str, Any]] = []
    for path in sorted(bench_root.glob("**/summary.json")):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"Invalid summary object in {path}")
        data["_source_path"] = str(path)
        summaries.append(data)
    return summaries


def _validate_and_extract_run_coverage(
    candidate: str,
    runs: list[dict[str, Any]],
    expected_modes: list[str],
) -> tuple[str, set[tuple[str, int]], dict[str, Any]]:
    """Validate commit identity, mode/seed completeness, config consistency, and measurements."""
    if not runs:
        raise ValueError(f"Candidate {candidate!r} has no benchmark runs")

    git_shas = {r.get("git_sha") for r in runs}
    if len(git_shas) != 1:
        raise ValueError(f"Candidate {candidate!r} has mixed git_sha values across runs: {sorted(map(str, git_shas))}")
    candidate_sha = next(iter(git_shas))
    if not isinstance(candidate_sha, str) or not candidate_sha or candidate_sha == "unknown":
        raise ValueError(f"Candidate {candidate!r} has missing or unknown git_sha: {candidate_sha!r}")

    configs = [r.get("config") for r in runs]
    if any(not isinstance(cfg, dict) for cfg in configs):
        raise ValueError(f"Candidate {candidate!r} has runs missing fault config settings")
    first_cfg = configs[0]
    for cfg in configs[1:]:
        if cfg != first_cfg:
            raise ValueError(f"Candidate {candidate!r} has mismatched fault configs across runs: {first_cfg} vs {cfg}")

    seeds_by_mode: dict[str, list[int]] = {}
    pairs: set[tuple[str, int]] = set()
    for r in runs:
        mode = r.get("mode")
        seed = r.get("seed")
        if mode not in MODES:
            raise ValueError(f"Candidate {candidate!r} has unknown mode {mode!r}")
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise ValueError(f"Candidate {candidate!r} has invalid seed {seed!r} in mode {mode!r}")
        if mode not in expected_modes:
            continue
        pair = (mode, seed)
        if pair in pairs:
            raise ValueError(f"Candidate {candidate!r} has duplicate run for mode={mode!r}, seed={seed}")
        pairs.add(pair)
        seeds_by_mode.setdefault(mode, []).append(seed)

    missing_modes = [m for m in expected_modes if m not in seeds_by_mode]
    if missing_modes:
        raise ValueError(f"Candidate {candidate!r} is missing required mode(s): {missing_modes}")

    reference_seeds = set(seeds_by_mode[expected_modes[0]])
    if not reference_seeds:
        raise ValueError(f"Candidate {candidate!r} has empty seed set")
    for m in expected_modes[1:]:
        if set(seeds_by_mode[m]) != reference_seeds:
            raise ValueError(
                f"Candidate {candidate!r} has mismatched seeds between {expected_modes[0]!r} "
                f"({sorted(reference_seeds)}) and {m!r} ({sorted(seeds_by_mode[m])})"
            )

    assert isinstance(first_cfg, dict)
    return candidate_sha, pairs, first_cfg


def _effective_health_p99(run: dict[str, Any], candidate: str) -> float:
    p99 = run.get("health_p99_ms")
    total = run.get("health_total_count")
    ok = run.get("health_ok_count")
    if not isinstance(p99, (int, float)) or math.isnan(p99) or p99 < 0.0:
        raise ValueError(f"Candidate {candidate!r} has invalid health_p99_ms={p99!r}")
    if not isinstance(total, int) or total <= 0 or not isinstance(ok, int):
        raise ValueError(f"Candidate {candidate!r} has invalid health probe counts: ok={ok!r}, total={total!r}")
    if ok < total:
        return max(float(p99), PENALTY_SCORE)
    return float(p99)


def _effective_recovery_time(run: dict[str, Any], candidate: str) -> float:
    recovered = run.get("recovered")
    ttr = run.get("time_to_recover_s")
    if recovered is False:
        return PENALTY_SCORE
    if not isinstance(ttr, (int, float)) or math.isnan(ttr) or ttr < 0.0:
        raise ValueError(
            f"Candidate {candidate!r} recovering run is missing valid time_to_recover_s (got {ttr!r})"
        )
    return float(ttr)


def derive_candidate_metrics(
    runs: list[dict[str, Any]],
    worktree: Path | None,
    shared_base_sha: str,
    dropped_mode: str | None = None,
) -> dict[str, Any]:
    """Derive validated mechanical metric scores for a single candidate."""
    if not runs:
        raise ValueError("Cannot derive candidate metrics from empty run list")

    candidate = str(runs[0].get("candidate") or "unknown")
    expected_modes = [m for m in MODES if m != dropped_mode]
    candidate_sha, _, _ = _validate_and_extract_run_coverage(candidate, runs, expected_modes)

    filtered_runs = [r for r in runs if r.get("mode") != dropped_mode] if dropped_mode else list(runs)

    # 1. worst_health_p99_ms
    worst_p99 = max(_effective_health_p99(r, candidate) for r in filtered_runs)

    # 2. hang_non_kestrel_rps
    for r in filtered_runs:
        rps = r.get("non_kestrel_rps")
        if not isinstance(rps, (int, float)) or math.isnan(rps) or rps < 0.0:
            raise ValueError(f"Candidate {candidate!r} has invalid non_kestrel_rps={rps!r}")

    if dropped_mode == "hang":
        fault_runs = [r for r in filtered_runs if r.get("mode") != "healthy"]
        if not fault_runs:
            raise ValueError(f"Candidate {candidate!r} has no remaining fault runs when dropping hang")
        hang_rps = sum(float(r["non_kestrel_rps"]) for r in fault_runs) / len(fault_runs)
    else:
        hang_runs = [r for r in filtered_runs if r.get("mode") == "hang"]
        if not hang_runs:
            raise ValueError(f"Candidate {candidate!r} has no hang runs")
        hang_rps = sum(float(r["non_kestrel_rps"]) for r in hang_runs) / len(hang_runs)

    # 3. max_time_to_recover_s
    if dropped_mode == "recovering":
        max_recover_s = 0.0
    else:
        rec_runs = [r for r in filtered_runs if r.get("mode") == "recovering"]
        if not rec_runs:
            raise ValueError(f"Candidate {candidate!r} has no recovering runs")
        max_recover_s = max(_effective_recovery_time(r, candidate) for r in rec_runs)

    # 4. src_diff_lines (measured against pinned candidate_sha, never mutable HEAD)
    src_diff = compute_src_diff_lines(worktree, shared_base_sha, candidate_sha)

    return {
        "candidate": candidate,
        "git_sha": candidate_sha,
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
    """Compute mechanical ranking across all candidates after cross-candidate validation."""
    all_runs = load_summaries(bench_root)
    if not all_runs:
        raise ValueError(f"No summary.json files found under {bench_root}")

    by_candidate: dict[str, list[dict[str, Any]]] = {}
    for r in all_runs:
        cand = str(r.get("candidate") or "").strip()
        if not cand:
            raise ValueError(f"Run summary missing candidate name: {r.get('_source_path')}")
        by_candidate.setdefault(cand, []).append(r)

    if worktrees:
        missing_cands = sorted(set(worktrees) - set(by_candidate))
        if missing_cands:
            raise ValueError(f"Candidate(s) missing all benchmark runs under {bench_root}: {missing_cands}")

    expected_modes = [m for m in MODES if m != dropped_mode]
    reference_pairs: set[tuple[str, int]] | None = None
    reference_cfg: dict[str, Any] | None = None
    reference_cand: str | None = None

    metrics_list: list[dict[str, Any]] = []
    for cand in sorted(by_candidate):
        runs = by_candidate[cand]
        _, pairs, cfg = _validate_and_extract_run_coverage(cand, runs, expected_modes)
        if reference_pairs is None:
            reference_pairs = pairs
            reference_cfg = cfg
            reference_cand = cand
        else:
            if pairs != reference_pairs:
                raise ValueError(
                    f"Mode/seed coverage mismatch between {reference_cand!r} and {cand!r}: "
                    f"{sorted(reference_pairs)} vs {sorted(pairs)}"
                )
            if cfg != reference_cfg:
                raise ValueError(
                    f"Fault config mismatch between {reference_cand!r} ({reference_cfg}) and {cand!r} ({cfg})"
                )

        wt = worktrees.get(cand)
        metrics_list.append(derive_candidate_metrics(runs, wt, shared_base_sha, dropped_mode=dropped_mode))

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
    # Ensure full 5-mode coverage is valid before dropping individual modes
    compute_ranking(bench_root, shared_base_sha, worktrees, dropped_mode=None)

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

    out_path = Path(args.out).resolve() if args.out else None
    verify_path = Path(args.verify).resolve() if args.verify else None
    if out_path is not None and verify_path is not None and out_path == verify_path:
        parser.error("--out and --verify must not point to the same file")

    existing_verify_data: dict[str, Any] | None = None
    if verify_path is not None:
        if not verify_path.exists():
            print(f"Verify file not found: {verify_path}", file=sys.stderr)
            sys.exit(1)
        with open(verify_path, "r", encoding="utf-8") as f:
            existing_verify_data = json.load(f)

    bench_root = Path(args.bench_root).resolve()
    worktrees: dict[str, Path] = {}
    if args.worktrees:
        for pair in args.worktrees.split(","):
            if "=" in pair:
                cand, p = pair.split("=", 1)
                worktrees[cand.strip()] = Path(p.strip()).resolve()

    try:
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
    except ValueError as exc:
        print(f"RANKING VALIDATION ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if existing_verify_data is not None:
        existing_norm = json.dumps(existing_verify_data, sort_keys=True)
        current_norm = json.dumps(output_dict, sort_keys=True)
        if existing_norm != current_norm:
            print("FAILED: Ranking mismatch with existing artifact.", file=sys.stderr)
            sys.exit(1)
        if out_path is not None:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(output_dict, f, indent=2)
        print("VERIFIED: Ranking output is identical to existing artifact.")
        sys.exit(0)

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output_dict, f, indent=2)

    print(json.dumps(output_dict, indent=2))
    if args.sensitivity and not output_dict.get("leader_stable", True):
        sys.exit(2)


if __name__ == "__main__":
    main()
