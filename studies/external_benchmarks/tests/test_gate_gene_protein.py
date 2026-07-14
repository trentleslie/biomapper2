"""Gene/protein Phase-0 smoke (offline; live observation injected)."""

from __future__ import annotations

from studies.external_benchmarks.gate import (
    GeneProteinObservation,
    run_gene_protein_gate,
)


def _obs(**overrides):
    base = dict(
        key_ok=True,
        kestrel_ok=True,
        per_symbol={
            "TP53": {"ENSEMBL", "NCBIGENE", "UNIPROTKB"},
            "BRCA1": {"ENSEMBL", "UNIPROTKB"},
        },
    )
    base.update(overrides)
    return GeneProteinObservation(**base)


def test_happy_path_all_symbols_reach_ensembl_and_uniprot():
    result = run_gene_protein_gate(lambda: _obs())
    assert result.passed
    assert result.verdict == "proceed"


def test_missing_uniprot_for_a_symbol_stops_and_names_it():
    # Cross-category symbol->UniProt is the flagged risk: a symbol with only Ensembl must STOP.
    obs = _obs(per_symbol={"TP53": {"ENSEMBL", "UNIPROTKB"}, "ORF1": {"ENSEMBL"}})
    result = run_gene_protein_gate(lambda: obs)
    assert not result.passed
    assert "ORF1" in result.reason
    assert "UNIPROTKB" in result.reason.upper()


def test_missing_ensembl_stops():
    obs = _obs(per_symbol={"TP53": {"NCBIGENE", "UNIPROTKB"}})
    result = run_gene_protein_gate(lambda: obs)
    assert not result.passed
    assert "ENSEMBL" in result.reason.upper()


def test_missing_key_stops():
    result = run_gene_protein_gate(lambda: _obs(key_ok=False))
    assert not result.passed
    assert "key" in result.reason.lower()


def test_kestrel_unreachable_stops():
    result = run_gene_protein_gate(lambda: _obs(kestrel_ok=False))
    assert not result.passed
    assert "kestrel" in result.reason.lower()


def test_empty_smoke_stops_no_fabrication():
    result = run_gene_protein_gate(lambda: _obs(per_symbol={}))
    assert not result.passed
    assert "empty" in result.reason.lower()
