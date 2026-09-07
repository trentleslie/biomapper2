"""Unit 4 driver — the one pure helper (provided-id kwarg selection); the live loop is operator-gated."""

from __future__ import annotations

from studies.external_benchmarks.ab_lipid_oracle_run import _metagraph_fingerprint, provided_id_kwargs


def test_prefers_gold_inchikey_then_hmdb_then_pubchem():
    row = {"gold_inchikey": "FHQVHHIBKUMWTI-OTMQOFQ-N", "gold_hmdb": "HMDB0005320", "gold_pubchem": "5283496"}
    assert provided_id_kwargs(row) == {
        "inchikey": "FHQVHHIBKUMWTI-OTMQOFQ-N",
        "hmdb": "HMDB0005320",
        "pubchem": "5283496",
    }


def test_reads_arivale_style_columns_and_blanks_to_none():
    row = {"HMDB_ID": "HMDB0009784", "PubChem_ID": "", "gold_inchikey": ""}
    out = provided_id_kwargs(row)
    assert out["hmdb"] == "HMDB0009784" and out["pubchem"] is None and out["inchikey"] is None


def test_metagraph_fingerprint_is_stable_and_order_independent():
    a = {"graph": "kraken", "version": "2.0.1", "summary": {"nodes": 10, "edges": 20},
         "node_prefixes": {"CHEBI": 5, "HMDB": 3}, "knowledge_sources": {"a": 1, "b": 2}}
    b = {"knowledge_sources": {"b": 2, "a": 1}, "node_prefixes": {"HMDB": 3, "CHEBI": 5},
         "summary": {"edges": 20, "nodes": 10}, "version": "2.0.1", "graph": "kraken"}
    assert _metagraph_fingerprint(a) == _metagraph_fingerprint(b)  # key order must not matter
    assert _metagraph_fingerprint(a).startswith("mg:")


def test_metagraph_fingerprint_changes_when_graph_changes():
    base = {"graph": "kraken", "version": "2.0.1", "summary": {"nodes": 10, "edges": 20},
            "node_prefixes": {"CHEBI": 5}, "knowledge_sources": {"a": 1}}
    bumped_version = {**base, "version": "2.0.2"}
    grew_nodes = {**base, "node_prefixes": {"CHEBI": 6}}
    new_summary = {**base, "summary": {"nodes": 11, "edges": 20}}
    fp = _metagraph_fingerprint(base)
    # positive control: each redeploy-shaped change must move the fingerprint
    assert _metagraph_fingerprint(bumped_version) != fp
    assert _metagraph_fingerprint(grew_nodes) != fp
    assert _metagraph_fingerprint(new_summary) != fp


def test_metagraph_fingerprint_tolerates_missing_keys():
    # older builds may omit fields; must not raise and must stay stable for the empty payload
    assert _metagraph_fingerprint({}) == _metagraph_fingerprint({})
    assert _metagraph_fingerprint({"version": "x"}) != _metagraph_fingerprint({})
