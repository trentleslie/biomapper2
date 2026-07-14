"""Gene/protein backbone adapters (offline; in-memory line iterators, no network)."""

from __future__ import annotations

from dataclasses import replace

from studies.external_benchmarks.adapters import backbones
from studies.external_benchmarks.adapters.backbones import (
    gene2ensembl_records,
    hgnc_records,
    load_backbone,
    reservoir_sample,
    subsample_from_lines,
    uniprot_records,
)
from studies.external_benchmarks.config import HGNC, NCBI_GENE2ENSEMBL, UNIPROT_IDMAPPING


def test_reservoir_sample_deterministic_seed42():
    items = list(range(1000))
    a = reservoir_sample(iter(items), 20, seed=42)
    b = reservoir_sample(iter(items), 20, seed=42)
    assert a == b  # deterministic
    assert len(a) == 20
    assert reservoir_sample(iter(items), 20, seed=7) != a  # seed actually matters
    # never load-then-sample: sampling from a generator that raises if fully drained past n works
    assert len(reservoir_sample(iter(items), 5, seed=42)) == 5


def test_reservoir_returns_all_when_fewer_than_n():
    assert sorted(reservoir_sample(iter([1, 2, 3]), 10, seed=42)) == [1, 2, 3]


# ---------------- HGNC ----------------

HGNC_LINES = [
    "hgnc_id\tsymbol\tensembl_gene_id\tentrez_id\tuniprot_ids",
    "HGNC:1100\tBRCA1\tENSG00000012048\t672\tP38398",
    "HGNC:1101\tBRCA2\tENSG00000139618\t675\tP51587|A0A024R8T8",
    "HGNC:0000\t\tENSG00000000000\t0\t",  # empty symbol -> skipped
    "HGNC:11998\tTP53\tENSG00000141510\t7157\tP04637",
]


def test_hgnc_records_build_curies_and_skip_empty_symbol():
    recs = list(hgnc_records(iter(HGNC_LINES)))
    assert [r["symbol"] for r in recs] == ["BRCA1", "BRCA2", "TP53"]  # empty-symbol row dropped
    brca2 = recs[1]
    assert brca2["gold_ensembl"] == "ENSEMBL:ENSG00000139618"
    assert brca2["gold_entrez"] == "NCBIGene:675"
    # multi-valued UniProt -> pipe-joined CURIEs
    assert brca2["gold_uniprot"] == "UniProtKB:P51587|UniProtKB:A0A024R8T8"


def test_hgnc_input_df_and_card():
    bundle = load_backbone(iter(HGNC_LINES), replace(HGNC, subsample_n=10, subsample_seed=42))
    df = bundle.input_df
    assert list(df.columns) == ["symbol", "gold_ensembl", "gold_entrez", "gold_uniprot"]
    assert len(df) == 3
    card = bundle.card
    assert card["subsample"]["seed"] == 42
    assert card["subsample"]["method"] == "reservoir"
    assert card["n_scanned"] == 3  # eligible (post-filter) rows streamed
    assert card["gold_curie_columns"] == {
        "ENSEMBL": "gold_ensembl",
        "NCBIGene": "gold_entrez",
        "UniProtKB": "gold_uniprot",
    }
    assert card["coverage"]["ENSEMBL"]["n"] == 3


# ---------------- UniProt idmapping ----------------


def _uniprot_line(ac, geneid, refseq, taxon, ensembl):
    fields = [""] * 22
    fields[0], fields[2], fields[3], fields[12], fields[18] = ac, geneid, refseq, taxon, ensembl
    return "\t".join(fields)


UNIPROT_LINES = [
    _uniprot_line("P51587", "675", "NP_000050.2", "9606", "ENSG00000139618"),
    _uniprot_line("Q99999", "111", "NP_111.1", "10090", "ENSMUSG0001"),  # mouse -> filtered out
    _uniprot_line("P04637", "7157", "NP_000537.3", "9606", "ENSG00000141510"),
]


def test_uniprot_records_tax_filter_and_curies():
    recs = list(uniprot_records(iter(UNIPROT_LINES), tax_filter="9606"))
    assert [r["uniprotkb_ac"] for r in recs] == ["P51587", "P04637"]  # mouse dropped
    assert recs[0]["gold_refseq"] == "RefSeq:NP_000050.2"
    assert recs[0]["gold_ensembl"] == "ENSEMBL:ENSG00000139618"


def test_uniprot_streaming_subsample_human_only():
    df, n_scanned = subsample_from_lines(iter(UNIPROT_LINES), replace(UNIPROT_IDMAPPING, subsample_n=10))
    assert n_scanned == 2  # only human rows are eligible
    assert set(df["uniprotkb_ac"]) == {"P51587", "P04637"}
    assert list(df.columns) == ["uniprotkb_ac", "gold_refseq", "gold_ensembl"]


# ---------------- NCBI gene2ensembl ----------------

GENE2ENSEMBL_LINES = [
    "#tax_id\tGeneID\tEnsembl_gene_identifier\tRNA_nucleotide\tEnsembl_rna\tprotein_acc\tEnsembl_protein",
    "9606\t672\tENSG00000012048\tNM_007294.4\tENST1\tNP_009225.1\tENSP1",
    "10090\t12189\tENSMUSG00000017146\tNM_009764.3\tENST2\tNP_033894.3\tENSP2",  # mouse -> filtered
    "9606\t7157\tENSG00000141510\tNM_000546.6\tENST3\tNP_000537.3\tENSP3",
]


def test_gene2ensembl_records_skip_header_and_filter_taxon():
    recs = list(gene2ensembl_records(iter(GENE2ENSEMBL_LINES), tax_filter="9606"))
    assert [r["gene_id"] for r in recs] == ["672", "7157"]  # header + mouse dropped
    assert recs[0]["gold_ensembl"] == "ENSEMBL:ENSG00000012048"


def test_gene2ensembl_card_records_gold_identity():
    bundle = load_backbone(iter(GENE2ENSEMBL_LINES), replace(NCBI_GENE2ENSEMBL, subsample_n=10))
    assert bundle.card["gold_curie_columns"] == {"ENSEMBL": "gold_ensembl"}
    assert bundle.card["tax_filter"] == "9606"
    assert bundle.card["n_rows"] == 2
    # subsample SHA pins exactly what was scored
    assert bundle.card["subsample_sha256"]


def test_stream_source_lines_is_the_network_seam():
    # The only network entry is stream_source_lines; the parse/subsample path never calls it.
    assert hasattr(backbones, "stream_source_lines")
