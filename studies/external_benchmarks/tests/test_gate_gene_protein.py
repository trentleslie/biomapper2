"""Gene/protein Phase-0 smoke (offline).

Two layers:
  1. Gate decision logic — hand-built ``GeneProteinObservation``s exercise the per-namespace
     coverage floor (proceed / stop), independent of any mapper.
  2. Batch-path wiring — ``build_live_gene_protein_smoke_fn`` over a FAKE mapper proves the smoke
     observes the same ``map_dataset_to_kg`` batch path the arm runs on, so the gate PROCEEDs when
     the batch returns Ensembl/UniProt cross-refs and STOPs when it returns only NCBIGene (the exact
     false-negative the single-entity path used to produce).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from studies.external_benchmarks.gate import (
    GeneProteinObservation,
    build_live_gene_protein_smoke_fn,
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


# --- gate decision logic (per-namespace coverage floor) -----------------------------------------


def test_happy_path_all_symbols_reach_ensembl_and_uniprot():
    result = run_gene_protein_gate(lambda: _obs())
    assert result.passed
    assert result.verdict == "proceed"


def test_partial_coverage_within_floor_proceeds():
    # The key fix: it is NOT per-symbol all-or-nothing. 4/5 symbols reach each required namespace
    # (80% >= 60% floor), so the batch arm proceeds — the single-entity path used to STOP here.
    obs = _obs(
        per_symbol={
            "TP53": {"ENSEMBL", "NCBIGENE", "UNIPROTKB"},
            "BRCA1": {"ENSEMBL", "UNIPROTKB"},
            "EGFR": {"ENSEMBL", "UNIPROTKB"},
            "INS": {"ENSEMBL", "UNIPROTKB"},
            "TNF": {"NCBIGENE"},  # this one missed both cross-refs; still above the floor overall
        }
    )
    result = run_gene_protein_gate(lambda: obs)
    assert result.passed


def test_uniprot_below_floor_stops_and_names_namespace():
    # Cross-category symbol->UniProt is the flagged risk: if the batch path resolves UniProt for
    # too few symbols (here 1/5 = 20% < 60%), STOP and name UniProt + the observed rate.
    obs = _obs(
        per_symbol={
            "TP53": {"ENSEMBL", "UNIPROTKB"},
            "BRCA1": {"ENSEMBL", "NCBIGENE"},
            "EGFR": {"ENSEMBL"},
            "INS": {"ENSEMBL", "NCBIGENE"},
            "TNF": {"ENSEMBL"},
        }
    )
    result = run_gene_protein_gate(lambda: obs)
    assert not result.passed
    assert "UNIPROTKB" in result.reason.upper()
    assert "20%" in result.reason


def test_zero_ensembl_stops():
    obs = _obs(per_symbol={"TP53": {"NCBIGENE", "UNIPROTKB"}, "BRCA1": {"NCBIGENE", "UNIPROTKB"}})
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


# --- batch-path wiring (fake mapper over the map_dataset_to_kg path) -----------------------------


class _BatchFakeMapper:
    """Fake mapper exercising the BATCH ``map_dataset_to_kg`` path.

    ``equiv_by_symbol`` maps each probe symbol to a ``kg_equivalent_ids`` dict
    ``{namespace: [local_id, ...]}`` — exactly the shape ``curie_scorer.predicted_curies`` parses.
    ``chosen_kg_id`` is always an NCBIGene id (the same-category free cross-ref), so the Ensembl/
    UniProt coverage the gate checks comes solely from the equivalent-id map, as it does live.
    """

    def __init__(self, equiv_by_symbol: dict[str, dict[str, list[str]]]):
        self.equiv_by_symbol = equiv_by_symbol
        self.vocab_calls: list[str] = []
        self.provided_id_columns_seen: list[list[str]] = []

    def map_dataset_to_kg(
        self,
        *,
        dataset,
        entity_type,
        name_column,
        provided_id_columns,
        vocab,
        annotation_mode,
        output_dir,
        output_prefix,
    ):
        self.vocab_calls.append(vocab)
        self.provided_id_columns_seen.append(list(provided_id_columns))
        rows = []
        for sym in dataset[name_column]:
            equiv = self.equiv_by_symbol.get(sym, {})
            rows.append(
                {name_column: sym, "chosen_kg_id": f"NCBIGene:{sym}", "kg_equivalent_ids": repr(equiv)}
            )
        out = Path(output_dir) / f"{output_prefix}_MAPPED.tsv"
        pd.DataFrame(rows).to_csv(out, sep="\t", index=False)
        return str(out), {"mapped_to_kg_assigned": len(rows)}


def _patch_key(monkeypatch):
    import biomapper2.config as bcfg

    monkeypatch.setattr(bcfg, "get_kestrel_api_key", lambda: "fake-key")


def test_batch_path_with_crossrefs_proceeds(monkeypatch):
    _patch_key(monkeypatch)
    symbols = ("TP53", "BRCA1", "EGFR", "INS", "TNF")
    equiv = {
        s: {"ENSEMBL": [f"ENSG_{s}"], "UNIPROTKB": [f"P_{s}"]} for s in symbols
    }
    mapper = _BatchFakeMapper(equiv)
    smoke = build_live_gene_protein_smoke_fn(mapper, symbols=symbols)
    result = run_gene_protein_gate(smoke)
    assert result.passed
    # ran the BATCH path (one call per vocab), name-only (gold never provided)
    assert mapper.vocab_calls == ["ENSEMBL", "NCBIGene", "UniProtKB"]
    assert all(cols == [] for cols in mapper.provided_id_columns_seen)
    # observed the cross-refs from the equivalent-id map, not just NCBIGene
    assert result.observation.per_symbol["TP53"] >= {"ENSEMBL", "UNIPROTKB", "NCBIGENE"}


def test_batch_path_only_ncbigene_stops(monkeypatch):
    # Reproduces the OLD single-entity failure mode: batch returns only NCBIGene, no cross-refs.
    # The gate MUST still STOP (fail-loud) — the fix is not a no-op.
    _patch_key(monkeypatch)
    symbols = ("TP53", "BRCA1", "EGFR", "INS", "TNF")
    mapper = _BatchFakeMapper({s: {} for s in symbols})  # empty equiv -> only chosen NCBIGene
    smoke = build_live_gene_protein_smoke_fn(mapper, symbols=symbols)
    result = run_gene_protein_gate(smoke)
    assert not result.passed
    assert "ENSEMBL" in result.reason.upper() or "UNIPROTKB" in result.reason.upper()
