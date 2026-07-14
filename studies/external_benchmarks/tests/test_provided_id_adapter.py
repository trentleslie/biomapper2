"""Provided-ID adapters — source-provided + target-held-out reshaping (offline)."""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from studies.external_benchmarks.adapters import provided_id as pv
from studies.external_benchmarks.config import (
    NCBI_GENE2ENSEMBL,
    PROVIDED_HAJJAR,
    PROVIDED_NCBI_GENE2ENSEMBL,
    PROVIDED_UNIPROT_IDMAPPING,
)

GENE2ENSEMBL_LINES = [
    "#tax_id\tGeneID\tEnsembl_gene_identifier\tRNA_nucleotide\tEnsembl_rna\tprotein_acc\tEnsembl_protein",
    "9606\t672\tENSG00000012048\tNM_007294.4\tENST1\tNP_009225.1\tENSP1",
    "10090\t12189\tENSMUSG00000017146\tNM_009764.3\tENST2\tNP_033894.3\tENSP2",  # mouse -> filtered
    "9606\t7157\tENSG00000141510\tNM_000546.6\tENST3\tNP_000537.3\tENSP3",
]


def test_backbone_reshape_source_provided_target_held_out():
    name_df = pd.DataFrame(
        {"gene_id": ["672", "7157"], "gold_ensembl": ["ENSEMBL:ENSG00000012048", "ENSEMBL:ENSG00000141510"]}
    )
    out = pv.build_provided_input_df(name_df, PROVIDED_NCBI_GENE2ENSEMBL)
    # the SOURCE id is the (only) provided column, bare local
    assert out[PROVIDED_NCBI_GENE2ENSEMBL.source_id_column].tolist() == ["672", "7157"]
    # the TARGET is held out verbatim and is NOT the provided source column (anti-trivial)
    assert PROVIDED_NCBI_GENE2ENSEMBL.source_id_column != "gold_ensembl"
    assert out["gold_ensembl"].tolist() == ["ENSEMBL:ENSG00000012048", "ENSEMBL:ENSG00000141510"]
    # an inert, empty placeholder name column (annotation_mode='none' never reads it)
    assert out[PROVIDED_NCBI_GENE2ENSEMBL.name_column].tolist() == ["", ""]


def test_hajjar_reshape_strips_chebi_prefix_to_bare_source():
    name_df = pd.DataFrame(
        {
            "metabolite_name": ["D-Glucose", "Ethanol"],
            "gold_chebi": ["CHEBI:4167", "CHEBI:16236"],
            "gold_inchikey": ["WQZGKKKJIJFFOK-GASJEMHNSA-N", "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"],
        }
    )
    out = pv.build_provided_input_df(name_df, PROVIDED_HAJJAR)
    # source = ChEBI (bare local, prefix stripped); target = held-out InChIKey (structure)
    assert out["chebi"].tolist() == ["4167", "16236"]
    assert out["gold_inchikey"].tolist() == ["WQZGKKKJIJFFOK-GASJEMHNSA-N", "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"]
    # the held-out target column is disjoint from the provided source column
    assert "gold_inchikey" != PROVIDED_HAJJAR.source_id_column


def test_load_provided_backbone_reuses_streaming_and_builds_card():
    bundle = pv.load_provided_backbone(
        iter(GENE2ENSEMBL_LINES),
        PROVIDED_NCBI_GENE2ENSEMBL,
        replace(NCBI_GENE2ENSEMBL, subsample_n=10),
    )
    df = bundle.input_df
    assert set(df["entrez"]) == {"672", "7157"}  # human rows, source provided
    card = bundle.card
    assert card["mode"] == "provided_id"
    assert card["annotation_mode"] == "none"
    assert card["provided_id_columns"] == ["entrez"]
    assert card["gold_target_columns"] == {"ENSEMBL": "gold_ensembl"}
    assert card["source_namespace"] == "NCBIGene"
    assert card["source_sha256"]  # pins the exact scored provided-ID subsample


def test_load_provided_hajjar_from_bytes():
    raw = b"Metabolite name,ChEBI ID,InChIKey,SMILES\n" b"Ethanol,CHEBI:16236,LFQSCWFLJHTTHZ-UHFFFAOYSA-N,CCO\n"
    bundle = pv.load_provided_hajjar(raw, PROVIDED_HAJJAR)
    assert bundle.input_df["chebi"].tolist() == ["16236"]
    assert bundle.input_df["gold_inchikey"].tolist() == ["LFQSCWFLJHTTHZ-UHFFFAOYSA-N"]
    assert bundle.card["gold_target_columns"] == {"INCHIKEY": "gold_inchikey"}


def test_uniprot_provided_holds_out_refseq_and_ensembl():
    name_df = pd.DataFrame(
        {
            "uniprotkb_ac": ["P38398"],
            "gold_refseq": ["RefSeq:NP_009225.1"],
            "gold_ensembl": ["ENSEMBL:ENSG00000012048"],
        }
    )
    out = pv.build_provided_input_df(name_df, PROVIDED_UNIPROT_IDMAPPING)
    assert out["uniprotkb"].tolist() == ["P38398"]
    assert "gold_refseq" in out.columns and "gold_ensembl" in out.columns
    assert "uniprotkb" not in ("gold_refseq", "gold_ensembl")


def test_persist_provided_subsample_roundtrips(tmp_path):
    bundle = pv.load_provided_backbone(
        iter(GENE2ENSEMBL_LINES), PROVIDED_NCBI_GENE2ENSEMBL, replace(NCBI_GENE2ENSEMBL, subsample_n=10)
    )
    path = pv.persist_subsample(bundle, tmp_path)
    assert path.name == "ncbi-gene2ensembl-provided-id_subsample.csv"
    reloaded = pd.read_csv(path, dtype=str, keep_default_na=False)
    assert pv.sha256_bytes(pv.subsample_csv_bytes(reloaded)) == bundle.card["source_sha256"]


def test_config_construction_fails_loud_on_target_in_provided():
    # The anti-trivial-100% invariant is enforced at config construction: a target column equal to
    # the provided source column is rejected outright, not silently scored as 100%.
    with pytest.raises(ValueError, match="anti-trivial|provided_id_columns|TARGET"):
        replace(PROVIDED_NCBI_GENE2ENSEMBL, gold_target_columns=(("NCBIGene", "entrez"),))


def test_config_construction_fails_loud_on_same_namespace_round_trip():
    with pytest.raises(ValueError, match="anti-trivial|round-trip|namespace"):
        replace(PROVIDED_HAJJAR, source_namespace="INCHIKEY")
