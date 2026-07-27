"""Offline re-score over a synthetic run dir — strict sanity guard + equivalence lift, fake judge."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from studies.external_benchmarks.config import METABOLITEANNOTATOR_POS
from studies.external_benchmarks.rescore_id_equivalence import rescore


class FakeJudge:
    def __init__(self, verdict=True):
        self._v = verdict

    def uci_equivalent(self, gold, pred):
        return self._v

    def block_equivalent(self, gold, pred):
        return self._v


def _write_run(tmp_path):
    # Minimal per-vocab mapped TSV: glucose gold HMDB, prediction CHEBI (divergent, right molecule).
    mode_dir = tmp_path / "metaboliteannotator" / "positive"
    mode_dir.mkdir(parents=True)
    df = pd.DataFrame([{
        METABOLITEANNOTATOR_POS.name_column: "glucose",
        "chosen_kg_id": "CHEBI:4167",
        "kg_equivalent_ids": "{}",
        METABOLITEANNOTATOR_POS.gold_id_column: "HMDB:HMDB0000122",
        METABOLITEANNOTATOR_POS.gold_smiles_column: "",
        "source_accession": "MTBLS1",
        "input_row_id": "MTBLS1::0",
    }])
    df.to_csv(mode_dir / "CHEBI_mapped.tsv", sep="\t", index=False)
    # Persisted strict result for the sanity guard (strict concordant == 0 here).
    (mode_dir / "name_hit_results.json").write_text(json.dumps({
        "id_concordance": {"scored": 1, "concordant": 0, "concordance_rate": 0.0},
    }))
    return tmp_path


def test_rescore_reports_strict_and_equivalence_lift(tmp_path):
    run_dir = _write_run(tmp_path)
    out = tmp_path / "out"
    summary = rescore(str(run_dir), str(out), judge=FakeJudge(verdict=True))
    pos = summary["positive"]
    assert pos["strict"]["concordant"] == 0            # strict unchanged
    assert pos["uci_equivalence"]["concordant"] == 1   # judge credits divergent row
    assert pos["inchikey_bridge"]["concordant"] == 1
    assert pos["strict_sanity_ok"] is True             # reproduces persisted strict number
    assert (out / "id_equivalence_rescore.json").exists()


def test_rescore_fails_loud_when_run_dir_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        rescore(str(tmp_path / "does-not-exist"), str(tmp_path / "out"), judge=FakeJudge())
