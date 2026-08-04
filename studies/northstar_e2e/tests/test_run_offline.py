from pathlib import Path

from studies.northstar_e2e import run


def test_default_run_dir_is_timestamped(tmp_path):
    d = run.default_run_dir(tmp_path)
    assert d.parent == tmp_path
    assert d.name.startswith("northstar_e2e_") and d.name.endswith("Z")


def test_orchestrate_runs_offline_and_saves(fake_mapper, fake_kestrel, fake_llm_fn, tmp_path):
    membership = {"C00031": ("map00010",), "C00183": ("map00280",)}
    result = run.orchestrate(
        mapper=fake_mapper,
        kestrel=fake_kestrel,
        llm_fn=fake_llm_fn,
        membership=membership,
        out_dir=tmp_path / "run1",
        repo_root=tmp_path,
    )
    out = Path(result["out_dir"])
    assert (out / "manifest.json").exists()
    assert (out / "arm1_product.json").exists()
    assert (out / "validity.json").exists()
    assert "validity" in result
