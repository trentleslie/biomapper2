"""Gene/protein Phase-0 smoke (offline).

Two layers:
  1. Gate decision logic — hand-built ``GeneProteinObservation``s (per-vocab ``VocabProbe``s)
     exercise the per-target-call coverage floor, non-gated-failure isolation, and Kestrel-down.
  2. Batch-path wiring — ``build_live_gene_protein_smoke_fn`` over a FAKE mapper proves the smoke
     observes the same ``map_dataset_to_kg`` batch path the arm runs on, keeps each vocab call's
     results isolated, and lets the gate PROCEED / STOP correctly (including the two Greptile PR #18
     edge cases: coverage must come from a namespace's own target call, and a non-gated call's
     exception must not abort the gate).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from studies.external_benchmarks.gate import (
    GeneProteinObservation,
    VocabProbe,
    build_live_gene_protein_smoke_fn,
    run_gene_protein_gate,
)


def _probe(per_symbol, ok=True):
    return VocabProbe(ok=ok, per_symbol=per_symbol)


def _obs(**overrides):
    """A healthy default: the ENSEMBL call covers Ensembl, the UniProtKB call covers UniProt."""
    base = dict(
        key_ok=True,
        kestrel_ok=True,
        per_vocab={
            "ENSEMBL": _probe({"TP53": {"ENSEMBL", "NCBIGENE"}, "BRCA1": {"ENSEMBL"}}),
            "UniProtKB": _probe({"TP53": {"UNIPROTKB"}, "BRCA1": {"UNIPROTKB", "NCBIGENE"}}),
            "NCBIGene": _probe({"TP53": {"NCBIGENE"}, "BRCA1": {"NCBIGENE"}}),
        },
    )
    base.update(overrides)
    return GeneProteinObservation(**base)


# --- gate decision logic (per-target-call coverage floor) ----------------------------------------


def test_happy_path_all_symbols_reach_ensembl_and_uniprot():
    result = run_gene_protein_gate(lambda: _obs())
    assert result.passed
    assert result.verdict == "proceed"


def test_partial_coverage_within_floor_proceeds():
    # NOT per-symbol all-or-nothing: 4/5 symbols reach each namespace in its own target call
    # (80% >= 60% floor), so the batch arm proceeds — the single-entity path used to STOP here.
    obs = _obs(
        per_vocab={
            "ENSEMBL": _probe(
                {
                    "TP53": {"ENSEMBL"},
                    "BRCA1": {"ENSEMBL"},
                    "EGFR": {"ENSEMBL"},
                    "INS": {"ENSEMBL"},
                    "TNF": {"NCBIGENE"},
                }  # noqa: E501
            ),
            "UniProtKB": _probe(
                {
                    "TP53": {"UNIPROTKB"},
                    "BRCA1": {"UNIPROTKB"},
                    "EGFR": {"UNIPROTKB"},
                    "INS": {"UNIPROTKB"},
                    "TNF": {"NCBIGENE"},
                }  # noqa: E501
            ),
            "NCBIGene": _probe({s: {"NCBIGENE"} for s in ("TP53", "BRCA1", "EGFR", "INS", "TNF")}),
        }
    )
    result = run_gene_protein_gate(lambda: obs)
    assert result.passed


def test_uniprot_below_floor_stops_and_names_namespace():
    obs = _obs(
        per_vocab={
            "ENSEMBL": _probe({s: {"ENSEMBL"} for s in ("TP53", "BRCA1", "EGFR", "INS", "TNF")}),
            "UniProtKB": _probe(
                {"TP53": {"UNIPROTKB"}, "BRCA1": {"NCBIGENE"}, "EGFR": set(), "INS": {"NCBIGENE"}, "TNF": set()}
            ),
            "NCBIGene": _probe({s: {"NCBIGENE"} for s in ("TP53", "BRCA1", "EGFR", "INS", "TNF")}),
        }
    )
    result = run_gene_protein_gate(lambda: obs)
    assert not result.passed
    assert "UNIPROTKB" in result.reason.upper()
    assert "20%" in result.reason


def test_zero_ensembl_stops():
    obs = _obs(
        per_vocab={
            "ENSEMBL": _probe({"TP53": {"NCBIGENE"}, "BRCA1": {"NCBIGENE"}}),
            "UniProtKB": _probe({"TP53": {"UNIPROTKB"}, "BRCA1": {"UNIPROTKB"}}),
        }
    )
    result = run_gene_protein_gate(lambda: obs)
    assert not result.passed
    assert "ENSEMBL" in result.reason.upper()


def test_ensembl_floor_only_counted_from_ensembl_target_call():
    # Finding #1 (decision-logic level): the ENSEMBL-target call produced NO Ensembl, but the
    # UniProtKB call happens to expose Ensembl equivalents. The gate MUST STOP — Ensembl coverage
    # is read only from the ENSEMBL call, never merged from another vocab's call.
    obs = _obs(
        per_vocab={
            "ENSEMBL": _probe({"TP53": {"NCBIGENE"}, "BRCA1": {"NCBIGENE"}}),  # broken Ensembl call
            "UniProtKB": _probe({"TP53": {"UNIPROTKB", "ENSEMBL"}, "BRCA1": {"UNIPROTKB", "ENSEMBL"}}),
            "NCBIGene": _probe({"TP53": {"NCBIGENE", "ENSEMBL"}, "BRCA1": {"NCBIGENE", "ENSEMBL"}}),
        }
    )
    result = run_gene_protein_gate(lambda: obs)
    assert not result.passed
    assert "ENSEMBL" in result.reason.upper()


def test_nongated_call_failure_proceeds():
    # Finding #2 (decision-logic level): the non-gated NCBIGene call threw (ok=False) but both gated
    # calls are healthy — proceed.
    obs = _obs(
        per_vocab={
            "ENSEMBL": _probe({"TP53": {"ENSEMBL"}, "BRCA1": {"ENSEMBL"}}),
            "UniProtKB": _probe({"TP53": {"UNIPROTKB"}, "BRCA1": {"UNIPROTKB"}}),
            "NCBIGene": _probe({"TP53": set(), "BRCA1": set()}, ok=False),
        }
    )
    result = run_gene_protein_gate(lambda: obs)
    assert result.passed


def test_gated_call_failure_stops():
    # The complement of finding #2: a GATED call failing means we cannot judge that namespace -> STOP.
    obs = _obs(
        per_vocab={
            "ENSEMBL": _probe({"TP53": set(), "BRCA1": set()}, ok=False),
            "UniProtKB": _probe({"TP53": {"UNIPROTKB"}, "BRCA1": {"UNIPROTKB"}}),
            "NCBIGene": _probe({"TP53": {"NCBIGENE"}, "BRCA1": {"NCBIGENE"}}),
        }
    )
    result = run_gene_protein_gate(lambda: obs)
    assert not result.passed
    assert "ENSEMBL" in result.reason.upper()
    assert "failed" in result.reason.lower()


def test_missing_key_stops():
    result = run_gene_protein_gate(lambda: _obs(key_ok=False))
    assert not result.passed
    assert "key" in result.reason.lower()


def test_kestrel_unreachable_stops():
    result = run_gene_protein_gate(lambda: _obs(kestrel_ok=False))
    assert not result.passed
    assert "kestrel" in result.reason.lower()


def test_empty_smoke_stops_no_fabrication():
    result = run_gene_protein_gate(lambda: _obs(per_vocab={}))
    assert not result.passed
    assert "empty" in result.reason.lower()


# --- batch-path wiring (fake mapper over the map_dataset_to_kg path) -----------------------------


class _BatchFakeMapper:
    """Fake mapper exercising the BATCH ``map_dataset_to_kg`` path, per vocab.

    ``equiv_by_vocab`` maps each queried vocab -> {symbol -> ``kg_equivalent_ids`` dict
    ``{namespace: [local_id, ...]}``} — exactly the shape ``curie_scorer.predicted_curies`` parses.
    ``chosen_kg_id`` is always an NCBIGene id (the same-category free cross-ref), so the Ensembl/
    UniProt coverage the gate checks comes solely from each call's equivalent-id map, as it does live.
    Vocabs in ``raise_on_vocab`` throw, simulating a per-call failure.
    """

    def __init__(self, equiv_by_vocab, raise_on_vocab=()):
        self.equiv_by_vocab = equiv_by_vocab
        self.raise_on_vocab = set(raise_on_vocab)
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
        if vocab in self.raise_on_vocab:
            raise RuntimeError(f"simulated Kestrel failure for vocab {vocab}")
        equiv_map = self.equiv_by_vocab.get(vocab, {})
        rows = []
        for sym in dataset[name_column]:
            equiv = equiv_map.get(sym, {})
            rows.append({name_column: sym, "chosen_kg_id": f"NCBIGene:{sym}", "kg_equivalent_ids": repr(equiv)})
        out = Path(output_dir) / f"{output_prefix}_MAPPED.tsv"
        pd.DataFrame(rows).to_csv(out, sep="\t", index=False)
        return str(out), {"mapped_to_kg_assigned": len(rows)}


_SYMBOLS = ("TP53", "BRCA1", "EGFR", "INS", "TNF")


def _full_crossrefs():
    """Every vocab call returns Ensembl + UniProt equivalents for every symbol."""
    per_symbol = {s: {"ENSEMBL": [f"ENSG_{s}"], "UNIPROTKB": [f"P_{s}"]} for s in _SYMBOLS}
    return {v: per_symbol for v in ("ENSEMBL", "NCBIGene", "UniProtKB")}


def _patch_key(monkeypatch):
    import biomapper2.config as bcfg

    monkeypatch.setattr(bcfg, "get_kestrel_api_key", lambda: "fake-key")


def test_batch_path_with_crossrefs_proceeds(monkeypatch):
    _patch_key(monkeypatch)
    mapper = _BatchFakeMapper(_full_crossrefs())
    smoke = build_live_gene_protein_smoke_fn(mapper, symbols=_SYMBOLS)
    result = run_gene_protein_gate(smoke)
    assert result.passed
    # ran the BATCH path (one call per vocab), name-only (gold never provided)
    assert mapper.vocab_calls == ["ENSEMBL", "NCBIGene", "UniProtKB"]
    assert all(cols == [] for cols in mapper.provided_id_columns_seen)
    # observed the cross-refs from the ENSEMBL call's own equivalent-id map, not just NCBIGene
    assert result.observation.per_vocab["ENSEMBL"].per_symbol["TP53"] >= {"ENSEMBL", "UNIPROTKB", "NCBIGENE"}


def test_batch_path_only_ncbigene_stops(monkeypatch):
    # Reproduces the OLD single-entity failure mode: batch returns only NCBIGene, no cross-refs.
    # The gate MUST still STOP (fail-loud) — the fix is not a no-op.
    _patch_key(monkeypatch)
    mapper = _BatchFakeMapper({v: {s: {} for s in _SYMBOLS} for v in ("ENSEMBL", "NCBIGene", "UniProtKB")})
    smoke = build_live_gene_protein_smoke_fn(mapper, symbols=_SYMBOLS)
    result = run_gene_protein_gate(smoke)
    assert not result.passed
    assert "ENSEMBL" in result.reason.upper() or "UNIPROTKB" in result.reason.upper()


def test_batch_ensembl_floor_not_satisfied_by_other_vocabs_equivalents(monkeypatch):
    # Finding #1 (end-to-end): the ENSEMBL-target call returns NO Ensembl, but the UniProtKB and
    # NCBIGene calls do expose Ensembl equivalents. Merging would falsely proceed; per-target-call
    # coverage STOPs, naming Ensembl.
    _patch_key(monkeypatch)
    equiv_by_vocab = {
        "ENSEMBL": {s: {} for s in _SYMBOLS},  # broken Ensembl-target call: only NCBIGene chosen
        "UniProtKB": {s: {"UNIPROTKB": [f"P_{s}"], "ENSEMBL": [f"ENSG_{s}"]} for s in _SYMBOLS},
        "NCBIGene": {s: {"ENSEMBL": [f"ENSG_{s}"]} for s in _SYMBOLS},
    }
    mapper = _BatchFakeMapper(equiv_by_vocab)
    smoke = build_live_gene_protein_smoke_fn(mapper, symbols=_SYMBOLS)
    result = run_gene_protein_gate(smoke)
    assert not result.passed
    assert "ENSEMBL" in result.reason.upper()
    # sanity: Ensembl DID surface in another call, proving the STOP is about the target call
    assert result.observation.per_vocab["UniProtKB"].per_symbol["TP53"] >= {"ENSEMBL"}


def test_batch_nongated_vocab_exception_proceeds(monkeypatch):
    # Finding #2 (end-to-end): the NCBIGene call throws, but Ensembl + UniProt calls are healthy.
    # A non-gated call's failure must not abort the gate.
    _patch_key(monkeypatch)
    mapper = _BatchFakeMapper(_full_crossrefs(), raise_on_vocab={"NCBIGene"})
    smoke = build_live_gene_protein_smoke_fn(mapper, symbols=_SYMBOLS)
    result = run_gene_protein_gate(smoke)
    assert result.passed
    assert result.observation.kestrel_ok is True
    assert result.observation.per_vocab["NCBIGene"].ok is False


def test_batch_all_calls_fail_kestrel_unreachable(monkeypatch):
    # If every call throws, Kestrel is genuinely unreachable -> STOP fail-loud.
    _patch_key(monkeypatch)
    mapper = _BatchFakeMapper(_full_crossrefs(), raise_on_vocab={"ENSEMBL", "NCBIGene", "UniProtKB"})
    smoke = build_live_gene_protein_smoke_fn(mapper, symbols=_SYMBOLS)
    result = run_gene_protein_gate(smoke)
    assert not result.passed
    assert "kestrel" in result.reason.lower()
