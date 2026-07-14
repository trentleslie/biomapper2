"""Orchestration entry: gate -> acquire -> run -> score -> verify -> validate -> figure -> report.

Wires the real Mapper + StructureResolver. This module is the live driver; it is NOT
exercised by the offline unit suite (it needs Kestrel + network). The individual stages it
calls are each unit-tested in isolation with fakes/fixtures.

Ordering guarantees (fail-closed):
  1. Unit 0 gate MUST pass before any full run touches real data.
  2. Reconciliation (verify) AND validation MUST pass before figures are generated.
  3. The report is internal only — /publish-wiki is never invoked here (R7).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path
from typing import Any

from .config import HAJJAR, HAJJAR_COMPETITORS, DatasetConfig


def default_run_dir(config: DatasetConfig, base: Path) -> Path:
    """Timestamped, save-by-default output dir (institutional artifact-hygiene SOP)."""
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return base / f"{config.key}_{stamp}"


def orchestrate(
    *,
    source: bytes | str,
    config: DatasetConfig = HAJJAR,
    out_dir: Path | None = None,
    repo_root: Path | None = None,
    published_parity_cell: tuple[float, float, float] | None = None,
    run_gate_first: bool = True,
) -> dict[str, Any]:
    """Run the full pipeline live. Imports heavy deps lazily so offline tests can import
    this module without constructing a Mapper.
    """
    from biomapper2.core.structure_resolver import StructureResolver
    from biomapper2.mapper import Mapper

    from .adapters.hajjar import load_hajjar, parse_raw
    from .figures.competitor_panel import render_s2
    from .figures.vocab_bar import render_s1
    from .gate import build_live_smoke_fn, run_gate
    from .oracle import KGStructureOracle
    from .report.assemble import assemble_report
    from .runner import run_all
    from .scorers.paper_metric import score_paper_metric
    from .scorers.structure_oracle_scorer import score_structure_oracle
    from .validate import validate_all
    from .verify import reconcile

    repo_root = repo_root or Path.cwd()
    out_dir = out_dir or default_run_dir(config, Path(__file__).parent / "runs")
    out_dir.mkdir(parents=True, exist_ok=True)

    mapper = Mapper()

    # 1. Unit 0 gate — must pass before touching real data.
    if run_gate_first:
        gate_result = run_gate(build_live_smoke_fn(mapper), n_rows=100)
        (out_dir / "gate_result.json").write_text(
            json.dumps({"verdict": gate_result.verdict, "reason": gate_result.reason}, indent=2)
        )
        if not gate_result.passed:
            raise RuntimeError(f"Phase-0 gate stopped the run: {gate_result.reason}")

    # 2. Acquire.
    bundle = load_hajjar(source, config)
    source_df = parse_raw(source) if isinstance(source, bytes) else None
    (out_dir / "dataset_card.json").write_text(json.dumps(bundle.card, indent=2))

    # 3. Run per vocab.
    runs = run_all(
        mapper, bundle.input_df, config, out_dir, dataset_sha=bundle.card["source_sha256"], repo_root=repo_root
    )

    # 4. Score + reconcile per successful vocab.
    oracle = KGStructureOracle(StructureResolver(mapper.linker), mapper.linker)
    import pandas as pd

    per_vocab_struct: dict[str, Any] = {}
    per_vocab_paper: dict[str, Any] = {}
    reconciliation_ok = True
    for vocab, vr in runs.items():
        if not vr.ok or not vr.output_tsv:
            continue
        mapped_df = pd.read_csv(vr.output_tsv, sep="\t")
        struct = score_structure_oracle(mapped_df, config, oracle, vocab=vocab)
        paper = score_paper_metric(mapped_df, config, vocab=vocab)
        per_vocab_struct[vocab] = struct
        per_vocab_paper[vocab] = paper
        rec = reconcile({"structure": struct, "paper": paper}, mapped_df, config, oracle)
        reconciliation_ok = reconciliation_ok and rec.passed
        (out_dir / f"{vocab}_results.json").write_text(json.dumps({"structure": struct, "paper": paper}, indent=2))
    if not reconciliation_ok:
        raise RuntimeError("Reconciliation failed — refusing to generate figures/report.")

    # 5. Validate primary vocab (external-anchor checks + protocol-parity gate).
    primary = config.target_vocabs[0]
    primary_tsv = runs[primary].output_tsv if primary in runs else None
    if primary in per_vocab_struct and source_df is not None and primary_tsv is not None:
        primary_df = pd.read_csv(primary_tsv, sep="\t")
        vrep = validate_all(
            input_df=bundle.input_df,
            source_df=source_df,
            mapped_df=primary_df,
            results={"structure": per_vocab_struct[primary]},
            config=config,
            oracle=oracle,
            competitors=HAJJAR_COMPETITORS,
            protocol_parity=published_parity_cell,
        )
        if not vrep.passed:
            raise RuntimeError(f"Validation failed — refusing figures/report: {vrep.failures}")
        validation_ok = vrep.passed
    else:
        validation_ok = False

    # 6. Figures (only after verify + validate pass).
    s1 = render_s1(per_vocab_struct, out_dir / "S1_vocab_bar.png", input_type=config.input_type)
    primary_top1 = per_vocab_struct[primary]["comparable_core"]["top1_accuracy"] or 0.0
    s2 = render_s2(primary_top1, HAJJAR_COMPETITORS, out_dir / "S2_competitor_panel.png")

    # 7. Internal report (NO wiki publish).
    report_path = out_dir / f"{config.key}_report.md"
    assemble_report(
        config=config,
        per_vocab_results=per_vocab_struct,
        paper_metrics=per_vocab_paper,
        competitors=HAJJAR_COMPETITORS,
        figure_paths={"S1": s1["figure"], "S2": s2["figure"]},
        integrity={
            "reconciliation_passed": reconciliation_ok,
            "validation_passed": validation_ok,
            "protocol_parity": published_parity_cell,
        },
        out_path=report_path,
    )
    return {"out_dir": str(out_dir), "report": str(report_path), "runs": list(runs.keys())}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Hajjar external-benchmark slice (live).")
    parser.add_argument("--supplement", required=True, help="path/URL to the Hajjar supplement")
    parser.add_argument("--out", default=None, help="override output dir (default: timestamped runs/)")
    parser.add_argument("--no-gate", action="store_true", help="skip the Phase-0 gate (NOT recommended)")
    args = parser.parse_args()

    src: bytes | str
    p = Path(args.supplement)
    if p.exists():
        src = p.read_bytes()
    else:
        src = args.supplement  # treated as URL
    out = Path(args.out) if args.out else None
    result = orchestrate(source=src, out_dir=out, run_gate_first=not args.no_gate)
    print(f"Saved run to {result['out_dir']}; report at {result['report']}")


if __name__ == "__main__":
    main()
