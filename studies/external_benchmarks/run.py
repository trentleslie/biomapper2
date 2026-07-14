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

    from .adapters.hajjar import fetch_supplement, load_hajjar, parse_raw
    from .figures.competitor_panel import render_s2
    from .figures.vocab_bar import render_s1
    from .gate import DEFAULT_PER_EXTERNAL_CALL_USD, build_live_smoke_fn, run_gate
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
        gate_result = run_gate(
            build_live_smoke_fn(mapper),
            n_rows=100,
            per_external_call_usd=DEFAULT_PER_EXTERNAL_CALL_USD,
        )
        (out_dir / "gate_result.json").write_text(
            json.dumps({"verdict": gate_result.verdict, "reason": gate_result.reason}, indent=2)
        )
        if not gate_result.passed:
            raise RuntimeError(f"Phase-0 gate stopped the run: {gate_result.reason}")

    # 2. Acquire. Normalize a URL to bytes up front so the source table is ALWAYS available
    # for validation. Previously a URL source left ``source_df=None``, which silently made the
    # validation guard skip every external-anchor check while still emitting figures/report
    # from unvalidated results. Fetching once here also keeps the SHA pin deterministic
    # (load_hajjar and parse_raw see the identical bytes).
    if isinstance(source, str):
        source = fetch_supplement(source)
    bundle = load_hajjar(source, config)
    source_df = parse_raw(source)
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
    # Fail-closed: a failed primary run must halt HERE with the recorded mapper error, not
    # surface downstream as an opaque KeyError at the figure stage (which would mask the
    # real cause). run_all records the failure; the scoring loop skips it, so ``primary``
    # is simply absent from ``per_vocab_struct``.
    if primary not in per_vocab_struct:
        primary_err = runs[primary].error if primary in runs else "no run recorded"
        raise RuntimeError(
            f"Primary vocab {primary!r} produced no scored result "
            f"(mapper run failed: {primary_err!r}) — refusing to generate figures/report."
        )
    primary_tsv = runs[primary].output_tsv
    assert primary_tsv is not None  # guaranteed: presence in per_vocab_struct implies ok output
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

    # 6. Figures (only after verify + validate pass).
    s1 = render_s1(per_vocab_struct, out_dir / "S1_vocab_bar.png", input_type=config.input_type)
    # The competitor panel plots the BioMapper marker beside published Hajjar numbers. Per the
    # protocol-parity gate that comparison is only legitimate once a published cell has been
    # reproduced within tolerance — so the parity cell is REQUIRED to emit S2. Without it the
    # parity gate is skipped inside validate_all, so refuse the figure (fail-closed) rather
    # than silently plotting an unreproduced comparison.
    if published_parity_cell is None:
        raise RuntimeError(
            "Competitor figure requires a reproduced protocol-parity cell "
            "(published_parity_cell = (reproduced, published, tolerance)); refusing to plot "
            "the BioMapper marker beside published competitor numbers without it. "
            "Supply --parity-cell on the CLI."
        )
    # Fail-closed: top1_accuracy is None when the primary run scored zero comparable rows.
    # Coercing that missing measurement to 0.0 would plant a concrete "BioMapper 0%" bar
    # beside published competitors — fabricating a result from an absent one. Refuse instead.
    primary_top1 = per_vocab_struct[primary]["comparable_core"]["top1_accuracy"]
    if primary_top1 is None:
        raise RuntimeError(
            f"Primary vocab {primary!r} has no scored rows (top1_accuracy is None) — refusing "
            "to plot an unscorable result as 0% beside published competitor numbers."
        )
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


def orchestrate_necs(
    *,
    source: bytes | str,
    out_dir: Path | None = None,
    repo_root: Path | None = None,
    run_gate_first: bool = True,
) -> dict[str, Any]:
    """Run the NECS metabolite slice live (structure oracle, strict + charge-normalized).

    One accuracy number per dataset (single CHEBI vocab), no competitor figure. Heavy deps are
    imported lazily so this module imports offline.
    """
    import pandas as pd

    from biomapper2.core.structure_resolver import StructureResolver
    from biomapper2.mapper import Mapper

    from .adapters.necs_metabolon import fetch_supplement, load_necs, parse_xlsx
    from .config import NECS
    from .oracle import KGStructureOracle
    from .report.campaign import assemble_campaign_report
    from .runner import run_all
    from .scorers.structure_oracle_scorer import neutralize_first_block, score_structure_oracle
    from .verify import reconcile

    repo_root = repo_root or Path.cwd()
    out_dir = out_dir or default_run_dir(NECS, Path(__file__).parent / "runs")
    out_dir.mkdir(parents=True, exist_ok=True)

    mapper = Mapper()
    if run_gate_first:
        from .gate import DEFAULT_PER_EXTERNAL_CALL_USD, build_live_smoke_fn, run_gate

        gate_result = run_gate(
            build_live_smoke_fn(mapper), n_rows=1495, per_external_call_usd=DEFAULT_PER_EXTERNAL_CALL_USD
        )
        (out_dir / "gate_result.json").write_text(
            json.dumps({"verdict": gate_result.verdict, "reason": gate_result.reason}, indent=2)
        )
        if not gate_result.passed:
            raise RuntimeError(f"Phase-0 gate stopped the NECS run: {gate_result.reason}")

    if isinstance(source, str):
        source = fetch_supplement(source)
    bundle = load_necs(source, NECS)
    _ = parse_xlsx  # source frame retained for validation parity in a future pass
    (out_dir / "dataset_card.json").write_text(json.dumps(bundle.card, indent=2))

    primary = NECS.target_vocabs[0]
    runs = run_all(
        mapper, bundle.input_df, NECS, out_dir, dataset_sha=bundle.card["source_sha256"], repo_root=repo_root
    )
    vr = runs.get(primary)
    if vr is None or not vr.ok or not vr.output_tsv:
        err = vr.error if vr else "no run recorded"
        raise RuntimeError(f"NECS primary vocab {primary!r} produced no result (mapper failed: {err!r}).")

    oracle = KGStructureOracle(StructureResolver(mapper.linker), mapper.linker)
    mapped_df = pd.read_csv(vr.output_tsv, sep="\t")
    result = score_structure_oracle(
        mapped_df, NECS, oracle, vocab=primary, gold_smiles_normalizer=neutralize_first_block
    )
    rec = reconcile({"structure": result}, mapped_df, NECS, oracle)
    if not rec.passed:
        raise RuntimeError(f"NECS reconciliation failed: {rec.mismatches}")
    (out_dir / f"{primary}_results.json").write_text(json.dumps(result, indent=2))

    report_path = out_dir / f"{NECS.key}_report.md"
    assemble_campaign_report(
        metabolite_entries=[{"key": NECS.key, "result": result}],
        curie_entries=[],
        integrity={"reconciliation_passed": rec.passed, "validation_passed": None},
        out_path=report_path,
    )
    return {"out_dir": str(out_dir), "report": str(report_path), "vocab": primary}


def orchestrate_backbone(
    *,
    config,
    source,
    out_dir: Path | None = None,
    repo_root: Path | None = None,
    run_gate_first: bool = True,
) -> dict[str, Any]:
    """Run one gene/protein backbone slice live (CURIE equality). No competitor figure.

    ``config`` is a ``CurieDatasetConfig``; ``source`` is a URL string (streamed) or a line
    iterator (tests). Heavy deps imported lazily.
    """
    import pandas as pd

    from biomapper2.mapper import Mapper

    from .adapters.backbones import load_backbone, persist_subsample, resolve_source_version
    from .report.campaign import assemble_campaign_report
    from .runner import run_all
    from .scorers.curie_scorer import score_curie

    repo_root = repo_root or Path.cwd()
    out_dir = out_dir or default_run_dir(config, Path(__file__).parent / "runs")
    out_dir.mkdir(parents=True, exist_ok=True)

    mapper = Mapper()
    if run_gate_first:
        from .gate import build_live_gene_protein_smoke_fn, run_gene_protein_gate

        gate_result = run_gene_protein_gate(build_live_gene_protein_smoke_fn(mapper))
        (out_dir / "gate_result.json").write_text(
            json.dumps({"verdict": gate_result.verdict, "reason": gate_result.reason}, indent=2)
        )
        if not gate_result.passed:
            raise RuntimeError(f"Gene/protein Phase-0 gate stopped the run: {gate_result.reason}")

    # The backbone sources are mutable current_release mirrors, so URL+seed+n cannot reconstruct
    # the scored subset after an upstream release. Resolve the upstream release version (best
    # effort) and PERSIST the exact subsample beside the card — that persisted artifact, not the
    # URL, is what makes the run reproducible.
    source_version = resolve_source_version(source) if isinstance(source, str) else None
    bundle = load_backbone(source, config, source_version=source_version)
    (out_dir / "dataset_card.json").write_text(json.dumps(bundle.card, indent=2))
    persist_subsample(bundle, out_dir)

    primary = config.target_vocabs[0]
    runs = run_all(
        mapper, bundle.input_df, config, out_dir, dataset_sha=bundle.card["subsample_sha256"], repo_root=repo_root
    )
    vr = runs.get(primary)
    if vr is None or not vr.ok or not vr.output_tsv:
        err = vr.error if vr else "no run recorded"
        raise RuntimeError(f"{config.key} primary vocab {primary!r} produced no result (mapper failed: {err!r}).")

    mapped_df = pd.read_csv(vr.output_tsv, sep="\t")
    result = score_curie(mapped_df, config, vocab=primary)
    (out_dir / f"{primary}_results.json").write_text(json.dumps(result, indent=2))

    report_path = out_dir / f"{config.key}_report.md"
    assemble_campaign_report(
        metabolite_entries=[],
        curie_entries=[{"key": config.key, "arm": config.arm, "result": result}],
        integrity={"reconciliation_passed": None, "validation_passed": None},
        out_path=report_path,
    )
    return {"out_dir": str(out_dir), "report": str(report_path), "vocab": primary}


def orchestrate_provided(
    *,
    config,
    source,
    backbone_config=None,
    out_dir: Path | None = None,
    repo_root: Path | None = None,
    run_gate_first: bool = True,
) -> dict[str, Any]:
    """Run one provided-ID (identifier-input) dataset live — BioMapper's core cross-namespace regime.

    The SOURCE id is handed to BioMapper as a provided id (``annotation_mode='none'``, pure
    equivalence expansion); the TARGET cross-ref is held out and consumed only by the scorer.
    ``config`` is a ``ProvidedIdDatasetConfig``; ``backbone_config`` is the source CurieDatasetConfig
    for gene/protein sets (None for the Hajjar metabolite anchor). ``source`` is a URL/bytes/line-
    iterator, dispatched by the adapter. No competitor figure. Heavy deps imported lazily.
    """
    import pandas as pd

    from biomapper2.mapper import Mapper

    from .adapters import provided_id as provided_adapter
    from .report.campaign import assemble_campaign_report
    from .runner import run_provided_id
    from .scorers.provided_id_scorer import score_provided_id

    repo_root = repo_root or Path.cwd()
    out_dir = out_dir or default_run_dir(config, Path(__file__).parent / "runs")
    out_dir.mkdir(parents=True, exist_ok=True)

    mapper = Mapper()
    if run_gate_first:
        # Reuse the arm's existing Phase-0 liveness gate. Provided-ID mode makes NO external
        # annotation calls (annotation_mode='none'), so this is a coarse liveness check, not a cost
        # gate — but keep it fail-closed so a dead Kestrel stops the run before scoring.
        if config.arm in ("gene", "protein"):
            from .gate import build_live_gene_protein_smoke_fn, run_gene_protein_gate

            gate_result = run_gene_protein_gate(build_live_gene_protein_smoke_fn(mapper))
        else:
            from .gate import DEFAULT_PER_EXTERNAL_CALL_USD, build_live_smoke_fn, run_gate

            gate_result = run_gate(
                build_live_smoke_fn(mapper), n_rows=100, per_external_call_usd=DEFAULT_PER_EXTERNAL_CALL_USD
            )
        (out_dir / "gate_result.json").write_text(
            json.dumps({"verdict": gate_result.verdict, "reason": gate_result.reason}, indent=2)
        )
        if not gate_result.passed:
            raise RuntimeError(f"Provided-ID Phase-0 gate stopped the run: {gate_result.reason}")

    bundle = provided_adapter.load_provided(source, config, backbone_config)
    (out_dir / "dataset_card.json").write_text(json.dumps(bundle.card, indent=2))
    provided_adapter.persist_subsample(bundle, out_dir)

    run = run_provided_id(
        mapper, bundle.input_df, config, out_dir, dataset_sha=bundle.card["source_sha256"], repo_root=repo_root
    )
    if not run.ok or not run.output_tsv:
        raise RuntimeError(f"{config.key} provided-ID run produced no result (mapper failed: {run.error!r}).")

    mapped_df = pd.read_csv(run.output_tsv, sep="\t")
    result = score_provided_id(mapped_df, config)
    # Fail-closed on an unscorable run — the SAME rule the name-input flow enforces (run.py:156).
    # top1_accuracy is None only when the scored denominator is zero (no row carried a held-out
    # target), i.e. an `n/a` benchmark. Persisting that as a success would file a run that measured
    # nothing; refuse BEFORE writing any results/report so an unscorable run never looks green.
    if result["comparable_core"]["top1_accuracy"] is None:
        raise RuntimeError(
            f"{config.key}: no scorable held-out targets (top1_accuracy is None; "
            f"scored_denominator={result['comparable_core']['scored_denominator']}) — refusing to "
            f"persist an unscorable provided-ID run as success."
        )
    (out_dir / f"{config.key}_provided_results.json").write_text(json.dumps(result, indent=2))

    report_path = out_dir / f"{config.key}_report.md"
    assemble_campaign_report(
        metabolite_entries=[],
        curie_entries=[{"key": config.key, "arm": f"{config.arm} (provided-ID)", "result": result}],
        integrity={"reconciliation_passed": None, "validation_passed": None},
        out_path=report_path,
    )
    return {"out_dir": str(out_dir), "report": str(report_path), "dataset": config.key}


def orchestrate_metabench(
    *,
    source,
    config=None,
    out_dir: Path | None = None,
    repo_root: Path | None = None,
    run_gate_first: bool = True,
) -> dict[str, Any]:
    """Run the MetaBench Grounding benchmark live — the one external set with a valid LLM head-to-head.

    Decomposes the 1,000-pair set into per-subgroup runs (ID->ID in provided-ID mode, name->ID in
    name-input mode), concatenates every subgroup's mapper output (each carries the held-out gold +
    target-namespace columns verbatim), and scores ONCE into a single accuracy. Then places that one
    number alongside the paper's published 25-LLM baseline distribution (transcribed with citation
    discipline; values left needs-verification). Heavy deps imported lazily.
    """
    import pandas as pd

    from biomapper2.mapper import Mapper

    from .adapters import metabench as metabench_adapter
    from .config import (
        METABENCH,
        CurieDatasetConfig,
        MetaBenchDatasetConfig,
        ProvidedIdDatasetConfig,
    )
    from .report.metabench import assemble_metabench_report
    from .runner import run_provided_id, run_vocab
    from .scorers.metabench_scorer import score_metabench

    config = config or METABENCH
    assert isinstance(config, MetaBenchDatasetConfig)
    repo_root = repo_root or Path.cwd()
    out_dir = out_dir or (Path(__file__).parent / "runs" / f"{config.key}_latest")
    out_dir.mkdir(parents=True, exist_ok=True)

    mapper = Mapper()
    if run_gate_first:
        from .gate import DEFAULT_PER_EXTERNAL_CALL_USD, build_live_smoke_fn, run_gate

        gate_result = run_gate(
            build_live_smoke_fn(mapper), n_rows=100, per_external_call_usd=DEFAULT_PER_EXTERNAL_CALL_USD
        )
        (out_dir / "gate_result.json").write_text(
            json.dumps({"verdict": gate_result.verdict, "reason": gate_result.reason}, indent=2)
        )
        if not gate_result.passed:
            raise RuntimeError(f"MetaBench Phase-0 gate stopped the run: {gate_result.reason}")

    bundle = metabench_adapter.load_metabench(source, config)
    (out_dir / "dataset_card.json").write_text(json.dumps(bundle.card, indent=2))
    dataset_sha = bundle.card["source_sha256"]

    mapped_frames: list[pd.DataFrame] = []
    for sub in bundle.subgroups:
        sub_dir = out_dir / sub.key
        if sub.pair_type == "id2id":
            # Provided-ID mode: the source id is handed to BioMapper; the target is held out. The
            # ProvidedIdDatasetConfig __post_init__ re-enforces source-namespace != target-namespace.
            assert sub.source_id_column is not None  # build_subgroups always sets it for id2id
            pid = ProvidedIdDatasetConfig(
                key=sub.key,
                arm=config.arm,
                entity_type=config.entity_type,
                source_id_column=sub.source_id_column,
                source_namespace=sub.source_namespace,
                name_column=config.name_column,
                gold_target_columns=((sub.target_namespace, config.gold_target_column),),
                target_vocabs=(sub.target_namespace,),
                source_label=f"MetaBench Grounding ({sub.key})",
                source_url=config.source_url,
                license=config.license,
            )
            run = run_provided_id(
                mapper, sub.input_df, pid, sub_dir, dataset_sha=dataset_sha, repo_root=repo_root
            )
            output_tsv = run.output_tsv
        else:
            # Name-input mode: the metabolite name is annotated; the target id is held out. Reuse the
            # CURIE-arm RunnableConfig purely for the runner machinery — scoring is uniform below.
            cfg = CurieDatasetConfig(
                key=sub.key,
                arm=config.arm,
                entity_type=config.entity_type,
                input_type="name",
                name_column=config.name_column,
                target_vocabs=(sub.vocab,),
                gold_curie_columns=((sub.target_namespace, config.gold_target_column),),
                source_label=f"MetaBench Grounding ({sub.key})",
                source_url=config.source_url,
                license=config.license,
            )
            vr = run_vocab(
                mapper, sub.input_df, cfg, sub.vocab, sub_dir, dataset_sha=dataset_sha, repo_root=repo_root
            )
            output_tsv = vr.output_tsv
        if not output_tsv:
            raise RuntimeError(f"{sub.key}: mapper produced no output — refusing to score a partial MetaBench run.")
        mapped_frames.append(pd.read_csv(output_tsv, sep="\t"))

    mapped_df = pd.concat(mapped_frames, ignore_index=True)
    result = score_metabench(mapped_df, config)
    # Fail-closed on an unscorable run (same rule as the name-input / provided-ID flows): top1 is
    # None only when nothing carried a held-out gold. Persisting that would file a run that measured
    # nothing.
    if result["comparable_core"]["top1_accuracy"] is None:
        raise RuntimeError(
            f"{config.key}: no scorable held-out targets (top1_accuracy is None; "
            f"scored_denominator={result['comparable_core']['scored_denominator']}) — refusing to "
            f"persist an unscorable MetaBench run as success."
        )
    (out_dir / f"{config.key}_results.json").write_text(json.dumps(result, indent=2))

    report_path = out_dir / f"{config.key}_report.md"
    assemble_metabench_report(
        config=config,
        result=result,
        card=bundle.card,
        baselines=config.baseline_competitors,
        integrity={"reconciliation_passed": None, "validation_passed": None},
        out_path=report_path,
    )
    return {"out_dir": str(out_dir), "report": str(report_path), "dataset": config.key}


def _resolve_source_arg(arg: str) -> bytes | str:
    """A local path is read to bytes; anything else is treated as a URL (streamed by the adapter).

    Correct for the Hajjar loader (accepts bytes / URL). NOT correct for the backbone loader, which
    consumes a URL string OR a line iterator — never raw bytes (iterating bytes yields ints, not
    records). Provided-ID CLI resolution therefore uses ``_resolve_provided_source`` instead.
    """
    p = Path(arg)
    return p.read_bytes() if p.exists() else arg


def _local_line_iter(path: Path):
    """Yield decoded, newline-stripped lines from a local (optionally gzipped) file.

    Mirrors ``backbones.stream_source_lines`` output so the backbone loader parses a local file
    identically to a streamed URL. The file handle is held only for the life of the generator; the
    reservoir sampler drains it fully, so it closes deterministically.
    """
    import gzip

    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            yield line.rstrip("\n")


def _resolve_provided_source(arg: str, backbone_config) -> Any:
    """Resolve a provided-ID ``--source`` to what its loader expects (URL / bytes / line iterator).

    - URL (non-existent path): returned as-is — the Hajjar loader fetches it, the backbone loader
      streams it.
    - Local file, backbone dataset: a line iterator (gzip-aware). Passing bytes here is the bug
      Greptile flagged — ``backbones.load_backbone`` iterates a non-str source directly, so bytes
      would yield integers instead of records and parsing fails.
    - Local file, Hajjar anchor (no backbone): bytes — the Hajjar loader accepts them.
    """
    p = Path(arg)
    if not p.exists():
        return arg  # URL
    if backbone_config is not None:
        return _local_line_iter(p)  # backbone loader wants a line iterator, not bytes
    return p.read_bytes()  # Hajjar loader accepts bytes


def build_parser() -> argparse.ArgumentParser:
    """CLI: legacy top-level Hajjar flags (back-compat) + a ``provided-id`` subcommand.

    ``python -m ...run --supplement X`` keeps working (name-input Hajjar). The new
    ``python -m ...run provided-id --dataset K --source S`` drives the identifier-input datasets so
    the gated run needs no hand-written driver (NECS/backbones previously had no CLI entrypoint).
    """
    from .config import PROVIDED_ID_REGISTRY

    parser = argparse.ArgumentParser(description="Run external-benchmark slices (live).")
    parser.add_argument("--supplement", default=None, help="path/URL to the Hajjar supplement (legacy name-input run)")
    parser.add_argument("--out", default=None, help="override output dir (default: timestamped runs/)")
    parser.add_argument("--no-gate", action="store_true", help="skip the Phase-0 gate (NOT recommended)")
    parser.add_argument(
        "--parity-cell",
        default=None,
        help=(
            "protocol-parity cell as 'reproduced,published,tolerance' (three floats). REQUIRED "
            "to emit the competitor figure: reproduces a published Hajjar cell so the BioMapper "
            "marker is only plotted beside a verified number."
        ),
    )
    sub = parser.add_subparsers(dest="command")
    pv = sub.add_parser("provided-id", help="run a provided-ID (identifier-input) dataset")
    pv.add_argument("--dataset", required=True, choices=sorted(PROVIDED_ID_REGISTRY), help="provided-ID dataset key")
    pv.add_argument("--source", required=True, help="path/URL/line-source for the dataset")
    pv.add_argument("--out", default=None, help="override output dir (default: timestamped runs/)")
    pv.add_argument("--no-gate", action="store_true", help="skip the Phase-0 gate (NOT recommended)")

    mb = sub.add_parser("metabench", help="run the MetaBench Grounding benchmark (LLM head-to-head)")
    mb.add_argument(
        "--source",
        default=None,
        help="path/URL to the MetaBench Grounding CSV (default: the pinned HuggingFace source URL)",
    )
    mb.add_argument("--out", default=None, help="override output dir (default: runs/)")
    mb.add_argument("--no-gate", action="store_true", help="skip the Phase-0 gate (NOT recommended)")
    return parser


def _run_provided_cli(args, parser: argparse.ArgumentParser) -> dict[str, Any]:
    from .config import PROVIDED_ID_BACKBONE, PROVIDED_ID_REGISTRY

    config = PROVIDED_ID_REGISTRY[args.dataset]
    backbone_config = PROVIDED_ID_BACKBONE.get(args.dataset)
    src = _resolve_provided_source(args.source, backbone_config)
    out = Path(args.out) if args.out else None
    return orchestrate_provided(
        config=config,
        source=src,
        backbone_config=backbone_config,
        out_dir=out,
        run_gate_first=not args.no_gate,
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "provided-id":
        result = _run_provided_cli(args, parser)
        print(f"Saved provided-ID run to {result['out_dir']}; report at {result['report']}")
        return

    if args.command == "metabench":
        from .config import METABENCH

        src = _resolve_source_arg(args.source) if args.source else METABENCH.source_url
        out = Path(args.out) if args.out else None
        result = orchestrate_metabench(source=src, out_dir=out, run_gate_first=not args.no_gate)
        print(f"Saved MetaBench run to {result['out_dir']}; report at {result['report']}")
        return

    # Legacy name-input Hajjar path.
    if not args.supplement:
        parser.error("--supplement is required for the Hajjar name-input run (or use the 'provided-id' subcommand)")
    src = _resolve_source_arg(args.supplement)

    parity: tuple[float, float, float] | None = None
    if args.parity_cell:
        try:
            parts = [float(x) for x in args.parity_cell.split(",")]
        except ValueError:
            parser.error("--parity-cell must be three floats 'reproduced,published,tolerance'")
        if len(parts) != 3:
            parser.error("--parity-cell must be three floats 'reproduced,published,tolerance'")
        parity = (parts[0], parts[1], parts[2])

    out = Path(args.out) if args.out else None
    result = orchestrate(source=src, out_dir=out, run_gate_first=not args.no_gate, published_parity_cell=parity)
    print(f"Saved run to {result['out_dir']}; report at {result['report']}")


if __name__ == "__main__":
    main()
