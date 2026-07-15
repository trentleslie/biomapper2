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
    # Optional deterministic subsample for LARGE reference sets (RefMet ships >200k analytes).
    # ``None`` => load the full set (Hajjar/NECS/NIST). When set, the adapter STREAMS the source
    # and reservoir-subsamples ``subsample_n`` rows at ``subsample_seed``, then PERSISTS the exact
    # subsample beside the card — the source URL is a mutable "current release", so URL+seed+n
    # alone cannot reconstruct the scored subset (same discipline as the gene/protein backbones).
    subsample_n: int | None = None
    subsample_seed: int = 42
    # When True the load/subsample is restricted to rows carrying a gold InChIKey — the independent
    # structure oracle REQUIRES a held-out structure, and RefMet's bulk CSV is only ~17% InChIKey-
    # annotated, so an unfiltered sample would be mostly coverage-only (nothing to score).
    require_gold_structure: bool = False


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


# Fahy & Subramaniam 2020, Nat. Methods, DOI 10.1038/s41592-020-01009-y — RefMet, the
# Metabolomics Workbench reference nomenclature. The bulk CSV (databases/refmet/refmet_download.php)
# ships ``refmet_name`` + a crosswalk to ChEBI/HMDB/PubChem/KEGG/LipidMaps + ``inchi_key``. The
# InChIKey is the independent structure oracle; the crosswalk IDs are reported as coverage only.
# >200k analytes, so it is streamed + reservoir-subsampled (n=1500, seed 42) from the InChIKey-
# bearing population (``require_gold_structure`` — the oracle needs a held-out structure) and the
# exact subsample is persisted (the download URL is a mutable current release). The bulk CSV ships
# NO SMILES, so the charge-normalized variant neutralizes only the prediction side (gold falls back
# to the strict InChIKey block). No same-set competitor exists, so no competitor figure is drawn.
REFMET = DatasetConfig(
    key="refmet",
    arm="metabolite",
    entity_type="metabolite",
    input_type="name",
    target_vocabs=("CHEBI",),
    name_column="refmet_name",
    gold_chebi_column="",  # RefMet's chebi_id is a coverage crosswalk, not the oracle (InChIKey is)
    gold_inchikey_column="gold_inchikey",
    gold_smiles_column=None,  # bulk CSV ships no SMILES; charge-normalized uses the strict gold block
    source_doi="10.1038/s41592-020-01009-y",
    source_url="https://www.metabolomicsworkbench.org/databases/refmet/refmet_download.php",
    license="RefMet / Metabolomics Workbench data are freely available (metabolomicsworkbench.org).",
    subsample_n=1500,
    subsample_seed=42,
    require_gold_structure=True,
    gold_coverage_columns=(
        ("INCHIKEY", "gold_inchikey"),
        ("CHEBI", "gold_chebi"),
        ("HMDB", "gold_hmdb"),
        ("PUBCHEM", "gold_pubchem"),
        ("KEGG", "gold_kegg"),
        ("LIPIDMAPS", "gold_lipidmaps"),
    ),
)


# Mandal et al. 2025, Anal. Chem., DOI 10.1021/acs.analchem.4c05018 — NIST SRM 1950 / SRM1950-DB,
# 1,058 certified human-plasma metabolites (srm1950-data.wishartlab.com). The CSV ships HMDB_ID +
# NAME + SMILES; the INCHIKEY column is EMPTY in the delivery, so the independent structure oracle
# InChIKey is DERIVED from the certified SMILES (RDKit, deterministic, zero shared infra with
# BioMapper's resolver). Clinical-lab framing. Small enough to load in full (no subsample). Rows
# whose SMILES fails to parse (or is absent) are coverage-only — excluded from the accuracy
# denominator by the structure-oracle scorer. No same-set competitor, so no competitor figure.
SRM1950 = DatasetConfig(
    key="srm1950",
    arm="metabolite",
    entity_type="metabolite",
    input_type="name",
    target_vocabs=("CHEBI",),
    name_column="metabolite_name",
    gold_chebi_column="",  # SRM1950-DB ships no ChEBI; oracle is the (SMILES-derived) InChIKey
    gold_inchikey_column="gold_inchikey",
    gold_smiles_column="gold_smiles",
    source_doi="10.1021/acs.analchem.4c05018",
    source_url="https://srm1950-data.wishartlab.com/metabolites.csv",
    license="SRM1950-DB data are freely available (wishartlab.com); NIST SRM 1950 certified values.",
    gold_coverage_columns=(
        ("INCHIKEY", "gold_inchikey"),
        ("SMILES", "gold_smiles"),
        ("HMDB", "gold_hmdb"),
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


@dataclass(frozen=True)
class ProvidedIdDatasetConfig:
    """A provided-ID (identifier-input) benchmark registry entry.

    Unlike the name-input configs (``DatasetConfig`` / ``CurieDatasetConfig``), the SOURCE
    identifier is handed to BioMapper as a *provided id* (``provided_id_columns=[source_id_column]``)
    with ``annotation_mode='none'`` — no name-resolution, pure provided-ID equivalence expansion.
    The measurement is whether BioMapper's KG equivalence set for the source reaches the held-out
    TARGET cross-reference. This is the regime comparable to the incumbent ID-mapping tools; the
    bare-ID name-input path (``7525`` -> ``USZIPCODE:75254``, 0%) is the wrong path for ID inputs.

    ANTI-TRIVIAL-100% INVARIANT (enforced in ``__post_init__``, fail-loud): the scored TARGET must
    never be a provided column, and the source namespace must be DISJOINT from every target
    namespace. A target-in-provided (or same-namespace round-trip) config raises ``ValueError`` at
    construction rather than silently scoring a trivial 100%.
    """

    key: str
    arm: str  # "gene" | "protein" | "metabolite"
    entity_type: str  # Biolink entity type
    source_id_column: str  # the ONLY provided_id column — a normalizer-recognizable column name
    source_namespace: str  # canonical namespace of the source id (e.g. "NCBIGene", "CHEBI")
    name_column: str  # inert placeholder query column (unused under annotation_mode='none')
    # (namespace, held-out-column) — the HELD-OUT gold TARGET cross-refs (scorer-only, never provided)
    gold_target_columns: tuple[tuple[str, str], ...]
    target_vocabs: tuple[str, ...]  # target namespace(s) the KG equivalence set is expected to reach
    source_label: str
    source_url: str
    license: str
    input_type: str = "provided_id"
    annotation_mode: str = "none"  # pure provided-ID equivalence expansion (no name annotation)
    # Reuse hook: when the provided-ID set is derived from a name-input backbone bundle, these name
    # the source CurieDatasetConfig (for the streaming/subsample machinery) and which of its columns
    # supplies the source id. None for the Hajjar-derived metabolite anchor.
    backbone_source_key: str | None = None
    backbone_source_column: str | None = None

    def __post_init__(self) -> None:
        provided = {self.source_id_column}
        gold_cols = {col for _, col in self.gold_target_columns}
        overlap = provided & gold_cols
        if overlap:
            raise ValueError(
                f"{self.key}: anti-trivial-100% violation — held-out TARGET column(s) {sorted(overlap)} "
                f"are also in provided_id_columns ({sorted(provided)}). The gold target must NEVER be "
                f"provided; only the source is. Refusing to construct a config that would score 100%."
            )
        gold_ns = {ns.upper() for ns, _ in self.gold_target_columns}
        if self.source_namespace.upper() in gold_ns:
            raise ValueError(
                f"{self.key}: anti-trivial-100% violation — source namespace {self.source_namespace!r} "
                f"is also a TARGET namespace ({sorted(gold_ns)}). A same-namespace round-trip lets the "
                f"provided source id self-match the gold. Choose disjoint source/target namespaces."
            )


# Gene/protein provided-ID anchors. Source id -> held-out cross-ref, both reusing the backbone
# streaming/subsample machinery. Entrez -> Ensembl and UniProt -> RefSeq/Ensembl are the two
# ID->ID regimes directly comparable to the incumbent ID-mapping tools.
PROVIDED_NCBI_GENE2ENSEMBL = ProvidedIdDatasetConfig(
    key="ncbi-gene2ensembl-provided-id",
    arm="gene",
    entity_type="gene",
    source_id_column="entrez",  # normalizer alias of ncbigene; value = bare Entrez GeneID
    source_namespace="NCBIGene",
    name_column="query_placeholder",
    gold_target_columns=(("ENSEMBL", "gold_ensembl"),),
    target_vocabs=("ENSEMBL",),
    source_label=NCBI_GENE2ENSEMBL.source_label,
    source_url=NCBI_GENE2ENSEMBL.source_url,
    license=NCBI_GENE2ENSEMBL.license,
    backbone_source_key=NCBI_GENE2ENSEMBL.key,
    backbone_source_column=NCBI_GENE2ENSEMBL.name_column,  # "gene_id"
)

PROVIDED_UNIPROT_IDMAPPING = ProvidedIdDatasetConfig(
    key="uniprot-idmapping-provided-id",
    arm="protein",
    entity_type="protein",
    source_id_column="uniprotkb",  # normalizer vocab name; value = bare UniProtKB accession
    source_namespace="UniProtKB",
    name_column="query_placeholder",
    gold_target_columns=(("RefSeq", "gold_refseq"), ("ENSEMBL", "gold_ensembl")),
    target_vocabs=("RefSeq", "ENSEMBL"),
    source_label=UNIPROT_IDMAPPING.source_label,
    source_url=UNIPROT_IDMAPPING.source_url,
    license=UNIPROT_IDMAPPING.license,
    backbone_source_key=UNIPROT_IDMAPPING.key,
    backbone_source_column=UNIPROT_IDMAPPING.name_column,  # "uniprotkb_ac"
)

# Metabolite provided-ID anchor — a Hajjar Table-2 PARITY cell on IDENTIFIER inputs. Source =
# Hajjar's curated ChEBI id; target = the held-out gold InChIKey (structure). Chosen over a
# ChEBI->ChEBI round-trip precisely because round-trip is trivial (source ns == target ns, rejected
# by the invariant above): ChEBI -> InChIKey crosses namespaces and reproduces a defensible
# "conversion to InChIKey from a provided compound identifier" cell that the name-input Hajjar run
# could not anchor. See ``HAJJAR_PROVIDED_ID_PARITY_CELL`` for the exact published cell reference.
PROVIDED_HAJJAR = ProvidedIdDatasetConfig(
    key="hajjar-100-provided-id",
    arm="metabolite",
    entity_type="metabolite",
    source_id_column="chebi",  # normalizer vocab name; value = Hajjar's curated ChEBI id
    source_namespace="CHEBI",
    name_column="query_placeholder",
    gold_target_columns=(("INCHIKEY", HAJJAR.gold_inchikey_column),),
    target_vocabs=("INCHIKEY",),
    source_label="Hajjar et al. 2026 (provided-ID: ChEBI -> InChIKey)",
    source_url=HAJJAR.source_url,
    license=HAJJAR.license,
    backbone_source_key=None,
    backbone_source_column=HAJJAR.gold_chebi_column,  # "gold_chebi" supplies the source id
)


# The specific Hajjar Table-2 cell the metabolite provided-ID anchor reproduces. Following the
# CompetitorResult discipline (Metabolon-96.5% scar): ``value=None`` until transcribed from the
# paper at run time — no number is fabricated in source control. ``doi`` + ``table_ref`` are
# load-bearing so the parity cell is citeable.
HAJJAR_PROVIDED_ID_PARITY_CELL = CompetitorResult(
    tool="Hajjar Table 2 (ID-input regime)",
    metric="conversion_accuracy_to_inchikey",
    input_type="provided_id",
    value=None,  # transcribe the published cell at run time; do NOT bake an unverified number here
    doi=HAJJAR_DOI,
    table_ref=(
        "Hajjar et al. 2026, Table 2 — conversion accuracy to InChIKey from a provided compound "
        "identifier (ID-input regime; ChEBI source)"
    ),
)


# The metabolite registry (structure-oracle arm). Hajjar remains the merged reference; NECS was
# the first deferred follow-on; RefMet (Metabolomics Workbench reference nomenclature) and NIST
# SRM 1950 (certified clinical-plasma reference set) are added here. All four are name->structure,
# scored by the independent InChIKey oracle (strict + charge-normalized); none has a same-set
# competitor, so no competitor figure is drawn for any of them.
REGISTRY: dict[str, DatasetConfig] = {
    HAJJAR.key: HAJJAR,
    NECS.key: NECS,
    REFMET.key: REFMET,
    SRM1950.key: SRM1950,
}

# The gene/protein registry (CURIE-equality arm). No published same-set competitor exists for
# any of these, so — unlike Hajjar — NO competitor figure is emitted for them (BioMapper-vs-
# reference only; nothing fabricated).
CURIE_REGISTRY: dict[str, CurieDatasetConfig] = {
    HGNC.key: HGNC,
    UNIPROT_IDMAPPING.key: UNIPROT_IDMAPPING,
    NCBI_GENE2ENSEMBL.key: NCBI_GENE2ENSEMBL,
}

# The provided-ID (identifier-input) registry — BioMapper's core cross-namespace-mapping regime,
# comparable to the incumbent ID-mapping tools. Every entry provides ONLY the source id and holds
# the target cross-ref out for the scorer (invariant enforced in ``ProvidedIdDatasetConfig``).
PROVIDED_ID_REGISTRY: dict[str, ProvidedIdDatasetConfig] = {
    PROVIDED_NCBI_GENE2ENSEMBL.key: PROVIDED_NCBI_GENE2ENSEMBL,
    PROVIDED_UNIPROT_IDMAPPING.key: PROVIDED_UNIPROT_IDMAPPING,
    PROVIDED_HAJJAR.key: PROVIDED_HAJJAR,
}

# Maps each provided-ID dataset to the source CurieDatasetConfig whose streaming/subsample machinery
# it reuses (None for the Hajjar-derived metabolite anchor, which reuses the Hajjar adapter instead).
PROVIDED_ID_BACKBONE: dict[str, CurieDatasetConfig | None] = {
    PROVIDED_NCBI_GENE2ENSEMBL.key: NCBI_GENE2ENSEMBL,
    PROVIDED_UNIPROT_IDMAPPING.key: UNIPROT_IDMAPPING,
    PROVIDED_HAJJAR.key: None,
}
