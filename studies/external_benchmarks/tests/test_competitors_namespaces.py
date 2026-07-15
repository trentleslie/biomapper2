"""Namespace mapping + CURIE-representation alignment (the fairness crux of the comparison)."""

from __future__ import annotations

from studies.external_benchmarks.competitors.namespaces import (
    BACKBONE_SOURCE_NAMESPACE,
    canonicalize_local,
    curies_to_equiv_cell,
    to_curie,
)


def test_backbone_source_namespaces_registered():
    assert BACKBONE_SOURCE_NAMESPACE["hgnc-complete-set"] == "SYMBOL"
    assert BACKBONE_SOURCE_NAMESPACE["uniprot-idmapping"] == "UniProtKB"
    assert BACKBONE_SOURCE_NAMESPACE["ncbi-gene2ensembl"] == "NCBIGene"


def test_canonicalize_strips_ensembl_version_suffix():
    # Gold Ensembl/RefSeq are unversioned; a tool's versioned id is aligned, not penalized.
    assert canonicalize_local("ENSEMBL", "ENSG00000139618.15") == "ENSG00000139618"
    assert canonicalize_local("RefSeq", "NP_009225.1") == "NP_009225"


def test_canonicalize_strips_uniprot_version_suffix():
    # g:Convert's UNIPROTSWISSPROT returns versioned accessions (P04637.307); gold is unversioned.
    # A UniProt accession never legitimately contains a ``.<digits>`` (isoforms use ``-N``).
    assert canonicalize_local("UniProtKB", "P04637.307") == "P04637"
    assert canonicalize_local("UniProtKB", "P38398") == "P38398"  # unversioned untouched
    assert canonicalize_local("UniProtKB", "P04637-2") == "P04637-2"  # isoform dash NOT stripped


def test_canonicalize_leaves_unversioned_namespaces_untouched():
    assert canonicalize_local("NCBIGene", "672") == "672"
    assert canonicalize_local("SYMBOL", "TP53") == "TP53"


def test_canonicalize_drops_sentinels():
    for sentinel in ["", "None", "nan", "-", "N/A", "null"]:
        assert canonicalize_local("ENSEMBL", sentinel) == ""


def test_to_curie_prefixes_with_canonical_namespace():
    assert to_curie("ENSEMBL", "ENSG00000012048") == "ENSEMBL:ENSG00000012048"
    assert to_curie("NCBIGene", "672") == "NCBIGene:672"


def test_to_curie_does_not_double_prefix():
    assert to_curie("UniProtKB", "UniProtKB:P38398") == "UniProtKB:P38398"


def test_to_curie_empty_for_sentinel():
    assert to_curie("ENSEMBL", "None") == ""


def test_curies_to_equiv_cell_groups_by_prefix_for_scorer():
    cell = curies_to_equiv_cell({"ENSEMBL:ENSG00000012048", "UniProtKB:P38398", "ENSEMBL:ENSG00000139618", ""})
    assert cell["ENSEMBL"] == ["ENSG00000012048", "ENSG00000139618"]  # sorted, deduped
    assert cell["UniProtKB"] == ["P38398"]
    assert "" not in cell
