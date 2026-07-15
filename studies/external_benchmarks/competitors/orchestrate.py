"""Live driver for the gene/protein competitor head-to-head (GATED — not run by the offline suite).

Mirrors ``run.orchestrate_backbone``: acquire the SAME backbone subsample, run BioMapper AND each
incumbent tool on those identical rows, score everyone with the identical ``curie_scorer``, and
write ``results.json`` (BioMapper vs each competitor). Heavy deps (Mapper, requests transport) are
imported lazily so this module imports offline; the pure pieces it calls are all unit-tested.

Save-by-default (artifact-hygiene SOP): outputs always land in a timestamped ``runs/`` dir;
``--out`` is an override, not the only way to save. This is a separate, gated step — do NOT invoke
it as part of building/testing the harness.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path
from typing import Any

from ..config import CURIE_REGISTRY, CurieDatasetConfig


def default_run_dir(config: CurieDatasetConfig, base: Path) -> Path:
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return base / f"{config.key}_competitors_{stamp}"


def build_default_clients(*, sleep=None) -> list:
    """Construct the three live competitor clients over a shared requests transport + rate limits.

    Conservative per-tool minimum intervals keep the hosted services happy; a shared in-memory
    cache de-dups identical batches within the run. No API keys are needed (see ACCESS_NOTES).
    """
    from .base import InMemoryCache, RateLimiter, RequestsTransport
    from .biodbnet import BioDBnetClient
    from .gconvert import GConvertClient
    from .uniprot_idmapping import UniProtIdMappingClient

    transport = RequestsTransport()
    cache = InMemoryCache()
    kw: dict[str, Any] = {"cache": cache}
    if sleep is not None:
        kw["sleep"] = sleep
    return [
        GConvertClient(transport, rate_limiter=RateLimiter(0.5), **kw),
        BioDBnetClient(transport, rate_limiter=RateLimiter(1.0), **kw),
        UniProtIdMappingClient(transport, rate_limiter=RateLimiter(1.0), **kw),
    ]


def orchestrate_competitors(
    *,
    config: CurieDatasetConfig,
    source,
    clients: list | None = None,
    out_dir: Path | None = None,
    repo_root: Path | None = None,
    run_gate_first: bool = True,
) -> dict[str, Any]:
    """Run BioMapper + competitors on one backbone's rows; write the head-to-head results.json."""
    import pandas as pd

    from biomapper2.mapper import Mapper

    from ..adapters.backbones import load_backbone, persist_subsample, resolve_source_version
    from ..runner import run_all
    from ..scorers.curie_scorer import score_curie
    from .headtohead import assemble_head_to_head
    from .runner import run_all_competitors, score_competitor_run, source_namespace_for

    repo_root = repo_root or Path.cwd()
    out_dir = out_dir or default_run_dir(config, Path(__file__).parent.parent / "runs")
    out_dir.mkdir(parents=True, exist_ok=True)

    mapper = Mapper()
    if run_gate_first:
        from ..gate import build_live_gene_protein_smoke_fn, run_gene_protein_gate

        gate_result = run_gene_protein_gate(build_live_gene_protein_smoke_fn(mapper))
        (out_dir / "gate_result.json").write_text(
            json.dumps({"verdict": gate_result.verdict, "reason": gate_result.reason}, indent=2)
        )
        if not gate_result.passed:
            raise RuntimeError(f"Gene/protein Phase-0 gate stopped the head-to-head: {gate_result.reason}")

    source_version = resolve_source_version(source) if isinstance(source, str) else None
    bundle = load_backbone(source, config, source_version=source_version)
    (out_dir / "dataset_card.json").write_text(json.dumps(bundle.card, indent=2))
    persist_subsample(bundle, out_dir)

    # 1. BioMapper on the primary vocab (its own run; the reference number in the head-to-head).
    primary = config.target_vocabs[0]
    runs = run_all(
        mapper, bundle.input_df, config, out_dir, dataset_sha=bundle.card["subsample_sha256"], repo_root=repo_root
    )
    vr = runs.get(primary)
    if vr is None or not vr.ok or not vr.output_tsv:
        err = vr.error if vr else "no run recorded"
        raise RuntimeError(f"{config.key} BioMapper primary vocab {primary!r} produced no result ({err!r}).")
    biomapper_mapped = pd.read_csv(vr.output_tsv, sep="\t")
    biomapper_result = score_curie(biomapper_mapped, config, vocab=primary)

    # 2. Competitors on the IDENTICAL rows (bundle.input_df — same subsample, same held-out gold).
    clients = clients if clients is not None else build_default_clients()
    comp_runs = run_all_competitors(clients, bundle.input_df, config)
    competitor_results = [score_competitor_run(r, config) for r in comp_runs]
    for r, res in zip(comp_runs, competitor_results):
        (out_dir / f"{r.tool}_results.json").write_text(json.dumps(res, indent=2, default=str))

    # 3. Head-to-head (fail-loud on row/gold mismatch or an unscorable BioMapper run).
    results_path = out_dir / "results.json"
    assembled = assemble_head_to_head(
        config=config,
        biomapper_result=biomapper_result,
        competitor_results=competitor_results,
        out_path=results_path,
    )
    assembled["source_namespace"] = source_namespace_for(config)
    results_path.write_text(json.dumps(assembled, indent=2, default=str))
    return {"out_dir": str(out_dir), "results": str(results_path), "tools": [e["tool"] for e in assembled["tools"]]}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the gene/protein competitor head-to-head (GATED live step).")
    parser.add_argument("--dataset", required=True, choices=sorted(CURIE_REGISTRY), help="backbone dataset key")
    parser.add_argument("--source", required=True, help="URL (streamed) or local path/line-source for the backbone")
    parser.add_argument("--out", default=None, help="override output dir (default: timestamped runs/)")
    parser.add_argument("--no-gate", action="store_true", help="skip the Phase-0 liveness gate (NOT recommended)")
    return parser


def _resolve_source(arg: str):
    from ..run import _local_line_iter

    p = Path(arg)
    return _local_line_iter(p) if p.exists() else arg  # backbone loader wants a line iterator / URL


def main() -> None:
    args = build_parser().parse_args()
    config = CURIE_REGISTRY[args.dataset]
    result = orchestrate_competitors(
        config=config,
        source=_resolve_source(args.source),
        out_dir=Path(args.out) if args.out else None,
        run_gate_first=not args.no_gate,
    )
    print(f"Saved competitor head-to-head to {result['out_dir']}; results at {result['results']}")


if __name__ == "__main__":
    main()
