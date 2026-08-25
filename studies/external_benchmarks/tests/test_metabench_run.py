"""MetaBench CLI wiring + orchestrator (offline; the live Mapper is faked)."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

import studies.external_benchmarks.run as run_mod
from studies.external_benchmarks.config import METABENCH

_RAW = (
    b"question,answer\n"
    b"What is the KEGG ID of HMDB ID HMDB0010090?,C00626\n"
    b"What is the HMDB ID of KEGG ID C07251?,HMDB0014982\n"
    b"What is the ChEBI ID of metabolite Rolapitant hydrochloride?,90911\n"
)

# Synthetic fixtures cannot match the real acquisition SHA pin, so the offline orchestrator tests
# run with the gate disabled (blank pin). The gate is exercised directly in
# test_orchestrate_metabench_refuses_sha_mismatch and in test_metabench_adapter.py.
_UNPINNED = dataclasses.replace(METABENCH, expected_source_sha256="")


def test_cli_parses_metabench_subcommand():
    parser = run_mod.build_parser()
    args = parser.parse_args(["metabench", "--source", "grounding.csv", "--no-gate"])
    assert args.command == "metabench"
    assert args.source == "grounding.csv"
    assert args.no_gate is True


def test_cli_metabench_source_defaults_to_none():
    parser = run_mod.build_parser()
    args = parser.parse_args(["metabench"])
    assert args.command == "metabench"
    assert args.source is None  # main() falls back to the pinned HuggingFace source URL


def _fake_run_vocab_factory(tmp_path):
    """Fake runner: writes each subgroup's input_df (with held-out cols) plus a prediction that
    makes exactly the id2id HMDB->KEGG and the name->ChEBI rows correct.
    """

    def _write(mapper, input_df, config, vocab, out_dir, **kwargs):
        df = input_df.copy()
        # Fabricate a prediction: chosen equals the (prefixed) gold for the ChEBI name row and the
        # KEGG id row; wrong for the KEGG->HMDB row.
        chosen = []
        equiv = []
        for _, r in df.iterrows():
            tgt = str(r[METABENCH.target_namespace_column])
            gold = str(r[METABENCH.gold_target_column])
            if tgt in ("KEGG", "CHEBI"):
                chosen.append(f"{tgt}:{gold}")
                equiv.append("{}")
            else:
                chosen.append("HMDB:HMDB9999999")  # wrong
                equiv.append("{}")
        df["chosen_kg_id"] = chosen
        df["kg_equivalent_ids"] = equiv
        out_dir = run_mod.Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        tsv = out_dir / "mapped.tsv"
        df.to_csv(tsv, sep="\t", index=False)
        return SimpleNamespace(vocab=vocab, ok=True, output_tsv=str(tsv), stats={}, manifest={})

    return _write


def test_orchestrate_metabench_offline_one_number_and_report(monkeypatch, tmp_path):
    import studies.external_benchmarks.runner as runner_mod

    monkeypatch.setattr("biomapper2.mapper.Mapper", lambda *a, **k: SimpleNamespace(linker=object()))
    writer = _fake_run_vocab_factory(tmp_path)
    # Both regimes funnel through the same fake writer (provided-ID and name-input share the shape).
    monkeypatch.setattr(runner_mod, "run_vocab", writer)
    monkeypatch.setattr(
        runner_mod,
        "run_provided_id",
        lambda mapper, input_df, config, out_dir, **k: writer(mapper, input_df, config, "provided", out_dir),
    )

    out = run_mod.orchestrate_metabench(source=_RAW, config=_UNPINNED, out_dir=tmp_path / "out", run_gate_first=False)
    assert out["dataset"] == "metabench-grounding"
    results_json = tmp_path / "out" / "metabench-grounding_results.json"
    report_md = tmp_path / "out" / "metabench-grounding_report.md"
    assert results_json.exists() and report_md.exists()
    text = report_md.read_text()
    assert "25-model distribution" in text
    assert "needs verification" in text  # baselines never asserted from memory
    assert (tmp_path / "out" / "dataset_card.json").exists()


def test_orchestrate_metabench_refuses_unscorable(monkeypatch, tmp_path):
    import studies.external_benchmarks.runner as runner_mod

    monkeypatch.setattr("biomapper2.mapper.Mapper", lambda *a, **k: SimpleNamespace(linker=object()))

    def _blank(mapper, input_df, config, vocab, out_dir, **kwargs):
        df = input_df.copy()
        df[METABENCH.gold_target_column] = ""  # strip all gold -> unscorable
        df["chosen_kg_id"] = None
        df["kg_equivalent_ids"] = "{}"
        out_dir = run_mod.Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        tsv = out_dir / "mapped.tsv"
        df.to_csv(tsv, sep="\t", index=False)
        return SimpleNamespace(vocab=vocab, ok=True, output_tsv=str(tsv), stats={}, manifest={})

    monkeypatch.setattr(runner_mod, "run_vocab", _blank)
    monkeypatch.setattr(
        runner_mod,
        "run_provided_id",
        lambda mapper, input_df, config, out_dir, **k: _blank(mapper, input_df, config, "provided", out_dir),
    )
    out_dir = tmp_path / "out"
    with pytest.raises(RuntimeError, match="no scorable held-out targets|top1_accuracy is None"):
        run_mod.orchestrate_metabench(source=_RAW, config=_UNPINNED, out_dir=out_dir, run_gate_first=False)
    assert not (out_dir / "metabench-grounding_results.json").exists()


def test_orchestrate_metabench_refuses_sha_mismatch(monkeypatch, tmp_path):
    # A drifted upstream file (synthetic bytes vs the real pin) must halt the orchestrator BEFORE
    # any scoring/report — no results json, no report md, no card written.
    from studies.external_benchmarks.adapters.metabench import MetaBenchShaMismatchError

    monkeypatch.setattr("biomapper2.mapper.Mapper", lambda *a, **k: SimpleNamespace(linker=object()))
    out_dir = tmp_path / "out"
    with pytest.raises(MetaBenchShaMismatchError):
        # default config = METABENCH carries the real pin; synthetic _RAW cannot match it
        run_mod.orchestrate_metabench(source=_RAW, out_dir=out_dir, run_gate_first=False)
    assert not (out_dir / "metabench-grounding_results.json").exists()
    assert not (out_dir / "metabench-grounding_report.md").exists()
