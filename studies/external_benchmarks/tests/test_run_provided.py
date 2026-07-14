"""Provided-ID CLI wiring + orchestrator fail-closed path (offline; live collaborators faked)."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

import studies.external_benchmarks.run as run_mod
from studies.external_benchmarks.config import PROVIDED_ID_BACKBONE, PROVIDED_ID_REGISTRY


def test_cli_parses_provided_id_subcommand():
    parser = run_mod.build_parser()
    args = parser.parse_args(["provided-id", "--dataset", "ncbi-gene2ensembl-provided-id", "--source", "x.gz"])
    assert args.command == "provided-id"
    assert args.dataset == "ncbi-gene2ensembl-provided-id"
    assert args.source == "x.gz"


def test_cli_rejects_unknown_provided_dataset():
    parser = run_mod.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["provided-id", "--dataset", "not-a-dataset", "--source", "x"])


def test_cli_legacy_hajjar_flag_still_parses():
    parser = run_mod.build_parser()
    args = parser.parse_args(["--supplement", "hajjar.csv"])
    assert args.command is None
    assert args.supplement == "hajjar.csv"


def test_registry_and_backbone_map_are_aligned():
    # every provided-ID dataset has a backbone-source entry (None allowed for the Hajjar anchor)
    assert set(PROVIDED_ID_REGISTRY) == set(PROVIDED_ID_BACKBONE)
    assert PROVIDED_ID_BACKBONE["hajjar-100-provided-id"] is None
    assert PROVIDED_ID_BACKBONE["ncbi-gene2ensembl-provided-id"] is not None


def _install_fakes(monkeypatch, tmp_path, *, result=None, run_ok=True, mapped_df=None, patch_score=True):
    import studies.external_benchmarks.adapters.provided_id as adapter_mod
    import studies.external_benchmarks.report.campaign as campaign_mod
    import studies.external_benchmarks.runner as runner_mod
    import studies.external_benchmarks.scorers.provided_id_scorer as scorer_mod

    monkeypatch.setattr("biomapper2.mapper.Mapper", lambda *a, **k: SimpleNamespace(linker=object()))

    tsv = tmp_path / "mapped.tsv"
    if mapped_df is None:
        mapped_df = pd.DataFrame({"entrez": ["672"], "chosen_kg_id": ["NCBIGene:672"]})
    mapped_df.to_csv(tsv, sep="\t", index=False)

    bundle = SimpleNamespace(
        input_df=pd.DataFrame({"entrez": ["672"], "gold_ensembl": ["ENSEMBL:ENSG1"], "query_placeholder": [""]}),
        card={"source_sha256": "deadbeef", "dataset": "ncbi-gene2ensembl-provided-id"},
    )
    monkeypatch.setattr(adapter_mod, "load_provided", lambda *a, **k: bundle)
    monkeypatch.setattr(adapter_mod, "persist_subsample", lambda *a, **k: tmp_path / "sub.csv")

    run = SimpleNamespace(ok=run_ok, output_tsv=str(tsv) if run_ok else None, stats={}, manifest={}, error="boom")
    monkeypatch.setattr(runner_mod, "run_provided_id", lambda *a, **k: run)
    # patch_score=False exercises the REAL scorer against the on-disk mapped tsv (fail-loud test).
    if patch_score:
        monkeypatch.setattr(scorer_mod, "score_provided_id", lambda *a, **k: result)
    monkeypatch.setattr(campaign_mod, "assemble_campaign_report", lambda **k: None)


def test_orchestrate_provided_offline_happy_path(monkeypatch, tmp_path):
    result = {
        "arm": "gene",
        "comparable_core": {"metric": "top1_accuracy", "top1_accuracy": 0.9, "correct": 9, "scored_denominator": 10},
        "coverage": {"n_predicted": 10, "total": 10, "fraction": 1.0},
        "curie_stats": {"precision": 0.9, "recall": 0.9, "f1": 0.9, "predicted_and_gold": 10},
    }
    _install_fakes(monkeypatch, tmp_path, result=result)
    config = PROVIDED_ID_REGISTRY["ncbi-gene2ensembl-provided-id"]
    out = run_mod.orchestrate_provided(
        config=config,
        source="ftp://example/gene2ensembl.gz",
        backbone_config=PROVIDED_ID_BACKBONE["ncbi-gene2ensembl-provided-id"],
        out_dir=tmp_path / "out",
        run_gate_first=False,
    )
    assert out["dataset"] == config.key
    assert (tmp_path / "out" / f"{config.key}_provided_results.json").exists()
    assert (tmp_path / "out" / "dataset_card.json").exists()


def test_orchestrate_provided_refuses_failed_run(monkeypatch, tmp_path):
    _install_fakes(monkeypatch, tmp_path, result={}, run_ok=False)
    config = PROVIDED_ID_REGISTRY["ncbi-gene2ensembl-provided-id"]
    with pytest.raises(RuntimeError, match="produced no result|boom"):
        run_mod.orchestrate_provided(
            config=config,
            source="ftp://example/gene2ensembl.gz",
            backbone_config=PROVIDED_ID_BACKBONE["ncbi-gene2ensembl-provided-id"],
            out_dir=tmp_path / "out",
            run_gate_first=False,
        )


def test_orchestrate_provided_refuses_unscorable_run_and_writes_no_results(monkeypatch, tmp_path):
    # Greptile #2: every held-out target is empty -> real scorer returns top1_accuracy=None
    # (scored_denominator=0). Persisting that as success would file an `n/a` benchmark. The run must
    # RAISE before any results json is written — the same fail-loud rule as the name-input flow.
    unscorable = pd.DataFrame(
        {"entrez": ["672"], "chosen_kg_id": ["NCBIGene:672"], "kg_equivalent_ids": ["{}"], "gold_ensembl": [""]}
    )
    _install_fakes(monkeypatch, tmp_path, mapped_df=unscorable, patch_score=False)
    config = PROVIDED_ID_REGISTRY["ncbi-gene2ensembl-provided-id"]
    out_dir = tmp_path / "out"
    with pytest.raises(RuntimeError, match="no scorable held-out targets|top1_accuracy is None"):
        run_mod.orchestrate_provided(
            config=config,
            source="ftp://example/gene2ensembl.gz",
            backbone_config=PROVIDED_ID_BACKBONE["ncbi-gene2ensembl-provided-id"],
            out_dir=out_dir,
            run_gate_first=False,
        )
    # no results json persisted for the unscorable run (refused before the write)
    assert not (out_dir / f"{config.key}_provided_results.json").exists()


# --------------------------------------------------------------------------------------------------
# Greptile #1: local-file --source must parse into records (a URL streams; a local file must too).
# --------------------------------------------------------------------------------------------------

GENE2ENSEMBL_LINES = [
    "#tax_id\tGeneID\tEnsembl_gene_identifier\tRNA_nucleotide\tEnsembl_rna\tprotein_acc\tEnsembl_protein",
    "9606\t672\tENSG00000012048\tNM_007294.4\tENST1\tNP_009225.1\tENSP1",
    "10090\t12189\tENSMUSG00000017146\tNM_009764.3\tENST2\tNP_033894.3\tENSP2",  # mouse -> filtered
    "9606\t7157\tENSG00000141510\tNM_000546.6\tENST3\tNP_000537.3\tENSP3",
]


def test_resolve_provided_source_returns_line_iter_for_local_backbone_file(tmp_path):
    from dataclasses import replace

    from studies.external_benchmarks.adapters import provided_id as pv
    from studies.external_benchmarks.config import NCBI_GENE2ENSEMBL, PROVIDED_NCBI_GENE2ENSEMBL

    local = tmp_path / "gene2ensembl.tsv"
    local.write_text("\n".join(GENE2ENSEMBL_LINES) + "\n")

    src = run_mod._resolve_provided_source(str(local), NCBI_GENE2ENSEMBL)
    # NOT bytes (the bug): a bytes source would iterate to integers and crash the parser
    assert not isinstance(src, (bytes, bytearray))
    assert not isinstance(src, str)

    # and it actually parses into records: source ids are strings ("672"), never ints
    bundle = pv.load_provided_backbone(src, PROVIDED_NCBI_GENE2ENSEMBL, replace(NCBI_GENE2ENSEMBL, subsample_n=10))
    entrez = bundle.input_df["entrez"].tolist()
    assert set(entrez) == {"672", "7157"}  # human rows parsed; mouse + header dropped
    assert all(isinstance(v, str) for v in entrez)


def test_resolve_provided_source_local_gzip_backbone_file(tmp_path):
    import gzip
    from dataclasses import replace

    from studies.external_benchmarks.adapters import provided_id as pv
    from studies.external_benchmarks.config import NCBI_GENE2ENSEMBL, PROVIDED_NCBI_GENE2ENSEMBL

    local = tmp_path / "gene2ensembl.tsv.gz"
    with gzip.open(local, "wt", encoding="utf-8") as fh:
        fh.write("\n".join(GENE2ENSEMBL_LINES) + "\n")

    src = run_mod._resolve_provided_source(str(local), NCBI_GENE2ENSEMBL)
    bundle = pv.load_provided_backbone(src, PROVIDED_NCBI_GENE2ENSEMBL, replace(NCBI_GENE2ENSEMBL, subsample_n=10))
    assert set(bundle.input_df["entrez"]) == {"672", "7157"}


def test_resolve_provided_source_url_and_hajjar_local(tmp_path):
    from studies.external_benchmarks.config import NCBI_GENE2ENSEMBL

    # URL (non-existent path): returned as-is for both loaders to stream/fetch
    assert run_mod._resolve_provided_source("https://ftp.ncbi.nlm.nih.gov/x.gz", NCBI_GENE2ENSEMBL) == (
        "https://ftp.ncbi.nlm.nih.gov/x.gz"
    )
    # Hajjar anchor (no backbone): a local file is read to bytes (the Hajjar loader accepts bytes)
    hajjar_local = tmp_path / "hajjar.csv"
    hajjar_local.write_bytes(
        b"Metabolite name,ChEBI ID,InChIKey,SMILES\nEthanol,CHEBI:16236,LFQSCWFLJHTTHZ-UHFFFAOYSA-N,CCO\n"
    )
    src = run_mod._resolve_provided_source(str(hajjar_local), None)
    assert isinstance(src, bytes)
