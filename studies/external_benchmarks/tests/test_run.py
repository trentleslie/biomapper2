"""Orchestration fail-closed gates (offline; all live collaborators faked).

``run.orchestrate`` is the live driver — it normally needs Kestrel + network. These tests
patch every lazily-imported collaborator with in-memory fakes so the *decision logic* of the
integrity gates is exercised deterministically offline. They lock in the Greptile P1 fixes:

  - Unscorable primary (top1_accuracy is None) must REFUSE, never plot 0%.        (run.py:156)
  - A failed primary run must surface the recorded mapper error, not a KeyError.  (run.py:126)
  - The protocol-parity cell is REQUIRED to emit the competitor (S2) figure.       (run.py:116)
  - A URL --supplement must still be validated (source_df retained, not None).     (run.py:74)
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

import studies.external_benchmarks.run as run_mod
from studies.external_benchmarks.config import HAJJAR
from studies.external_benchmarks.runner import VocabRun


def _struct(top1: float | None):
    """Minimal structure-oracle result with a tunable ``comparable_core.top1_accuracy``."""
    return {
        "vocab": "CHEBI",
        "input_type": "name",
        "comparable_core": {
            "metric": "top1_accuracy",
            "top1_accuracy": top1,
            "correct": 0 if top1 is None else 1,
            "scored_denominator": 0 if top1 is None else 1,
        },
        "coverage": {"n_predicted": 1, "total": 1, "fraction": 1.0},
        "fallback_bucket": {"count": 0, "rows": []},
        "per_row": [],
    }


def _install_fakes(
    monkeypatch,
    tmp_path,
    *,
    runs: dict[str, VocabRun],
    struct_top1: float | None = 0.9,
    reconcile_ok: bool = True,
    validate_ok: bool = True,
    validate_calls: list | None = None,
    parse_raw_calls: list | None = None,
    fetch_calls: list | None = None,
):
    """Patch every collaborator ``orchestrate`` imports lazily with a controllable fake.

    The imports inside ``orchestrate`` (`from .runner import run_all`, etc.) resolve the
    attribute on the source module at call time, so patching the module attribute wins.
    """
    import studies.external_benchmarks.adapters.hajjar as hajjar_mod
    import studies.external_benchmarks.figures.competitor_panel as s2_mod
    import studies.external_benchmarks.figures.vocab_bar as s1_mod
    import studies.external_benchmarks.oracle as oracle_mod
    import studies.external_benchmarks.report.assemble as report_mod
    import studies.external_benchmarks.runner as runner_mod
    import studies.external_benchmarks.scorers.paper_metric as paper_mod
    import studies.external_benchmarks.scorers.structure_oracle_scorer as struct_mod
    import studies.external_benchmarks.validate as validate_mod
    import studies.external_benchmarks.verify as verify_mod

    # Heavy live deps: never construct the real Mapper / resolver / oracle.
    monkeypatch.setattr("biomapper2.mapper.Mapper", lambda *a, **k: SimpleNamespace(linker=object()))
    monkeypatch.setattr("biomapper2.core.structure_resolver.StructureResolver", lambda *a, **k: object())
    monkeypatch.setattr(oracle_mod, "KGStructureOracle", lambda *a, **k: object())

    input_df = pd.DataFrame({HAJJAR.name_column: ["D-Glucose"], HAJJAR.gold_chebi_column: ["CHEBI:4167"]})
    bundle = SimpleNamespace(input_df=input_df, card={"source_sha256": "deadbeef"})

    def _fetch(url):
        if fetch_calls is not None:
            fetch_calls.append(url)
        return b"FETCHED-BYTES"

    def _parse_raw(src):
        if parse_raw_calls is not None:
            parse_raw_calls.append(src)
        return pd.DataFrame({"Metabolite name": ["D-Glucose"]})

    monkeypatch.setattr(hajjar_mod, "fetch_supplement", _fetch)
    monkeypatch.setattr(hajjar_mod, "load_hajjar", lambda src, cfg: bundle)
    monkeypatch.setattr(hajjar_mod, "parse_raw", _parse_raw)

    monkeypatch.setattr(runner_mod, "run_all", lambda *a, **k: runs)
    monkeypatch.setattr(struct_mod, "score_structure_oracle", lambda *a, **k: _struct(struct_top1))
    monkeypatch.setattr(paper_mod, "score_paper_metric", lambda *a, **k: {"metric": "paper", "value": 0.5})
    monkeypatch.setattr(verify_mod, "reconcile", lambda *a, **k: SimpleNamespace(passed=reconcile_ok))

    def _validate_all(**kwargs):
        if validate_calls is not None:
            validate_calls.append(kwargs)
        return SimpleNamespace(passed=validate_ok, failures=[] if validate_ok else [{"check": "x"}])

    monkeypatch.setattr(validate_mod, "validate_all", _validate_all)

    monkeypatch.setattr(s1_mod, "render_s1", lambda *a, **k: {"figure": str(tmp_path / "S1.png")})
    monkeypatch.setattr(s2_mod, "render_s2", lambda *a, **k: {"figure": str(tmp_path / "S2.png")})
    monkeypatch.setattr(report_mod, "assemble_report", lambda **k: None)


def _ok_run(tmp_path, vocab: str) -> VocabRun:
    """A successful VocabRun backed by a real (tiny) MAPPED tsv on disk."""
    tsv = tmp_path / f"{vocab}_MAPPED.tsv"
    pd.DataFrame({HAJJAR.name_column: ["D-Glucose"], "chosen_kg_id": [f"{vocab}:1"]}).to_csv(
        tsv, sep="\t", index=False
    )
    return VocabRun(vocab=vocab, ok=True, output_tsv=str(tsv), stats={"mapped_to_kg_assigned": 1}, manifest={})


PARITY = (0.83, 0.84, 0.02)  # (reproduced, published, tolerance)


def test_failed_primary_surfaces_recorded_mapper_error_not_keyerror(monkeypatch, tmp_path):
    # Greptile P1 (run.py:126): the primary (CHEBI) run failed; scoring omits it. The old code
    # then hit an opaque KeyError at the figure stage. Fix: raise with the RECORDED mapper error.
    failed = VocabRun(
        vocab="CHEBI", ok=False, output_tsv=None, stats=None, manifest=None, error="Kestrel 503 on CHEBI"
    )
    _install_fakes(monkeypatch, tmp_path, runs={"CHEBI": failed})
    with pytest.raises(RuntimeError) as exc:
        run_mod.orchestrate(
            source=b"local-bytes", out_dir=tmp_path / "out", run_gate_first=False, published_parity_cell=PARITY
        )
    msg = str(exc.value)
    assert "CHEBI" in msg
    assert "Kestrel 503 on CHEBI" in msg  # the true cause, not a downstream KeyError
    assert "KeyError" not in type(exc.value).__name__


def test_missing_parity_cell_blocks_competitor_figure(monkeypatch, tmp_path):
    # Greptile P1 (run.py:116): without a reproduced published parity cell, S2 must not be
    # plotted. Normal CLI runs used to skip the gate and plot anyway.
    _install_fakes(monkeypatch, tmp_path, runs={"CHEBI": _ok_run(tmp_path, "CHEBI")}, struct_top1=0.9)
    with pytest.raises(RuntimeError, match="parity"):
        run_mod.orchestrate(
            source=b"local-bytes", out_dir=tmp_path / "out", run_gate_first=False, published_parity_cell=None
        )


def test_unscorable_primary_refuses_instead_of_plotting_zero(monkeypatch, tmp_path):
    # Greptile P1 (run.py:156): top1_accuracy is None (zero comparable rows). The old `or 0.0`
    # would plant a concrete "BioMapper 0%" bar beside published competitors. Must refuse.
    _install_fakes(monkeypatch, tmp_path, runs={"CHEBI": _ok_run(tmp_path, "CHEBI")}, struct_top1=None)
    with pytest.raises(RuntimeError, match="top1_accuracy is None|no scored rows"):
        run_mod.orchestrate(
            source=b"local-bytes", out_dir=tmp_path / "out", run_gate_first=False, published_parity_cell=PARITY
        )


def test_url_supplement_still_runs_validation(monkeypatch, tmp_path):
    # Greptile P1 (run.py:74): a URL --supplement used to leave source_df=None, so validate_all
    # skipped every external-anchor check. Fix: fetch once and retain the source frame so URL and
    # local-file inputs validate identically.
    validate_calls: list = []
    fetch_calls: list = []
    _install_fakes(
        monkeypatch,
        tmp_path,
        runs={"CHEBI": _ok_run(tmp_path, "CHEBI")},
        struct_top1=0.9,
        validate_calls=validate_calls,
        fetch_calls=fetch_calls,
    )
    result = run_mod.orchestrate(
        source="https://example.org/hajjar_supplement.xlsx",  # URL path
        out_dir=tmp_path / "out",
        run_gate_first=False,
        published_parity_cell=PARITY,
    )
    assert fetch_calls == ["https://example.org/hajjar_supplement.xlsx"]  # URL was fetched
    assert len(validate_calls) == 1  # validation ran
    # The load-bearing assertion: the validation layer received a real source frame, not None,
    # so its external-anchor checks actually execute for URL inputs.
    assert validate_calls[0]["source_df"] is not None
    assert isinstance(validate_calls[0]["source_df"], pd.DataFrame)
    assert "out_dir" in result


def test_local_and_url_paths_validate_identically(monkeypatch, tmp_path):
    # Both a local bytes source and a URL source must hand validate_all a non-None source_df.
    for source in (b"local-bytes", "https://example.org/x.xlsx"):
        validate_calls: list = []
        _install_fakes(
            monkeypatch,
            tmp_path,
            runs={"CHEBI": _ok_run(tmp_path, "CHEBI")},
            struct_top1=0.9,
            validate_calls=validate_calls,
        )
        run_mod.orchestrate(
            source=source, out_dir=tmp_path / f"out_{isinstance(source, str)}", run_gate_first=False,
            published_parity_cell=PARITY,
        )
        assert validate_calls[0]["source_df"] is not None
