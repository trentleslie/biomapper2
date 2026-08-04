"""Live orchestrator: acquire -> arms(0,1,3) -> score -> shuffled control -> save.

Save-by-default (institutional artifact-hygiene SOP): every arm's full output,
the seed, the dataset/KEGG SHAs, the biomapper2 commit, the KG snapshot sentinels,
and the interpreter model are persisted to a timestamped directory. --out is an
override, not the only way to save. This module is the live driver; the stages it
calls are each unit-tested offline with fakes.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .adapters.suhre import load_suhre
from .arms import run_arm
from .config import SUHRE
from .gold import assert_known_answer
from .mess import make_messy
from .scorers.pathway_overlap import primary_metric
from .validate import MIN_VALID_GAP, shuffle_measurements, validity_gate


def default_run_dir(base: Path) -> Path:
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return base / f"northstar_e2e_{stamp}"


def _git_commit(repo_root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _arm_payload(res) -> dict:
    return {
        "arm": res.arm,
        "interpretation": {
            "ranked_pathways": list(res.interpretation.ranked_pathways),
            "disease_label": res.interpretation.disease_label,
        },
        "candidate_pathways": list(res.grounded.candidate_pathways),
        "provenance": res.grounded.provenance,
        "score": res.score,
    }


def orchestrate(
    *,
    mapper: Any,
    kestrel: Any,
    llm_fn: Callable[[str], dict],
    membership: dict,
    out_dir: Path | None = None,
    repo_root: Path | None = None,
    min_gap: float = MIN_VALID_GAP,
) -> dict:
    assert_known_answer()  # structural gate on A* before any run
    repo_root = repo_root or Path.cwd()
    out_dir = out_dir or default_run_dir(Path(__file__).parent / "runs")
    out_dir.mkdir(parents=True, exist_ok=True)

    bundle = load_suhre()
    clean_df = bundle.input_df
    messy = make_messy(clean_df, config=SUHRE)

    # Arms 0 / 1 / 3.
    arm_results = {}
    for arm in ("arm0_clean", "arm1_product", "arm3_oracle"):
        res = run_arm(
            arm,
            clean_df=clean_df,
            messy_result=messy,
            config=SUHRE,
            mapper=mapper,
            kestrel=kestrel,
            membership=membership,
            llm_fn=llm_fn,
        )
        arm_results[arm] = res
        (out_dir / f"{arm}.json").write_text(json.dumps(_arm_payload(res), indent=2))

    # Shuffled-annotation negative control (re-run Arm 1 with permuted directions).
    shuffled = shuffle_measurements(messy, SUHRE, seed=SUHRE.mess_seed + 1)
    shuffled_res = run_arm(
        "arm1_product",
        clean_df=clean_df,
        messy_result=shuffled,
        config=SUHRE,
        mapper=mapper,
        kestrel=kestrel,
        membership=membership,
        llm_fn=llm_fn,
    )
    (out_dir / "arm1_shuffled.json").write_text(json.dumps(_arm_payload(shuffled_res), indent=2))

    real_metric = primary_metric(arm_results["arm1_product"].score)
    shuffled_metric = primary_metric(shuffled_res.score)
    validity = validity_gate(real_metric, shuffled_metric, min_gap=min_gap)
    (out_dir / "validity.json").write_text(json.dumps(asdict(validity), indent=2))

    manifest = {
        "dataset": SUHRE.key,
        "dataset_source_sha256": bundle.card["source_sha256"],
        "source_doi": SUHRE.source_doi,
        "mess_seed": SUHRE.mess_seed,
        "pathway_vocab": SUHRE.pathway_vocab,
        "interpreter_model": "claude-opus-4-8",
        "biomapper2_commit": _git_commit(repo_root),
        "kg_snapshot": os.getenv("KG_SNAPSHOT", "unrecorded"),
        "chebi_release": os.getenv("CHEBI_RELEASE", "unrecorded"),
        "timestamp_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    print(f"[northstar_e2e] results saved to {out_dir}")
    return {"out_dir": str(out_dir), "validity": asdict(validity), "manifest": manifest}


def main(argv: list[str] | None = None) -> None:
    """Live entry point: wires the real Mapper + Kestrel + Anthropic interpreter."""
    parser = argparse.ArgumentParser(description="North-star end-to-end slice (live run)")
    parser.add_argument("--out", type=Path, default=None, help="override output dir")
    args = parser.parse_args(argv)

    from biomapper2.mapper import Mapper

    from .grounding import LinkerKestrel
    from .interpret import anthropic_llm_fn
    from .kegg import load_membership

    mapper = Mapper()
    kestrel = LinkerKestrel(mapper.linker)
    membership = load_membership()
    orchestrate(
        mapper=mapper,
        kestrel=kestrel,
        llm_fn=anthropic_llm_fn,
        membership=membership,
        out_dir=args.out,
    )


if __name__ == "__main__":
    main()
