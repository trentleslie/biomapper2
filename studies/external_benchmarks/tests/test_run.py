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

from pathlib import Path
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


# ==================================================================================================
# Pham orchestration — the report must claim ONLY the PubChem cross-check that actually ran (integrity).
# ==================================================================================================


def _pham_result() -> dict:
    """A minimal Pham-shaped score result carrying every key the inline report reads."""
    stratum = {
        "ambiguous_subset": {"referent_membership_rate": 0.5, "member": 1, "scored_denominator": 2,
                             "ambiguous_min_referents": 2},
        "structural_precision": {"precision": 0.5, "member": 1, "predicted_denominator": 2},
    }
    return {
        "comparable_core": {"referent_membership_rate": 0.6, "member": 3, "scored_denominator": 5},
        "ambiguous_subset": {"referent_membership_rate": 0.5, "member": 2, "scored_denominator": 4,
                             "ambiguous_min_referents": 2},
        "structural_precision": {"precision": 0.75, "member": 3, "predicted_denominator": 4},
        "ambiguity": {"mean_gold_referents": 2.25, "collapse_rate": 1.0},
        "coverage": {"n_predicted": 5, "total": 6},
        "by_stratum": {"non_lipid": stratum, "lipid": stratum},
    }


def _install_pham_fakes(monkeypatch, tmp_path):
    """Fake every collaborator ``orchestrate_pham`` imports lazily; keep the crosscheck path real."""
    import studies.external_benchmarks.adapters.pham as pham_mod
    import studies.external_benchmarks.oracle as oracle_mod
    import studies.external_benchmarks.runner as runner_mod
    import studies.external_benchmarks.scorers.pham_scorer as pham_scorer_mod
    from studies.external_benchmarks.config import PHAM_DISAMBIGUATION as C

    monkeypatch.setattr("biomapper2.mapper.Mapper", lambda *a, **k: SimpleNamespace(linker=object()))
    monkeypatch.setattr("biomapper2.core.structure_resolver.StructureResolver", lambda *a, **k: object())
    monkeypatch.setattr(oracle_mod, "KGStructureOracle", lambda *a, **k: object())

    input_df = pd.DataFrame(
        {
            C.name_column: ["suc", "tmp"],
            C.gold_referent_inchikey_column: [
                "SUCCINATEBLOCK-AAAAAAAAAA-N|SUCROSEBLOCKXX-BBBBBBBBBB-N",
                "TMPBLOCKXXXXXX-EEEEEEEEEE-N|THYMIDINEMPXXX-FFFFFFFFFF-N",
            ],
            C.stratum_column: ["non_lipid", "non_lipid"],
        }
    )
    bundle = SimpleNamespace(input_df=input_df, card={"source_sha256": "deadbeef", "source_status": "resolved",
                                                      "strata": {}})
    monkeypatch.setattr(pham_mod, "load_pham", lambda src, cfg: bundle)
    monkeypatch.setattr(pham_mod, "subsample_within_strata", lambda df, cfg, **kw: (df, {"seed": 42}))
    monkeypatch.setattr(pham_mod, "persist_stratified_subsample", lambda df, key, out: str(out))

    tsv = tmp_path / "CHEBI_MAPPED.tsv"
    input_df.assign(chosen_kg_id=["CHEBI:1", "CHEBI:2"]).to_csv(tsv, sep="\t", index=False)
    vr = VocabRun(vocab="CHEBI", ok=True, output_tsv=str(tsv), stats={}, manifest={})
    monkeypatch.setattr(runner_mod, "run_all", lambda *a, **k: {"CHEBI": vr})
    monkeypatch.setattr(pham_scorer_mod, "score_pham_disambiguation", lambda *a, **k: _pham_result())


def test_pham_report_states_real_crosscheck_numbers(monkeypatch, tmp_path):
    # Integrity fix: the report may claim a PubChem cross-check ONLY with the numbers that actually ran.
    _install_pham_fakes(monkeypatch, tmp_path)
    seen: dict = {}

    def fake_crosscheck(name_to_blocks):
        seen["names"] = set(name_to_blocks)
        return {
            "suc": {"agrees": True, "metanetx_blocks": ["SUCCINATEBLOCK"], "pubchem_blocks": ["SUCCINATEBLOCK"]},
            "tmp": {"agrees": False, "metanetx_blocks": ["TMPBLOCKXXXXXX"], "pubchem_blocks": ["OTHER"]},
        }

    out = tmp_path / "out"
    result = run_mod.orchestrate_pham(
        source=b"raw", out_dir=out, run_gate_first=False, crosscheck_fn=fake_crosscheck
    )
    # The cross-check was fed the SCORED subsample's names (with non-empty referent sets).
    assert seen["names"] == {"suc", "tmp"}
    report = (out / "pham_report.md").read_text() if (out / "pham_report.md").exists() else \
        Path(result["report"]).read_text()
    # Real numbers appear; no unqualified "cross-checked against PubChem" claim.
    assert "2 scored names' MetaNetX referents: 1 agreed, 1 disagreed" in report
    assert "0 inconclusive" in report
    assert result["pubchem_crosscheck"] == {"n_checked": 2, "n_agree": 1, "n_disagree": 1, "n_inconclusive": 0}
    assert (out / "pubchem_crosscheck.json").exists()
    assert (out / "pubchem_crosscheck_summary.json").exists()


def test_pham_report_declares_crosscheck_not_run_when_skipped(monkeypatch, tmp_path):
    # When the cross-check is skipped, the report must SAY so — never assert a validation that didn't run.
    _install_pham_fakes(monkeypatch, tmp_path)
    out = tmp_path / "out"
    result = run_mod.orchestrate_pham(source=b"raw", out_dir=out, run_gate_first=False, run_crosscheck=False)
    report = Path(result["report"]).read_text()
    assert "PubChem-by-name cross-check: NOT RUN" in report
    assert "agreed," not in report  # no fabricated agreement numbers
    assert result["pubchem_crosscheck"] is None
    assert not (out / "pubchem_crosscheck.json").exists()


def _install_lmsd_fakes(monkeypatch, tmp_path, *, struct_result):
    """Fake every collaborator orchestrate_lmsd imports lazily, EXCEPT the capability floor gate
    (assert_capability_floor / capability_resolvability stay REAL so we exercise the enforcement)."""
    import studies.external_benchmarks.adapters.lmsd as lmsd_mod
    import studies.external_benchmarks.oracle as oracle_mod
    import studies.external_benchmarks.report.campaign as campaign_mod
    import studies.external_benchmarks.runner as runner_mod
    import studies.external_benchmarks.scorers.structure_oracle_scorer as struct_mod
    import studies.external_benchmarks.verify as verify_mod
    from studies.external_benchmarks.config import LMSD

    monkeypatch.setattr("biomapper2.mapper.Mapper", lambda *a, **k: SimpleNamespace(linker=object()))
    monkeypatch.setattr("biomapper2.core.structure_resolver.StructureResolver", lambda *a, **k: object())
    monkeypatch.setattr(oracle_mod, "KGStructureOracle", lambda *a, **k: object())

    input_df = pd.DataFrame({LMSD.name_column: ["PC 34:1"], LMSD.gold_inchikey_column: ["AAAAAAAAAAAAAA"]})
    bundle = SimpleNamespace(input_df=input_df, card={"subsample_sha256": "deadbeef"})
    monkeypatch.setattr(lmsd_mod, "load_lmsd", lambda src, cfg, **k: bundle)
    monkeypatch.setattr(lmsd_mod, "persist_subsample", lambda *a, **k: str(tmp_path / "sub.csv"))
    monkeypatch.setattr(runner_mod, "run_all", lambda *a, **k: {"CHEBI": _ok_run(tmp_path, "CHEBI")})
    monkeypatch.setattr(struct_mod, "score_structure_oracle", lambda *a, **k: struct_result)
    monkeypatch.setattr(verify_mod, "reconcile", lambda *a, **k: SimpleNamespace(passed=True, mismatches=[]))
    monkeypatch.setattr(campaign_mod, "assemble_campaign_report", lambda **k: "report")


def _lmsd_result(shorthand_fraction, *, with_regime=True):
    # Mirrors the PRODUCTION score_structure_oracle shape: coverage lives at the RESULT ROOT, and
    # comparable_core carries NO coverage sub-key. with_regime=False exercises the blended fallback.
    result = {
        "vocab": "CHEBI",
        "input_type": "name",
        "comparable_core": {
            "metric": "top1_accuracy",
            "top1_accuracy": 0.5,
            "correct": 1,
            "scored_denominator": 2,
        },
        "coverage": {"n_predicted": 5, "total": 100, "fraction": shorthand_fraction},
        "fallback_bucket": {"count": 0, "rows": []},
        "per_row": [],
    }
    if with_regime:
        result["by_name_source_regime"] = {
            "shorthand": {"coverage": {"fraction": shorthand_fraction, "n_predicted": 5, "total": 100}},
        }
    return result


def test_lmsd_below_capability_floor_fails_closed(monkeypatch, tmp_path):
    # LMSD is role="capability_regression" with regression_floor=0.90. A shorthand resolvability
    # below the floor means the Goslin lipid capability is missing/regressed — the run MUST fail
    # closed BEFORE persisting (a declared floor that is never enforced is dead config).
    _install_lmsd_fakes(monkeypatch, tmp_path, struct_result=_lmsd_result(0.05))
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="regression floor"):
        run_mod.orchestrate_lmsd(source=b"local-bytes", out_dir=out, run_gate_first=False)
    # The measured resolvability is recorded for provenance even when the gate trips.
    assert (out / "capability_regression.json").exists()


def test_lmsd_above_capability_floor_persists(monkeypatch, tmp_path):
    # Above the floor the capability is wired; the run proceeds and persists results.
    _install_lmsd_fakes(monkeypatch, tmp_path, struct_result=_lmsd_result(0.97))
    out = tmp_path / "out2"
    result = run_mod.orchestrate_lmsd(source=b"local-bytes", out_dir=out, run_gate_first=False)
    assert (out / "capability_regression.json").exists()
    assert (out / "CHEBI_results.json").exists()
    assert result["vocab"] == "CHEBI"


def test_lmsd_capability_gate_survives_missing_shorthand_regime(monkeypatch, tmp_path):
    # A production-shaped LMSD result with NO by_name_source_regime must NOT crash the capability
    # gate: the fallback reads blended coverage from the result root. Below-floor still fails closed
    # via ValueError, not a KeyError, and the provenance file is still written.
    _install_lmsd_fakes(monkeypatch, tmp_path, struct_result=_lmsd_result(0.05, with_regime=False))
    out = tmp_path / "out3"
    with pytest.raises(ValueError, match="regression floor"):
        run_mod.orchestrate_lmsd(source=b"local-bytes", out_dir=out, run_gate_first=False)
    assert (out / "capability_regression.json").exists()
