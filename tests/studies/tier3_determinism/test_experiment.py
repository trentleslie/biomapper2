"""End-to-end tests for the orchestrator: save-by-default + pinned manifest."""

import json
from datetime import datetime, timezone
from pathlib import Path

from studies.tier3_determinism import dataset, experiment, prompt
from studies.tier3_determinism.call_model import ModelResponse
from studies.tier3_determinism.models import ExperimentConfig, ModelSpec, Query

_NOW = datetime(2026, 7, 13, 5, 30, 15, tzinfo=timezone.utc)


def _dataset(tmp_path: Path) -> Path:
    recs = [
        {
            "query_id": "q1",
            "query_name": "caffeine",
            "entity_type": "metabolite",
            "target_namespace": "CHEBI",
            "gold_curie": "CHEBI:27732",
        },
        {
            "query_id": "q2",
            "query_name": "urea",
            "entity_type": "metabolite",
            "target_namespace": "CHEBI",
            "gold_curie": "CHEBI:16199",
        },
    ]
    p = tmp_path / "qs.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    return p


def _config(path: Path) -> ExperimentConfig:
    return ExperimentConfig(
        dataset_path=path,
        models=[ModelSpec(provider="openai", model_id="gpt-x", label="gpt")],
        temperatures=[0.0, 0.7],
        n_repeats=2,
    )


def _fake_call(spec, messages, decoding, client=None):
    return ModelResponse(text='{"id": "CHEBI:27732"}', prompt_tokens=1, completion_tokens=1, latency_s=0.0)


def _fake_resolve(query: Query) -> str | None:
    return query.gold_curie  # deterministic, correct -> byte-identical, accuracy 1.0


def test_run_writes_all_artifacts_and_returns_out_dir(tmp_path: Path) -> None:
    ds = _dataset(tmp_path)
    result = experiment.run_experiment(
        _config(ds),
        out_dir=tmp_path / "run",
        call_fn=_fake_call,
        resolve_fn=_fake_resolve,
        now=_NOW,
        git_commit="abc123",
    )
    out = Path(result.out_dir)
    for name in ("manifest.json", "arm_a_raw.jsonl", "arm_b_raw.jsonl", "fig4_data.json"):
        assert (out / name).exists(), f"missing {name}"


def test_manifest_pins_sha_prompt_models_and_decoding(tmp_path: Path) -> None:
    ds = _dataset(tmp_path)
    result = experiment.run_experiment(
        _config(ds),
        out_dir=tmp_path / "run",
        call_fn=_fake_call,
        resolve_fn=_fake_resolve,
        now=_NOW,
        git_commit="abc123",
    )
    manifest = json.loads((Path(result.out_dir) / "manifest.json").read_text())
    assert manifest["dataset_sha256"] == dataset.content_sha256(ds)
    assert manifest["prompt_sha256"] == prompt.prompt_fingerprint()
    assert manifest["n_repeats"] == 2
    assert manifest["temperatures"] == [0.0, 0.7]
    assert manifest["git_commit"] == "abc123"
    assert manifest["models"][0]["model_id"] == "gpt-x"
    assert manifest["generated_utc"].startswith("2026-07-13T05:30:15")


def test_raw_run_files_hold_every_call(tmp_path: Path) -> None:
    ds = _dataset(tmp_path)
    result = experiment.run_experiment(
        _config(ds),
        out_dir=tmp_path / "run",
        call_fn=_fake_call,
        resolve_fn=_fake_resolve,
        now=_NOW,
        git_commit="abc",
    )
    out = Path(result.out_dir)
    arm_a_lines = (out / "arm_a_raw.jsonl").read_text().splitlines()
    arm_b_lines = (out / "arm_b_raw.jsonl").read_text().splitlines()
    assert len(arm_a_lines) == 1 * 2 * 2 * 2  # models x temps x queries x repeats
    assert len(arm_b_lines) == 2 * 2  # queries x repeats


def test_save_by_default_uses_timestamped_runs_dir(tmp_path: Path, capsys) -> None:
    ds = _dataset(tmp_path)
    cfg = _config(ds)
    result = experiment.run_experiment(
        cfg,
        out_dir=None,
        call_fn=_fake_call,
        resolve_fn=_fake_resolve,
        now=_NOW,
        git_commit="abc",
        runs_root=tmp_path / "runs",
    )
    out = Path(result.out_dir)
    assert out.parent == (tmp_path / "runs")
    assert out.name == "20260713T053015Z"  # derived from `now`
    assert str(out) in capsys.readouterr().out  # path printed on completion


def test_fig4_json_has_both_arms(tmp_path: Path) -> None:
    ds = _dataset(tmp_path)
    result = experiment.run_experiment(
        _config(ds),
        out_dir=tmp_path / "run",
        call_fn=_fake_call,
        resolve_fn=_fake_resolve,
        now=_NOW,
        git_commit="abc",
    )
    fig = json.loads((Path(result.out_dir) / "fig4_data.json").read_text())
    assert len(fig["arm_a"]) == 2  # one panel per temperature
    assert fig["biomapper"]["byte_identical"] is True
    assert fig["biomapper"]["accuracy"] == 1.0
