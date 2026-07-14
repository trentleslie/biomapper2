"""End-to-end tests for the orchestrator: save-by-default + pinned manifest."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

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


def test_reused_out_dir_refuses_to_overwrite_prior_run(tmp_path: Path) -> None:
    """An explicit --out that already holds a run must not be silently clobbered."""
    ds = _dataset(tmp_path)
    out = tmp_path / "headline"
    experiment.run_experiment(
        _config(ds), out_dir=out, call_fn=_fake_call, resolve_fn=_fake_resolve, now=_NOW, git_commit="abc"
    )
    first_manifest = (out / "manifest.json").read_text()
    with pytest.raises(FileExistsError):
        experiment.run_experiment(
            _config(ds), out_dir=out, call_fn=_fake_call, resolve_fn=_fake_resolve, now=_NOW, git_commit="def"
        )
    # prior evidence untouched
    assert (out / "manifest.json").read_text() == first_manifest


def test_reused_out_dir_allows_empty_existing_dir(tmp_path: Path) -> None:
    """A pre-created but empty dir is fine (e.g. mkdir before the run)."""
    ds = _dataset(tmp_path)
    out = tmp_path / "empty"
    out.mkdir()
    result = experiment.run_experiment(
        _config(ds), out_dir=out, call_fn=_fake_call, resolve_fn=_fake_resolve, now=_NOW, git_commit="abc"
    )
    assert (Path(result.out_dir) / "manifest.json").exists()


def _boom_call(spec, messages, decoding, client=None):
    raise AssertionError("Arm A must NOT be re-run when resuming from complete raw evidence")


def test_resume_does_not_truncate_complete_arm_a_when_fig4_missing(tmp_path: Path) -> None:
    """Arm A + Arm B completed but fig4_data.json is missing (crash before figure write).
    A retry must RESUME from the complete raw files -- not re-run Arm A, not truncate its
    expensive evidence -- and produce the figure from the persisted calls."""
    ds = _dataset(tmp_path)
    out = tmp_path / "run"
    experiment.run_experiment(
        _config(ds), out_dir=out, call_fn=_fake_call, resolve_fn=_fake_resolve, now=_NOW, git_commit="abc"
    )
    arm_a_before = (out / "arm_a_raw.jsonl").read_text()
    manifest_before = (out / "manifest.json").read_text()
    # simulate a crash after the arms but before fig4_data.json was written
    (out / "fig4_data.json").unlink()

    result = experiment.run_experiment(
        _config(ds), out_dir=out, call_fn=_boom_call, resolve_fn=_fake_resolve, now=_NOW, git_commit="def"
    )
    # Arm-A raw evidence untouched (not truncated / re-run), manifest preserved (original pins).
    assert (out / "arm_a_raw.jsonl").read_text() == arm_a_before
    assert (out / "manifest.json").read_text() == manifest_before
    assert (out / "fig4_data.json").exists()
    assert len(result.arm_a) == 8  # 1 model x 2 temps x 2 queries x 2 repeats, resumed


def test_resume_arm_a_reruns_only_missing_arm_b(tmp_path: Path) -> None:
    """Arm A complete, Arm B crashed (no arm_b_raw). Retry resumes Arm A (never re-run)
    and runs only the missing Arm B."""
    ds = _dataset(tmp_path)
    out = tmp_path / "run"
    experiment.run_experiment(
        _config(ds), out_dir=out, call_fn=_fake_call, resolve_fn=_fake_resolve, now=_NOW, git_commit="abc"
    )
    arm_a_before = (out / "arm_a_raw.jsonl").read_text()
    (out / "fig4_data.json").unlink()
    (out / "arm_b_raw.jsonl").unlink()  # Arm B never got written

    experiment.run_experiment(
        _config(ds), out_dir=out, call_fn=_boom_call, resolve_fn=_fake_resolve, now=_NOW, git_commit="def"
    )
    assert (out / "arm_a_raw.jsonl").read_text() == arm_a_before  # Arm A resumed, untouched
    assert len((out / "arm_b_raw.jsonl").read_text().splitlines()) == 4  # Arm B re-run: 2 q x 2 repeats
    fig = json.loads((out / "fig4_data.json").read_text())
    assert fig["biomapper"]["byte_identical"] is True


def test_partial_arm_a_is_not_silently_truncated(tmp_path: Path) -> None:
    """A partial/crashed arm_a_raw.jsonl (no fig4_data) must NOT be reopened in
    truncating 'w' mode -- the run fails loud and leaves the evidence intact."""
    ds = _dataset(tmp_path)
    out = tmp_path / "run"
    experiment.run_experiment(
        _config(ds), out_dir=out, call_fn=_fake_call, resolve_fn=_fake_resolve, now=_NOW, git_commit="abc"
    )
    (out / "fig4_data.json").unlink()
    full = (out / "arm_a_raw.jsonl").read_text().splitlines()
    partial = "\n".join(full[:3]) + "\n"  # drop the tail: an incomplete arm
    (out / "arm_a_raw.jsonl").write_text(partial)

    with pytest.raises(FileExistsError):
        experiment.run_experiment(
            _config(ds), out_dir=out, call_fn=_boom_call, resolve_fn=_fake_resolve, now=_NOW, git_commit="def"
        )
    # partial evidence left exactly as-is (not truncated to empty)
    assert (out / "arm_a_raw.jsonl").read_text() == partial


def test_resume_refuses_config_mismatch_even_when_row_count_matches(tmp_path: Path) -> None:
    """A retry whose config differs (here: different temperatures) but whose expected raw
    row count is identical must NOT resume -- resuming would splice mismatched data into
    one figure. It fails loud and leaves the raw evidence intact."""
    ds = _dataset(tmp_path)
    out = tmp_path / "run"
    experiment.run_experiment(
        _config(ds), out_dir=out, call_fn=_fake_call, resolve_fn=_fake_resolve, now=_NOW, git_commit="abc"
    )
    arm_a_before = (out / "arm_a_raw.jsonl").read_text()
    (out / "fig4_data.json").unlink()  # crash before fig4

    # Same shape (1 model x 2 temps x 2 queries x 2 repeats = 8 rows) but DIFFERENT temps.
    cfg_b = ExperimentConfig(
        dataset_path=ds,
        models=[ModelSpec(provider="openai", model_id="gpt-x", label="gpt")],
        temperatures=[0.1, 0.9],  # differs from the preserved run's [0.0, 0.7]
        n_repeats=2,
    )
    with pytest.raises(FileExistsError, match="config differs"):
        experiment.run_experiment(
            cfg_b, out_dir=out, call_fn=_boom_call, resolve_fn=_fake_resolve, now=_NOW, git_commit="def"
        )
    assert (out / "arm_a_raw.jsonl").read_text() == arm_a_before  # untouched


def test_resume_refuses_config_mismatch_on_seed(tmp_path: Path) -> None:
    """The seed is part of the run's identity: a seed change with the same row count must
    also refuse to resume (the manifest now pins the numeric seed)."""
    ds = _dataset(tmp_path)
    out = tmp_path / "run"
    cfg_a = ExperimentConfig(
        dataset_path=ds,
        models=[ModelSpec(provider="openai", model_id="gpt-x", label="gpt")],
        temperatures=[0.0, 0.7],
        n_repeats=2,
        seed=111,
    )
    experiment.run_experiment(cfg_a, out_dir=out, call_fn=_fake_call, resolve_fn=_fake_resolve, now=_NOW)
    (out / "fig4_data.json").unlink()
    cfg_b = cfg_a.model_copy(update={"seed": 222})
    with pytest.raises(FileExistsError, match="config differs"):
        experiment.run_experiment(cfg_b, out_dir=out, call_fn=_boom_call, resolve_fn=_fake_resolve, now=_NOW)


def test_relabel_native_temp_maps_opus_zero_to_none(tmp_path: Path) -> None:
    """The post-hoc helper maps a temperature-unsupported model's mislabeled temp=0.0
    group to native/None in a COMPLETED run, without re-running it."""
    from studies.tier3_determinism import relabel_native_temp

    ds = _dataset(tmp_path)
    out = tmp_path / "run"
    # Opus-class config, but simulate a run produced by the OLD arms.py: force temp 0.0
    # onto the raw calls + fig4 panel as if native had been mislabeled.
    opus = ModelSpec(
        provider="anthropic", model_id="claude-opus-x", label="opus-4.8", supports_temperature=False
    )
    cfg = ExperimentConfig(
        dataset_path=ds,
        models=[opus],
        temperatures=[0.0],
        n_repeats=2,
        run_arm_b=False,
    )
    experiment.run_experiment(cfg, out_dir=out, call_fn=_fake_call, now=_NOW, git_commit="abc")
    # new code already labels None; rewrite to 0.0 to reproduce an OLD-code artifact.
    raw = out / "arm_a_raw.jsonl"
    rows = [json.loads(x) for x in raw.read_text().splitlines() if x.strip()]
    for r in rows:
        r["temperature"] = 0.0
    raw.write_text("".join(json.dumps(r) + "\n" for r in rows))
    fig4_path = out / "fig4_data.json"
    fig = json.loads(fig4_path.read_text())
    for p in fig["arm_a"]:
        p["temperature"] = 0.0
    fig4_path.write_text(json.dumps(fig, indent=2))

    summary = relabel_native_temp.relabel_run(out)

    assert summary["labels"] == ["opus-4.8"]
    assert summary["relabeled_panels"] == 1
    fig_after = json.loads(fig4_path.read_text())
    assert all(p["temperature"] is None for p in fig_after["arm_a"])
    rows_after = [json.loads(x) for x in raw.read_text().splitlines() if x.strip()]
    assert all(r["temperature"] is None for r in rows_after)
    # originals backed up, not destroyed
    assert (out / "fig4_data.json.pre-relabel.bak").exists()
    assert (out / "arm_a_raw.jsonl.pre-relabel.bak").exists()


def test_relabel_refuses_in_progress_run(tmp_path: Path) -> None:
    """The helper refuses a run without fig4_data.json (in-progress / absent)."""
    from studies.tier3_determinism import relabel_native_temp

    out = tmp_path / "inprogress"
    out.mkdir()
    (out / "arm_a_raw.jsonl").write_text("")
    with pytest.raises(FileNotFoundError):
        relabel_native_temp.relabel_run(out)


def test_second_relabel_preserves_original_backup(tmp_path: Path) -> None:
    """A second relabel (for a different label) must NOT overwrite the .pre-relabel.bak
    created by the first -- the pristine ORIGINAL completed artifact must stay recoverable
    no matter how many relabels run."""
    from studies.tier3_determinism import relabel_native_temp

    out = tmp_path / "run"
    out.mkdir()
    # A completed run (fig4 present) with two models BOTH mislabeled at temp 0.0. The
    # helper reads only model_label/temperature, so minimal records suffice.
    orig_fig4 = {
        "arm_a": [
            {"model_label": "opus-4.8", "temperature": 0.0},
            {"model_label": "qwen3-8b", "temperature": 0.0},
        ]
    }
    (out / "fig4_data.json").write_text(json.dumps(orig_fig4))
    (out / "arm_a_raw.jsonl").write_text(
        json.dumps({"model_label": "opus-4.8", "temperature": 0.0})
        + "\n"
        + json.dumps({"model_label": "qwen3-8b", "temperature": 0.0})
        + "\n"
    )

    # First relabel opus, then (later) relabel qwen with an explicit --labels override.
    relabel_native_temp.relabel_run(out, labels=["opus-4.8"])
    relabel_native_temp.relabel_run(out, labels=["qwen3-8b"])

    # The backup still holds the PRISTINE original (both at 0.0), not the opus-relabeled copy.
    bak = json.loads((out / "fig4_data.json.pre-relabel.bak").read_text())
    assert {p["model_label"]: p["temperature"] for p in bak["arm_a"]} == {
        "opus-4.8": 0.0,
        "qwen3-8b": 0.0,
    }
    raw_bak = [json.loads(x) for x in (out / "arm_a_raw.jsonl.pre-relabel.bak").read_text().splitlines() if x.strip()]
    assert all(r["temperature"] == 0.0 for r in raw_bak)

    # The live artifact reflects BOTH relabels.
    cur = json.loads((out / "fig4_data.json").read_text())
    assert {p["model_label"]: p["temperature"] for p in cur["arm_a"]} == {
        "opus-4.8": None,
        "qwen3-8b": None,
    }
