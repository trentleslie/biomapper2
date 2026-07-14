"""Registry entries for the external-benchmarks study.

Hajjar-100 (metabolite, name input) was the merged vertical slice. This module adds the
deferred follow-on: the NECS Metabolon metabolite set (structure-oracle) and the three
gene/protein cross-reference backbones (HGNC, UniProt idmapping, NCBI gene2ensembl),
scored by CURIE equality. MetaBench is still deferred (license unconfirmed).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class RunnableConfig(Protocol):
    """The minimal surface the runner (Unit 2) consumes.

    Both the metabolite ``DatasetConfig`` and the gene/protein ``CurieDatasetConfig``
    satisfy this structurally, so ``runner.run_all`` drives either arm unchanged: the run
    mode is always name-only (``provided_id_columns=[]``, ``annotation_mode='all'``) with the
    gold held out for the scorer.

    Members are read-only (properties) so the frozen dataclasses — whose fields are immutable —
    match structurally.
    """

    @property
    def key(self) -> str: ...
    @property
    def arm(self) -> str: ...
    @property
    def entity_type(self) -> str: ...
    @property
    def input_type(self) -> str: ...
    @property
    def name_column(self) -> str: ...
    @property
    def target_vocabs(self) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class DatasetConfig:
    """A metabolite benchmark dataset registry entry.

    The ``gold_*`` columns are *held out* of the mapper input in every sense that
    matters: they are carried alongside the name query but ``provided_id_columns``
    is empty, so BioMapper never sees them. Only the scorers consume them.
    """

    key: str
    arm: str  # e.g. "metabolite"
    entity_type: str  # Biolink-standardizable entity type, e.g. "metabolite"
    input_type: str  # "name" — the unsolved regime this slice targets
    target_vocabs: tuple[str, ...]  # vocabs to map to; correctness always via InChIKey block
    name_column: str  # the query column handed to mapper.name_column
    gold_chebi_column: str  # held-out ground-truth ChEBI id ("" when the source ships none)
    gold_inchikey_column: str  # held-out curated InChIKey — the independent structure oracle
    gold_smiles_column: str | None  # optional; enables the RDKit second-source structure check
    source_doi: str
    source_url: str
    license: str
    # (namespace, held-out-column) pairs whose per-column presence is reported on the dataset
    # card. Used by the NECS adapter to characterize the source's partial external-ID annotation
    # (InChIKey ~53%, HMDB ~57%, KEGG ~32%, ...). Empty for Hajjar (uniform ChEBI+InChIKey).
    gold_coverage_columns: tuple[tuple[str, str], ...] = ()


# Hajjar et al. 2026, Metabolomics, DOI 10.1007/s11306-026-02404-w.
# Curated 100-metabolite human-plasma set with ChEBI ID + InChIKey ground truth.
HAJJAR = DatasetConfig(
    key="hajjar-100",
    arm="metabolite",
    entity_type="metabolite",
    input_type="name",
    # primary CHEBI; also HMDB/PUBCHEM/KEGG to fill S1. Correctness always via the
    # dataset-anchored InChIKey block, never via the target vocab identity.
    target_vocabs=("CHEBI", "HMDB", "PUBCHEM", "KEGG"),
    name_column="metabolite_name",
    gold_chebi_column="gold_chebi",
    gold_inchikey_column="gold_inchikey",
    gold_smiles_column="gold_smiles",
    source_doi="10.1007/s11306-026-02404-w",
    # Pinned at acquisition against the paper's supplement; exact URL/format resolved
    # by the adapter and the fetched bytes' SHA recorded on the dataset card.
    source_url="",
    license="See Hajjar et al. 2026 supplement terms (Springer).",
)


@dataclass(frozen=True)
class CompetitorResult:
    """A published competitor number transcribed from a paper table.

    Values are intentionally ``None`` until transcribed at run time from the source
    table — no number is fabricated here (Metabolon-96.5% scar). The ``doi`` and
    ``table_ref`` are load-bearing: ``validate.citation_spot_check`` refuses any
    competitor entry missing either, so an unciteable number cannot reach a figure.
    """

    tool: str
    metric: str  # native metric name, e.g. "conversion_accuracy"
    input_type: str  # "name" / "inchikey" / ... — Hajjar reports by input type
    value: float | None
    doi: str
    table_ref: str  # e.g. "Table 2, row CTS (name input)"


# The six ID-conversion services Hajjar benchmarks on the same 100-set (valid
# same-dataset comparison). Values are transcribed from the paper's table at run
# time; left None here so nothing unverified is baked into source control.
HAJJAR_DOI = HAJJAR.source_doi
HAJJAR_COMPETITOR_TABLE_REF = "Hajjar et al. 2026, conversion-accuracy table"
HAJJAR_COMPETITORS: tuple[CompetitorResult, ...] = tuple(
    CompetitorResult(
        tool=tool,
        metric="conversion_accuracy",
        input_type="name",
        value=None,
        doi=HAJJAR_DOI,
        table_ref=HAJJAR_COMPETITOR_TABLE_REF,
    )
    for tool in (
        "CTS",
        "MetaboAnalyst",
        "RaMP",
        "MetabolomicsWorkbench/RefMet",
        "PubChem Identifier Exchange",
        "MetaNetX",
    )
)


# Monti et al. 2026, GeroScience, DOI 10.1007/s11357-026-02174-2 (New England Centenarian
# Study). 1,495 plasma metabolites delivered by Metabolon; the supplement (MOESM5) ships the
# Metabolon CHEMICAL_NAME plus an *independent* curated InChIKey/SMILES column and partial
# external IDs (HMDB/KEGG/PubChem/CAS/ChemSpider/RefMet). The InChIKey column is the structure
# oracle — same discipline as Hajjar, no ChEBI ground truth is shipped, so gold_chebi_column="".
# Single target vocab (CHEBI): per the Hajjar calibration, chosen_kg_id is annotation-driven not
# vocab-steered, so one accuracy number per dataset is reported (no per-vocab axis).
NECS = DatasetConfig(
    key="necs-metabolon",
    arm="metabolite",
    entity_type="metabolite",
    input_type="name",
    target_vocabs=("CHEBI",),
    name_column="chemical_name",
    gold_chebi_column="",  # NECS ships no curated ChEBI; oracle is the InChIKey column
    gold_inchikey_column="gold_inchikey",
    gold_smiles_column="gold_smiles",
    source_doi="10.1007/s11357-026-02174-2",
    source_url=(
        "https://static-content.springer.com/esm/art%3A10.1007%2Fs11357-026-02174-2/"
        "MediaObjects/11357_2026_2174_MOESM5_ESM.xlsx"
    ),
    license="See Monti et al. 2026 (GeroScience, Springer) supplement terms.",
    gold_coverage_columns=(
        ("INCHIKEY", "gold_inchikey"),
        ("SMILES", "gold_smiles"),
        ("HMDB", "gold_hmdb"),
        ("KEGG", "gold_kegg"),
        ("PUBCHEM", "gold_pubchem"),
        ("CAS", "gold_cas"),
        ("CHEMSPIDER", "gold_chemspider"),
        ("REFMET", "gold_refmet"),
    ),
)


@dataclass(frozen=True)
class CurieDatasetConfig:
    """A gene/protein cross-reference backbone registry entry (CURIE-equality arm).

    There is no structure oracle for genes/proteins; correctness is CURIE equality between
    BioMapper's *assigned* cross-reference CURIEs and the backbone's authoritative held-out
    cross-refs. The run mode mirrors the metabolite arm: ``name_column`` is the source symbol/
    accession query, ``provided_id_columns=[]`` so the gold cross-refs are never shown to the
    mapper, and the ``curie_scorer`` consumes ``gold_curie_columns`` alone.

    Subsampling is deterministic (reservoir, seed pinned) and recorded on the card — the
    UniProt idmapping table is multi-GB and is streamed, never loaded-then-sampled.
    """

    key: str
    arm: str  # "gene" | "protein"
    entity_type: str  # Biolink entity type: "gene" | "protein"
    input_type: str  # "name" — source symbol/accession handed to the annotator
    name_column: str  # the query column (source-namespace symbol/accession)
    target_vocabs: tuple[str, ...]  # authoritative cross-ref namespaces (the gold targets)
    # (namespace, held-out-column) — the AUTHORITATIVE gold cross-ref columns, stated explicitly
    # so the gold-column identity is load-bearing and reviewable (not inferred at run time).
    gold_curie_columns: tuple[tuple[str, str], ...]
    source_label: str  # e.g. "HGNC complete set"
    source_url: str
    license: str
    subsample_n: int = 1500
    subsample_seed: int = 42
    tax_filter: str | None = None  # e.g. "9606" for human-only rows (NCBI/UniProt)


# HGNC complete set (genenames.org). Query = approved gene symbol; authoritative cross-refs
# = Ensembl gene / Entrez / UniProt. entity_type=gene.
HGNC = CurieDatasetConfig(
    key="hgnc-complete-set",
    arm="gene",
    entity_type="gene",
    input_type="name",
    name_column="symbol",
    target_vocabs=("ENSEMBL", "NCBIGene", "UniProtKB"),
    gold_curie_columns=(
        ("ENSEMBL", "gold_ensembl"),
        ("NCBIGene", "gold_entrez"),
        ("UniProtKB", "gold_uniprot"),
    ),
    source_label="HGNC complete set",
    source_url="https://storage.googleapis.com/public-download-files/hgnc/tsv/tsv/hgnc_complete_set.txt",
    license="HGNC data are freely available without restriction (genenames.org).",
)

# UniProt idmapping_selected.tab (multi-GB; streamed + reservoir-subsampled). Query = UniProtKB
# accession; authoritative cross-refs = RefSeq / Ensembl. entity_type=protein.
UNIPROT_IDMAPPING = CurieDatasetConfig(
    key="uniprot-idmapping",
    arm="protein",
    entity_type="protein",
    input_type="name",
    name_column="uniprotkb_ac",
    target_vocabs=("RefSeq", "ENSEMBL"),
    gold_curie_columns=(
        ("RefSeq", "gold_refseq"),
        ("ENSEMBL", "gold_ensembl"),
    ),
    source_label="UniProt idmapping_selected.tab",
    source_url=(
        "https://ftp.uniprot.org/pub/databases/uniprot/current_release/knowledgebase/"
        "idmapping/idmapping_selected.tab.gz"
    ),
    license="UniProt data are available under CC BY 4.0.",
    tax_filter="9606",  # human rows only (column 13, NCBI-taxon)
)

# NCBI gene2ensembl (ftp.ncbi.nlm.nih.gov). Query = Entrez GeneID; authoritative cross-ref =
# Ensembl gene. entity_type=gene.
NCBI_GENE2ENSEMBL = CurieDatasetConfig(
    key="ncbi-gene2ensembl",
    arm="gene",
    entity_type="gene",
    input_type="name",
    name_column="gene_id",
    target_vocabs=("ENSEMBL",),
    gold_curie_columns=(("ENSEMBL", "gold_ensembl"),),
    source_label="NCBI gene2ensembl",
    source_url="https://ftp.ncbi.nlm.nih.gov/gene/DATA/gene2ensembl.gz",
    license="NCBI Gene data are in the public domain.",
    tax_filter="9606",  # human rows only (tax_id column)
)


# The metabolite registry (structure-oracle arm). Hajjar remains the merged reference; NECS is
# the deferred follow-on added here.
REGISTRY: dict[str, DatasetConfig] = {HAJJAR.key: HAJJAR, NECS.key: NECS}

# The gene/protein registry (CURIE-equality arm). No published same-set competitor exists for
# any of these, so — unlike Hajjar — NO competitor figure is emitted for them (BioMapper-vs-
# reference only; nothing fabricated).
CURIE_REGISTRY: dict[str, CurieDatasetConfig] = {
    HGNC.key: HGNC,
    UNIPROT_IDMAPPING.key: UNIPROT_IDMAPPING,
    NCBI_GENE2ENSEMBL.key: NCBI_GENE2ENSEMBL,
}
