"""NECS exemplar-set generator (Unit 8) — offline, synthetic fixtures."""

from __future__ import annotations

import json

import pandas as pd

from studies.external_benchmarks.report.necs_gold_exemplars import (
    build_exemplar_set,
    render_markdown,
    write_exemplar_report,
)

_CORTISONE = {
    "chemical_name": "cortisone", "gold_inchikey": "IWIJFUQFXLWZIA-UHFFFAOYAP",
    "gold_smiles": "C[C@]12CCC(=O)C=C1CCC1C2C(=O)C[C@]2(C)C1CCC2(O)C(=O)CO",
    "gold_inchikey_standard": "MFYSYFVPBJMHGN-ZPOLXVRWSA-N",
    "gold_smiles_standard": "C[C@@]12CCC(=O)C=C1CC[C@H]1[C@H]2C(=O)C[C@]2(C)[C@@H]1CCC2(O)C(=O)CO",
    "gold_formula": "C21H28O5",
}
_AGREE = {"chemical_name": "ethanol", "gold_inchikey": "LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
          "gold_smiles": "CCO", "gold_inchikey_standard": "LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
          "gold_smiles_standard": "CCO", "gold_formula": "C2H6O"}


def test_only_disagreements_become_exemplars():
    bundle = build_exemplar_set(pd.DataFrame([_CORTISONE, _AGREE]))
    names = [e["chemical_name"] for e in bundle["exemplars"]]
    assert names == ["cortisone"]  # the agreeing row is excluded
    assert bundle["summary"]["n_disagreements"] == 1


def test_exemplar_carries_both_candidates_and_kind():
    e = build_exemplar_set(pd.DataFrame([_CORTISONE]))["exemplars"][0]
    assert e["legacy_inchikey"] and e["modern_inchikey"]
    assert e["legacy_smiles"] and e["modern_smiles"]
    assert e["kind"] == "kind_a_bad_key" and e["arbiter"] == "modern"


def test_markdown_numbers_come_from_bundle_not_hardcoded():
    bundle = build_exemplar_set(pd.DataFrame([_CORTISONE]))
    md = render_markdown(bundle)
    assert f"**{bundle['summary']['n_disagreements']}**" in md
    assert "kind_a_bad_key" in md


def test_write_report_emits_json_and_markdown(tmp_path):
    bundle = build_exemplar_set(pd.DataFrame([_CORTISONE]))
    paths = write_exemplar_report(bundle, tmp_path)
    loaded = json.loads(open(paths["json"]).read())
    assert loaded["summary"]["n_disagreements"] == 1
    assert open(paths["markdown"]).read().startswith("# NECS gold-disagreement exemplar set")
