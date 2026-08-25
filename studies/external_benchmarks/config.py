"""Registry entries for the external-benchmarks study.

Hajjar-100 (metabolite, name input) was the merged vertical slice. This module adds the
deferred follow-on: the NECS Metabolon metabolite set (structure-oracle) and the three
gene/protein cross-reference backbones (HGNC, UniProt idmapping, NCBI gene2ensembl),
scored by CURIE equality. It also adds the MetaboliteAnnotator name-hit head-to-head (Lu et al.
2026) — a same-set, NAME-input regime scored by name-hit-rate against MetaboAnalyst 6.0 /
metaboliteIDmapping baselines. MetaBench (Lu et al. 2025, arXiv:2510.14944) is now wired in too —
its 1,000-pair cross-database Grounding set is the ONE external dataset with a valid LLM
head-to-head (25 published baselines on the same set).
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    # Benchmark ROLE. "accuracy" arms report an independent accuracy number; "capability_regression"
    # arms (LMSD post-Goslin) certify a capability is wired and gate a resolvability FLOOR — they are
    # NEVER reported as an accuracy headline. When role == "capability_regression", regression_floor
    # is the minimum shorthand resolvability the run must clear.
    role: str = "accuracy"
    regression_floor: float | None = None


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
        ("inchi_key", "gold_inchikey_standard"),
        ("smiles", "gold_smiles_standard"),
        ("formula", "gold_formula"),
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
    # The delivery's identifier column is deliberately absent: it was a row index in accession
    # clothing (see ``adapters.srm1950.RowIndexGoldColumnError``), so the identifier-based coverage
    # figure computed from it was an artefact of a synthetic column, not a resolver result. Dropped
    # rather than quarantined so it cannot be mistaken for gold by the next reader.
    gold_coverage_columns=(
        ("INCHIKEY", "gold_inchikey"),
        ("SMILES", "gold_smiles"),
    ),
)


# Liebisch et al. 2020, J. Lipid Res., DOI 10.1194/jlr.S120001025 — the LIPID MAPS shorthand
# nomenclature governing LMSD (the LIPID MAPS Structure Database). The bulk SDF download
# (lipidmaps.org/files/?file=LMSD&ext=sdf.zip, CC BY 4.0, ~50k curated records) ships a lipid
# shorthand ``ABBREVIATION`` + common ``NAME`` + ``SYSTEMATIC_NAME`` + ``INCHI_KEY`` + ``SMILES`` +
# a crosswalk to PubChem/HMDB/KEGG/ChEBI/SwissLipids. This targets BioMapper's KNOWN lipid weakness
# (NIST SRM 1950 lipids scored only 40.3%) with an honest gap-characterization on lipid NAME inputs.
#
# CONTAMINATION CONTROL: the query is a lipid NAME (shorthand/common/systematic) whose structure must
# be inferred; the ``LM_ID`` is HELD OUT — never a query, never the oracle. The Kestrel KG recognizes
# the LIPIDMAPS namespace (normalizer ``LM`` prefix), so scoring on LM_IDs would be circular; scoring
# on names forces BioMapper to resolve structure independently. The independent oracle is LMSD's own
# ``INCHI_KEY`` first block (+ charge-normalized via the record's SMILES). >~50k records, so the SDF
# is streamed + reservoir-subsampled (n=1500, seed 42) from the InChIKey-bearing population
# (``require_gold_structure``) and the exact subsample is persisted. Single CHEBI target vocab (one
# accuracy number per dataset; correctness always via the InChIKey block). No same-set competitor
# exists, so no competitor figure is drawn.
LMSD = DatasetConfig(
    key="lmsd",
    arm="metabolite",
    entity_type="metabolite",
    input_type="name",
    target_vocabs=("CHEBI",),
    name_column="lipid_name",
    gold_chebi_column="",  # LMSD's CHEBI_ID is a coverage crosswalk, not the oracle (InChIKey is)
    gold_inchikey_column="gold_inchikey",
    gold_smiles_column="gold_smiles",  # SDF ships SMILES -> enables the charge-normalized variant
    source_doi="10.1194/jlr.S120001025",
    source_url="https://www.lipidmaps.org/files/?file=LMSD&ext=sdf.zip",
    license="LMSD structures + annotations are available under CC BY 4.0 (lipidmaps.org).",
    subsample_n=1500,
    subsample_seed=42,
    require_gold_structure=True,
    role="capability_regression",
    regression_floor=0.90,
    gold_coverage_columns=(
        ("INCHIKEY", "gold_inchikey"),
        ("SMILES", "gold_smiles"),
        ("CHEBI", "gold_chebi"),
        ("HMDB", "gold_hmdb"),
        ("PUBCHEM", "gold_pubchem"),
        ("KEGG", "gold_kegg"),
        ("SWISSLIPIDS", "gold_swisslipids"),
    ),
)


# SwissLipids (swisslipids.org) — a lipid database with its OWN names + InChIKeys + a PubChem CID
# crosswalk, and a SwissLipids dialect Goslin parses natively. SwissLipids is NOT a Kraken ingest
# source, so it is a LEGAL accuracy gold (unlike LMSD/RefMet, which are IN Kraken and therefore
# circular). The query is SwissLipids' own name/abbreviation (a non-LIPID-MAPS dialect — this tests
# Goslin's real dialect-translation job, not an identity map). The gold structure is NOT taken from
# the KG or from LIPID MAPS: the held-out PubChem CID is resolved to an InChIKey by the INDEPENDENT
# PubChem resolver at scoring time, so the resolution-path binding (KG/RefMet) and the gold structure
# (PubChem) are disjoint. This is the REPORTABLE lipid accuracy arm.
SWISSLIPIDS = DatasetConfig(
    key="swisslipids",
    arm="metabolite",
    entity_type="metabolite",
    input_type="name",
    target_vocabs=("CHEBI",),
    name_column="lipid_name",
    gold_chebi_column="",
    gold_inchikey_column="gold_inchikey",  # filled at scoring time from the held-out PubChem CID
    gold_smiles_column="gold_smiles",
    source_doi="10.1093/nar/gku1179",  # Aimo et al. 2015, SwissLipids (Bioinformatics/NAR)
    source_url="https://www.swisslipids.org/api/file.php?cast=normal&file=lipids.tsv",
    license="SwissLipids data are freely available for academic use (swisslipids.org).",
    subsample_n=1500,
    subsample_seed=42,
    require_gold_structure=True,
    role="accuracy",
    gold_coverage_columns=(
        ("PUBCHEM", "held_out_pubchem"),
        ("INCHIKEY_SWISSLIPIDS", "gold_inchikey_swisslipids"),
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
    # Set True ONLY for a direction with a DOCUMENTED source gap (the provided source id is not a
    # queryable KG node, e.g. MetaBench kegg2hmdb). Then a zero provided-path mapping is a genuine 0/n
    # result, not a broken run: the fail-loud NoProvidedMappingError guard is suppressed and the
    # direction is scored as all-misses. Never set this to paper over an actually-broken run.
    known_source_gap: bool = False

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
# the first deferred follow-on; RefMet (Metabolomics Workbench reference nomenclature), NIST SRM 1950
# (certified clinical-plasma reference set), and LMSD (LIPID MAPS Structure Database — lipid-name
# gap characterization) are added here. All are name->structure, scored by the independent InChIKey
# oracle (strict + charge-normalized); none has a same-set competitor, so no competitor figure is
# drawn for any of them.
REGISTRY: dict[str, DatasetConfig] = {
    HAJJAR.key: HAJJAR,
    NECS.key: NECS,
    REFMET.key: REFMET,
    SRM1950.key: SRM1950,
    LMSD.key: LMSD,
    SWISSLIPIDS.key: SWISSLIPIDS,
}

# The gene/protein registry (CURIE-equality arm). No published same-set competitor exists for
# any of these, so — unlike Hajjar — NO competitor figure is emitted for them (BioMapper-vs-
# reference only; nothing fabricated).
CURIE_REGISTRY: dict[str, CurieDatasetConfig] = {
    HGNC.key: HGNC,
    UNIPROT_IDMAPPING.key: UNIPROT_IDMAPPING,
    NCBI_GENE2ENSEMBL.key: NCBI_GENE2ENSEMBL,
}

# ==================================================================================================
# NLM-Gene (Islamaj Doğan et al. 2021, J. Biomed. Inform., doi:10.1016/j.jbi.2021.103779) —
# the INDEPENDENT name-input gene-normalization benchmark. Unlike the HGNC / gene2ensembl backbones
# (whose golds are authoritative xref TABLES plausibly inside BioMapper's resolution path, so their
# numbers are equivalence-recall not independent accuracy), NLM-Gene's (mention -> NCBI Gene id) gold
# was produced by six NLM indexers reading 550 PubMed abstracts. The gold NAMESPACE (NCBIGene) is
# downstream in BioMapper's path, but the gold MAPPING is human-curated -> independent by construction.
# Corpus is public domain, BioC XML, one file per PMID under Corpus/. Scored ambiguity-partitioned:
# unambiguous surface forms -> accuracy (curie_scorer); ambiguous forms -> EITL flag-rate (nlmgene_scorer).
# ==================================================================================================

# A surface form whose union of gold NCBI Gene ids across the corpus has >= this many distinct genes
# is AMBIGUOUS (routed to the flag-rate partition). A single multi-id annotation is also ambiguous.
NLMGENE_AMBIGUOUS_MIN_GENES = 2

NLMGENE = CurieDatasetConfig(
    key="nlm-gene",
    arm="gene",
    entity_type="gene",
    input_type="name",
    name_column="mention",
    target_vocabs=("NCBIGene",),
    gold_curie_columns=(("NCBIGene", "gold_ncbigene"),),
    source_label="NLM-Gene corpus (Islamaj Doğan et al. 2021)",
    source_url="https://ftp.ncbi.nlm.nih.gov/pub/lu/NLMGene",
    license="Public domain (NLM/NCBI); freely available.",
    # subsample_n is unused by the NLM-Gene adapter (it parses per-PMID BioC XML, not a single streamed
    # TSV, and scores the full deduped surface-form set); set high so nothing is silently dropped.
    subsample_n=1_000_000,
    subsample_seed=42,
)

# NLM-Gene is driven by its own adapter/orchestrator (BioC XML + ambiguity partition), NOT the
# streaming backbone path, so it lives in its own registry rather than CURIE_REGISTRY.
NLMGENE_REGISTRY: dict[str, CurieDatasetConfig] = {NLMGENE.key: NLMGENE}

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


# ==================================================================================================
# MetaBench (Lu et al. 2025, arXiv:2510.14944) — the Grounding (cross-database ID mapping) task.
# ==================================================================================================
# The one external dataset with a VALID LLM head-to-head: the paper scores 25 open/closed LLMs on
# the SAME 1,000 grounding pairs (exact-match accuracy). The pairs are bidirectional cross-database
# mappings sampled from MetabolitesIDmapping, delivered as natural-language QA:
#   - ID -> ID   (400): HMDB->KEGG, KEGG->HMDB          -> provided-ID mode (source id provided)
#   - name -> ID (600): name->KEGG, name->HMDB, name->ChEBI -> name-input mode (annotation)
# In BOTH regimes the gold is the held-out TARGET database id and correctness is CURIE equality
# between BioMapper's equivalence-set predictions and the gold — so one uniform scorer, ONE number.
#
# ACQUISITION (2026-07-14): dataset released publicly on HuggingFace as ``LuYuxing/MetaBench``
# (Apache-2.0, non-gated); the Grounding file is ``Grounding - metabolite_mapping_dataset.csv``
# (exactly 1,000 rows). Apache-2.0 permits vendoring, but — mirroring Hajjar/NECS — we fetch from
# the source URL at run time and pin the SHA on the card rather than vendoring the raw bytes.
METABENCH_DOI = "10.48550/arXiv.2510.14944"
METABENCH_SOURCE_URL = (
    "https://huggingface.co/datasets/LuYuxing/MetaBench/resolve/main/Grounding%20-%20metabolite_mapping_dataset.csv"
)
METABENCH_LICENSE = "Apache-2.0 (HuggingFace dataset LuYuxing/MetaBench; grounding = MetabolitesIDmapping-derived)"
# SHA256 of the 1,000-row Grounding CSV as fetched at acquisition (2026-07-14). Recorded for
# reproducibility; the dataset card pins whatever bytes are actually fetched at run time.
METABENCH_EXPECTED_SHA256 = "5f1955d1053aee39ad7d6fd1a9c833d9221abdcfa8d258deb52f61036df12cd2"

# The 25-LLM baseline distribution published in the MetaBench paper for the Grounding task. This is
# the ONLY external set where BioMapper can be placed alongside a valid same-set LLM head-to-head.
# Per the Metabolon-96.5% scar and ``validate.citation_spot_check``: every value is left ``None``
# (needs-verification) — the DOI + table_ref are load-bearing so a human transcribes the exact
# figures from the paper's table at report time rather than trusting a from-memory number. The
# paper's headline (UNVERIFIED, read from the arXiv HTML during acquisition, MUST be re-checked
# against the source table before any is asserted): no-retrieval Grounding accuracy stays near zero
# and does not exceed ~0.87% even for the strongest model; a web-search-augmented run reaches at
# most ~40.93%. Do NOT bake those numbers as fact here.
METABENCH_BASELINE_TABLE_REF = "Lu et al. 2025 (arXiv:2510.14944), Grounding-task results table — TRANSCRIBE per model"
METABENCH_BASELINES: tuple[CompetitorResult, ...] = tuple(
    CompetitorResult(
        tool=tool,
        metric=metric,
        input_type="grounding",
        value=None,  # needs-verification: transcribe from the paper's table, do not assert from memory
        doi=METABENCH_DOI,
        table_ref=METABENCH_BASELINE_TABLE_REF,
    )
    for tool, metric in (
        ("Best LLM (no retrieval)", "grounding_exact_match"),
        ("Median LLM (no retrieval)", "grounding_exact_match"),
        ("Worst LLM (no retrieval)", "grounding_exact_match"),
        ("Best LLM (web-search retrieval)", "grounding_exact_match_with_retrieval"),
    )
)


@dataclass(frozen=True)
class MetaBenchDatasetConfig:
    """MetaBench Grounding registry entry — a mixed-regime cross-database ID-mapping benchmark.

    The parsed grounding set is a single normalized long frame with a fixed column contract
    (below). It decomposes into per-subgroup runs by ``(pair_type, source_namespace,
    target_namespace)``: ID->ID subgroups run in provided-ID mode, name->ID subgroups in
    name-input mode. Every subgroup's mapper output carries the two held-out scoring columns
    (``gold_target_column`` + ``target_namespace_column``) verbatim; the outputs are concatenated
    and scored ONCE (``score_metabench``) into a single accuracy — no per-vocab axis (the Hajjar
    calibration: ``chosen_kg_id`` is annotation-driven, not vocab-steered).

    ANTI-TRIVIAL-100%: the gold TARGET (``gold_target_column``) and its namespace are NEVER handed
    to the mapper as input, and every ID->ID subgroup has source namespace disjoint from target
    namespace (HMDB!=KEGG). ``metabench_scorer.assert_metabench_held_out`` re-checks both, fail-loud,
    before scoring. There is NO charge-normalized variant: the target is a database identifier, not
    a structure, so structure/protonation normalization does not apply.
    """

    key: str = "metabench-grounding"
    arm: str = "metabolite"
    entity_type: str = "metabolite"
    input_type: str = "mixed"  # id2id (provided-id) + name2id (name-input)
    source_doi: str = METABENCH_DOI
    source_url: str = METABENCH_SOURCE_URL
    license: str = METABENCH_LICENSE
    expected_source_sha256: str = METABENCH_EXPECTED_SHA256
    # Normalized long-form column contract (adapter emits these; scorer consumes the last three).
    question_column: str = "question"
    name_column: str = "metabolite_name"  # populated for name->ID rows; "" for ID->ID rows
    source_id_column: str = "source_id"  # populated for ID->ID rows; "" for name->ID rows
    source_namespace_column: str = "source_namespace"  # "HMDB"/"KEGG" for ID rows; "" for name rows
    gold_target_column: str = "gold_target"  # HELD OUT — bare target id (C-number / HMDB id / ChEBI number)
    target_namespace_column: str = "target_namespace"  # HELD OUT — "KEGG"/"HMDB"/"CHEBI" per row
    pair_type_column: str = "pair_type"  # "id2id" | "name2id"
    baseline_competitors: tuple[CompetitorResult, ...] = field(default_factory=lambda: METABENCH_BASELINES)


METABENCH = MetaBenchDatasetConfig()

# The MetaBench registry (single entry; the one external set with a valid LLM head-to-head).
METABENCH_REGISTRY: dict[str, MetaBenchDatasetConfig] = {METABENCH.key: METABENCH}


# ==================================================================================================
# MetaboliteAnnotator name-hit-rate arm (Lu et al. 2026, J. Proteome Res., DOI 10.1021/acs.jproteome
# .5c00477, PMID 41691569). A same-set, NAME-input head-to-head — the novel regime this harness
# targets. MetaboliteAnnotator benchmarked on SIX MetaboLights sets with a per-input NAME-HIT-RATE
# (fraction of input names for which a target-vocab identifier was produced), reporting 93.2%
# (positive, 4021/4314) and 93.5% (negative, 2344/2510) vs MetaboAnalyst 6.0 and metaboliteIDmapping.
#
# ACCESSION ACQUISITION: RESOLVED 2026-07-14. The six MTBLS accessions are named in the paper's
# Methods ("applied the tool to six public MetaboLights data sets (MTBLS12997, MTBLS13105, MTBLS12764,
# MTBLS11733, MTBLS12636, and MTBLS13039)") and detailed in its Table 1 (PMID 41691569, DOI
# 10.1021/acs.jproteome.5c00477). All six were verified live and public on MetaboLights, each exposing
# the positive- and negative-mode ``m_*.tsv`` MAF tables the name-hit protocol scores. The sentinel +
# fail-loud fetch guard are retained so any FUTURE unresolved accession still refuses to score.
# ==================================================================================================

NEEDS_FETCHING_SENTINEL = "MTBLS-NEEDS-FETCHING-"

# The six MetaboLights sets MetaboliteAnnotator benchmarked on (Lu et al. 2026, Methods + Table 1).
# Ordering is not load-bearing.
METABOLITEANNOTATOR_ACCESSIONS: tuple[str, ...] = (
    "MTBLS12997",  # AB Sciex TripleTOF 6600, XCMS — mouse fecal (largest: 1446 pos / 409 neg names)
    "MTBLS13105",  # Thermo Q Exactive, MS-DIAL — human fecal
    "MTBLS12764",  # Thermo Q-Exactive Plus, MS-DIAL — human tumor-associated
    "MTBLS11733",  # Thermo Q Exactive HF-X, Compound Discoverer — mouse osteocyte
    "MTBLS12636",  # AB Sciex TripleTOF 4600, XCMS/MetDNA 2 — human vaginal fornix
    "MTBLS13039",  # Thermo Q Exactive HF-X, XCMS — human serum
)


@dataclass(frozen=True)
class NameHitDatasetConfig:
    """A NAME-input, name-hit-rate benchmark registry entry (MetaboliteAnnotator regime).

    The comparable metric is a per-input NAME-HIT-RATE — the fraction of input names for which
    BioMapper produced a target-vocab identifier — computed with the SAME protocol as
    MetaboliteAnnotator so BioMapper's number lands directly beside the published 93.2%/93.5% and
    the MetaboAnalyst 6.0 / metaboliteIDmapping baselines. One config per ion mode -> exactly ONE
    headline number per config (the "one number per dataset" learning; the two configs reproduce the
    paper's two reported numbers).

    The run mode mirrors the metabolite arm: ``name_column`` is the sole query, ``provided_id_columns
    =[]`` so nothing is handed to BioMapper but the name (the runner's assigned>0 guard enforces the
    name path). ``gold_id_column`` (the MetaboLights MAF ``database_identifier``, ``|``-multi) and the
    optional ``gold_smiles_column`` are HELD OUT — consumed only by the scorer's ID-concordance /
    charge-normalized structure qualifiers, never by BioMapper.

    ANTI-TRIVIAL guard (``__post_init__``, fail-loud): the held-out ``gold_id_column`` must exist and
    must NOT be the ``name_column`` — a gold-equals-query config would let every row self-hit and
    silently score a trivial 100%.
    """

    key: str
    arm: str  # "metabolite"
    entity_type: str  # "metabolite"
    mode: str  # "positive" | "negative" — the ion mode this config aggregates across the 6 sets
    name_column: str  # the query column handed to the mapper (MAF metabolite_identification)
    gold_id_column: str  # held-out MAF database_identifier (|-delimited CURIEs) — ID-concordance gold
    gold_smiles_column: str  # held-out MAF SMILES ("" when absent) — charge-normalized structure gold
    target_vocabs: tuple[str, ...]  # vocabs the name is mapped to; hit = any target-vocab id produced
    accessions: tuple[str, ...]  # the 6 MetaboLights MTBLS sets (placeholders until fetched)
    source_url_template: str  # MetaboLights MAF URL template, ``{accession}`` substituted at fetch
    license: str
    input_type: str = "name"  # the unsolved regime this arm targets
    source_doi: str = "10.1021/acs.jproteome.5c00477"
    source_pmid: str = "41691569"
    accessions_status: str = "needs-fetching"  # flipped to "resolved" once real accessions are filled
    # MAF *bytes* are pulled from the MetaboLights public FTP mirror (per-study files served directly).
    # The web-service ``/download`` route returns HTTP 400 for these studies, so listing uses
    # ``source_url_template`` ({base}/files) but the download uses this FTP template.
    maf_download_url_template: str = (
        "https://ftp.ebi.ac.uk/pub/databases/metabolights/studies/public/{accession}/{filename}"
    )

    def __post_init__(self) -> None:
        if not (self.gold_id_column and self.gold_id_column.strip()):
            raise ValueError(
                f"{self.key}: anti-trivial violation — a held-out gold_id_column is required to "
                f"adjudicate a name hit against a reference; none was given."
            )
        if self.gold_id_column == self.name_column:
            raise ValueError(
                f"{self.key}: anti-trivial violation — gold_id_column {self.gold_id_column!r} equals "
                f"the query name_column; the gold must be held out, not the input. Refusing a config "
                f"that would self-hit to a trivial 100%."
            )


METABOLITEANNOTATOR_POS = NameHitDatasetConfig(
    key="metaboliteannotator-positive",
    arm="metabolite",
    entity_type="metabolite",
    mode="positive",
    name_column="metabolite_identification",  # MetaboLights MAF query column
    gold_id_column="gold_database_identifier",  # held-out MAF database_identifier (|-multi CURIEs)
    gold_smiles_column="gold_smiles",
    target_vocabs=("CHEBI", "HMDB", "PUBCHEM", "KEGG"),
    accessions=METABOLITEANNOTATOR_ACCESSIONS,
    accessions_status="resolved",
    # Web-service base — the adapter lists files at {base}/files. MAF *bytes* come from the public FTP
    # (maf_download_url_template) because the web-service /download route returns HTTP 400.
    source_url_template="https://www.ebi.ac.uk/metabolights/ws/studies/{accession}",
    license="MetaboLights data are available under CC0 (per-study terms apply).",
)

METABOLITEANNOTATOR_NEG = NameHitDatasetConfig(
    key="metaboliteannotator-negative",
    arm="metabolite",
    entity_type="metabolite",
    mode="negative",
    name_column="metabolite_identification",
    gold_id_column="gold_database_identifier",
    gold_smiles_column="gold_smiles",
    target_vocabs=("CHEBI", "HMDB", "PUBCHEM", "KEGG"),
    accessions=METABOLITEANNOTATOR_ACCESSIONS,
    accessions_status="resolved",
    source_url_template="https://www.ebi.ac.uk/metabolights/ws/studies/{accession}",
    license="MetaboLights data are available under CC0 (per-study terms apply).",
)

# The name-hit registry — one entry per ion mode (one headline number each).
NAME_HIT_REGISTRY: dict[str, NameHitDatasetConfig] = {
    METABOLITEANNOTATOR_POS.key: METABOLITEANNOTATOR_POS,
    METABOLITEANNOTATOR_NEG.key: METABOLITEANNOTATOR_NEG,
}


# ==================================================================================================
# Pham et al. 2019 name-DISAMBIGUATION arm (Metabolites 9(2):28, DOI 10.3390/metabo9020028,
# PMID 30736318, PMC6409771). The hard NAME-input frontier: a single metabolite name/abbreviation
# maps to MULTIPLE structurally-DISTINCT compounds across 11 biochemical databases (BiGG, ChEBI,
# enviPath, HMDB, KEGG, LIPID MAPS, MetaCyc, Reactome, SABIO-RK, SEED, SwissLipids), inter-database
# inconsistency up to 83.1%. This is the ambiguity BioMapper's resolver must survive on bare NAME
# input — distinct from the other metabolite arms (one name -> one gold structure); here one name ->
# a SET of legitimate structural referents.
#
# ACQUISITION (2026-07-15): the paper ships NO supplementary data file. Verified against the
# EuropePMC full-text XML (PMC6409771): zero <supplementary-material> tags, no "Supplementary
# Materials"/"Data Availability" section, no MDPI ``/s1`` link, no Zenodo/figshare/authors' code
# repo. The concrete ambiguous cases live in the paper's OWN Table 9 ("Examples of mapping
# inconsistencies") and Table 3 ("high ambiguity and multiplicity"). The full ambiguous-name
# population is RECONSTRUCTED (2026-07-16) from the paper's own inputs — the MetaNetX ``chem_xref.tsv``
# name<->MNXM crosswalk (its ``description`` field carries the cross-database synonym names) joined to
# ``chem_prop.tsv`` for INDEPENDENT curated InChIKeys per MNXM bridge id. Per the approval the CURRENT
# MetaNetX release is used (4.5, dated 2025/08/13) — NOT the paper's 2018 snapshot — so the benchmark
# reflects today's namespaces; the exact files are SHA- and md5-pinned on the dataset card. Hence
# ``source_status`` flips to "resolved" once the two files are supplied; the needs-reconstruction
# sentinel + a fail-loud guard remain (mirrors MetaboliteAnnotator's needs-fetching sentinel) so an
# unresolved source can never be silently scored. The offline unit tests drive the transform on tiny
# in-memory chem_prop/chem_xref fixtures so the reconstruction + scorer are fully testable meanwhile.
#
# ORACLE / CIRCULARITY (design for human sign-off; see the adapter + scorer docstrings): the gold is
# the SET of distinct InChIKey first-blocks a name legitimately maps to, resolved from an INDEPENDENT
# source — MetaNetX ``chem_prop.tsv`` (the paper's own bridge namespace, ships InChIKey+SMILES per
# MNXM id), cross-checked against PubChem-by-name (disagreements FLAGGED, never silently trusted) —
# NEVER via BioMapper's resolver. Only BioMapper's PREDICTION (``chosen_kg_id``) is resolved through
# the KG oracle, exactly like the structure-oracle arm. This keeps the SUT and the gold on disjoint
# infrastructure (no circularity).
# ==================================================================================================

# MetaNetX release used for the reconstruction. CURRENT numbered release (not the paper's 2018 snapshot,
# per the approved design). ``latest/`` on the FTP tracks this; we pin the numbered dir for stability.
METANETX_RELEASE = "4.5"
METANETX_FTP_BASE = "https://www.metanetx.org/ftp"

# The 11 databases Pham et al. surveyed (ordering not load-bearing; recorded on the card for provenance).
PHAM_DATABASES: tuple[str, ...] = (
    "BiGG",
    "ChEBI",
    "enviPath",
    "HMDB",
    "KEGG",
    "LIPID MAPS",
    "MetaCyc",
    "Reactome",
    "SABIO-RK",
    "SEED",
    "SwissLipids",
)

# Sentinel marking a source that must be RECONSTRUCTED from MetaNetX (no downloadable SI exists), so a
# placeholder can never be silently scored (mirrors NEEDS_FETCHING_SENTINEL / the MetaboliteAnnotator
# fail-loud guard).
PHAM_NEEDS_RECONSTRUCTION_SENTINEL = "PHAM-NEEDS-RECONSTRUCTION"

PHAM_DOI = "10.3390/metabo9020028"
PHAM_PMID = "30736318"


@dataclass(frozen=True)
class PhamDisambiguationDatasetConfig:
    """A NAME-DISAMBIGUATION benchmark registry entry (Pham et al. 2019 regime).

    The unit is the ambiguous NAME. Unlike the structure-oracle arms (one name -> one gold InChIKey),
    a genuinely ambiguous name maps to a SET of distinct structural referents, so there is NO single
    "correct" structure to demand (that is exactly the paper's finding). Correctness is therefore
    STRUCTURAL-MEMBERSHIP: given the bare ambiguous name, does BioMapper resolve to a structure that is
    a MEMBER of the name's legitimate referent set (a real referent, not an off-target/hallucinated
    structure)? — measured by InChIKey first-block. The referent set is the held-out
    ``gold_referent_inchikey_column`` (``|``-delimited distinct InChIKeys from the INDEPENDENT MetaNetX
    ``chem_prop`` source); ``gold_referent_id_column`` (candidate CURIEs) + ``gold_metanetx_column``
    (MNXM bridge ids) are coverage/provenance. All ride along with ``provided_id_columns=[]`` so
    BioMapper only ever sees the name.

    The run mode is name-input (``name_column`` sole query, ``annotation_mode='all'``), so this config
    satisfies the runner's ``RunnableConfig`` protocol and drives through ``runner.run_all`` unchanged.

    ANTI-TRIVIAL guard (``__post_init__``, fail-loud): the held-out referent gold column must exist and
    must NOT equal the ``name_column`` — a gold-equals-query config would let a name self-match and
    score a trivial 100%.
    """

    key: str
    arm: str  # "metabolite"
    entity_type: str  # "metabolite"
    name_column: str  # the ambiguous name/abbreviation handed to the mapper (the ONLY input)
    gold_referent_inchikey_column: str  # held-out ``|``-delimited distinct InChIKeys — the referent SET
    gold_referent_id_column: str  # held-out ``|``-delimited candidate CURIEs across DBs (coverage)
    gold_metanetx_column: str  # held-out ``|``-delimited MNXM bridge ids (independent-structure provenance)
    referent_count_column: str  # per-name count of distinct structural referents (ambiguity degree)
    target_vocabs: tuple[str, ...]  # vocabs the name is mapped to; membership is via the InChIKey block
    source_url: str  # the MetaNetX reconstruction inputs / sentinel (no downloadable SI exists)
    license: str
    input_type: str = "name"
    source_doi: str = PHAM_DOI
    source_pmid: str = PHAM_PMID
    # LIPID vs NON-LIPID stratification (approved 2026-07-16). The reconstructed ambiguous population is
    # ~100% lipid-isomer nomenclature, which overlaps the LMSD lipid arm and misses the abbreviation /
    # cross-class ambiguity Pham 2019 is actually about (``tmp`` -> thymidine-MP / thiamine-MP; ``suc``
    # -> succinate / sucrose). Each name is stratified by whether its referents are predominantly lipids
    # (namespace signal preferred: a LIPID MAPS / SwissLipids cross-reference on the referent's MNXM;
    # fallback: canonical lipid-shorthand NAME patterns). The NON-lipid stratum is the headline (Pham's
    # distinct contribution); the lipid stratum is reported separately (it overlaps LMSD).
    stratum_column: str = "stratum"  # per-name "lipid" | "non_lipid" label carried in the input_df
    is_lipid_referent_column: str = "is_lipid_referent"  # per-referent lipid flag in the raw candidate table
    # Deterministic WITHIN-strata subsample for the gated run (mirrors RefMet's reservoir + seed 42), so
    # the non-lipid headline is not swamped by the lipid majority. Each stratum is sampled INDEPENDENTLY
    # to its per-stratum n (or kept in full when the stratum is smaller); the exact scored subset is
    # persisted beside the card. ``None`` keeps a stratum in full.
    subsample_n_non_lipid: int | None = 1500
    subsample_n_lipid: int | None = 1500
    subsample_seed: int = 42
    # A name is RETAINED in the scored population if it has >= this many distinct structural referents.
    # Default 1 = the FULL population (every name with at least one resolvable structure); a name with
    # zero referents / no InChIKey among its candidates is dropped (nothing to score). The approved
    # scoring design scores this full population AND breaks out the ambiguous subset below — it no
    # longer pre-filters to ambiguous-only (which would collapse full-population and subset into one).
    min_referents: int = 1
    # The AMBIGUOUS subset threshold: names with >= this many distinct structural referents are the
    # paper's hard case, broken out and reported as the headline (``ambiguous_subset`` in the scorer).
    ambiguous_min_referents: int = 2
    source_status: str = "needs-reconstruction"  # flipped to "resolved" once the MetaNetX join lands
    databases: tuple[str, ...] = PHAM_DATABASES

    def __post_init__(self) -> None:
        if not (self.gold_referent_inchikey_column and self.gold_referent_inchikey_column.strip()):
            raise ValueError(
                f"{self.key}: anti-trivial violation — a held-out referent InChIKey column is required "
                f"to adjudicate structural membership; none was given."
            )
        if self.gold_referent_inchikey_column == self.name_column:
            raise ValueError(
                f"{self.key}: anti-trivial violation — the referent gold column "
                f"{self.gold_referent_inchikey_column!r} equals the query name_column; the gold must be "
                f"held out, not the input. Refusing a config that would self-match to a trivial 100%."
            )
        if self.min_referents < 1:
            raise ValueError(
                f"{self.key}: min_referents must be >= 1 (a scorable name needs >= 1 distinct "
                f"structural referent); got {self.min_referents}."
            )
        if self.ambiguous_min_referents < 2:
            raise ValueError(
                f"{self.key}: ambiguous_min_referents must be >= 2 (a disambiguation case needs >= 2 "
                f"distinct structural referents); got {self.ambiguous_min_referents}."
            )
        if self.ambiguous_min_referents < self.min_referents:
            raise ValueError(
                f"{self.key}: ambiguous_min_referents ({self.ambiguous_min_referents}) must be >= "
                f"min_referents ({self.min_referents}); the ambiguous subset cannot be looser than the "
                f"retained population."
            )


PHAM_DISAMBIGUATION = PhamDisambiguationDatasetConfig(
    key="pham-disambiguation",
    arm="metabolite",
    entity_type="metabolite",
    name_column="metabolite_name",  # the ambiguous name/abbreviation query
    gold_referent_inchikey_column="gold_referent_inchikeys",
    gold_referent_id_column="gold_referent_ids",
    gold_metanetx_column="gold_metanetx_ids",
    referent_count_column="referent_count",
    target_vocabs=("CHEBI", "HMDB", "PUBCHEM", "KEGG"),
    # The reconstruction inputs (no downloadable SI): MetaNetX chem_xref (name<->MNXM) + chem_prop
    # (InChIKey per MNXM). URL kept as provenance; the adapter fails loud on the sentinel until the two
    # files are supplied. CURRENT release (4.5) is used per the approved design — the exact bytes are
    # SHA/md5-pinned on the dataset card, so the mutable "current release" is still reproducible.
    source_url="https://www.metanetx.org/ftp/4.5/  (chem_xref.tsv + chem_prop.tsv)",
    license="Pham et al. 2019 is CC BY 4.0; MetaNetX/MNXref data are CC BY 4.0.",
)

# The name-disambiguation registry (single entry). No published same-set competitor tool exists (the
# paper reports inconsistency matrices, not a tool leaderboard), so — like NECS/RefMet/SRM1950 — NO
# competitor figure is drawn.
PHAM_DISAMBIGUATION_REGISTRY: dict[str, PhamDisambiguationDatasetConfig] = {
    PHAM_DISAMBIGUATION.key: PHAM_DISAMBIGUATION,
}

# Published same-set baselines for the head-to-head. Following the CompetitorResult discipline
# (Metabolon-96.5% scar): ``value=None`` in source control — transcribed + verified against the
# paper's table at run time, NOT baked from the abstract/memory. The abstract-reported aggregates
# (MetaboliteAnnotator 93.2% pos / 93.5% neg; MetaboAnalyst 6.0 and metaboliteIDmapping lower) are
# the numbers to transcribe; ``doi`` + ``table_ref`` make each entry citeable so citation_spot_check
# admits it. MetaboliteAnnotator's OWN headline is included as the tool BioMapper is measured beside.
METABOLITEANNOTATOR_DOI = "10.1021/acs.jproteome.5c00477"
METABOLITEANNOTATOR_TABLE_REF = (
    "Lu et al. 2026, J. Proteome Res. (DOI 10.1021/acs.jproteome.5c00477), name-hit-rate comparison "
    "across the six MetaboLights sets (positive + negative mode) — transcribe per-mode cell at run time"
)
METABOLITEANNOTATOR_COMPETITORS: tuple[CompetitorResult, ...] = tuple(
    CompetitorResult(
        tool=tool,
        metric="name_hit_rate",
        input_type=mode,  # "positive" / "negative" — the paper reports one number per mode
        value=None,
        doi=METABOLITEANNOTATOR_DOI,
        table_ref=f"{METABOLITEANNOTATOR_TABLE_REF} [{mode} mode]",
    )
    for mode in ("positive", "negative")
    for tool in ("MetaboliteAnnotator", "MetaboAnalyst 6.0", "metaboliteIDmapping")
)


# ==================================================================================================
# metLinkR head-to-head (Patt et al. 2025, J. Proteome Res., DOI 10.1021/acs.jproteome.4c01051,
# PMC12053952) — the closest same-TASK tool: metabolite-ID cross-linking on RefMet + RaMP-DB.
# ==================================================================================================
# metLinkR harmonizes metabolite lists across datasets and reports (i) coverage and (ii) AGREEMENT
# with the COMETS expert curators (~85.3% headline in the paper). Crucially, metLinkR does NOT
# validate its links against an InChIKey structural oracle — that gap is BioMapper's differentiator.
#
# This arm scores BioMapper on the FIVE COMETS-curator-cross-linked datasets (the paper's
# ``inputs_*`` files), whose expert grouping is delivered in ``ManualMappings.csv`` (SI zip
# pr4c01051_si_003.zip). One row per source metabolite carries: the metabolite NAME
# (``IPT_METABOLITE_NAME``), the curator's manual cross-link group label
# (``Manual_Metabolite_Group_Label`` — two rows sharing a label are the SAME compound per the
# curators), and the curator/Metabolon PROVIDED reference IDs (``IPT_HMDB_ID`` / ``IPT_PUBCHEM``).
#
# DUAL, LABELLED SCORING (see scorers/metlinkr_scorer.py):
#   (a) CURATOR-AGREEMENT rate — metLinkR's own ~85.3% metric. Over the curator's cross-dataset
#       linked PAIRS, the fraction that BioMapper also links (its two name-resolved canonical
#       identifier sets intersect). Held-out gold = the curator group label (never shown to
#       BioMapper); anti-trivial because BioMapper must independently arrive at the same canonical
#       for both members from the NAME alone.
#   (b) INCHIKEY STRUCTURAL CONCORDANCE — the oracle metLinkR LACKS. For each row carrying a
#       held-out curator provided ID, resolve BOTH BioMapper's name-chosen ID AND the curator ID to
#       an InChIKey first-block and compare. Validates the LINK against a STRUCTURE, not just
#       identifier/name agreement.
#
# ACQUISITION (2026-07-15): the ACS SI is Cloudflare-bot-blocked on direct fetch, but the identical
# SI zips are mirrored on EuropePMC's PMC12053952 ``supplementaryFiles`` bundle (fetched live). The
# scored table ``ManualMappings.csv`` SHA is pinned below; the adapter re-pins whatever bytes it
# fetches on the dataset card. INPUT MODE is NAME-ONLY (provided_id_columns=[]) — consistent with the
# whole name-input harness and required to keep oracle (b) non-trivial (a provided curator ID handed
# back as input would self-echo its own structure). See the module docstring for the run-mode note.

NEEDS_FETCHING_SENTINEL_METLINKR = "METLINKR-NEEDS-FETCHING-"

METLINKR_DOI = "10.1021/acs.jproteome.4c01051"
METLINKR_PMCID = "PMC12053952"
# Canonical ACS SI URL (Cloudflare-blocked on direct bot fetch; recorded for provenance).
METLINKR_SI_URL = "https://pubs.acs.org/doi/suppl/10.1021/acs.jproteome.4c01051/suppl_file/pr4c01051_si_003.zip"
# Working live mirror: EuropePMC bundles every supplementary file (incl. both SI zips) for a PMCID.
METLINKR_FETCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC12053952/supplementaryFiles"
# The SI zip (inside the EuropePMC bundle) that holds the curator oracle, and the file inside it.
METLINKR_SI_ZIP_MEMBER = "pr4c01051_si_003.zip"
METLINKR_MANUAL_MAPPINGS_MEMBER = "ManualMappings.csv"
# SHA256 of ManualMappings.csv as fetched at acquisition (2026-07-15). Pinned for reproducibility;
# the card re-pins the bytes actually fetched at run time.
METLINKR_MANUAL_MAPPINGS_SHA256 = "3c94b2d0a6463b7dc446884a873b8a4d0e3d80943ea91de0bf1d599e1183e5ac"


@dataclass(frozen=True)
class MetLinkRDatasetConfig:
    """metLinkR head-to-head registry entry — a same-TASK, cross-linking benchmark.

    The parsed scoring table (from ``ManualMappings.csv``) is one row per source metabolite across
    the 5 COMETS datasets. Columns the adapter emits: the query NAME (``name_column``) plus three
    HELD-OUT columns consumed only by the scorer — the curator cross-link group label
    (``group_label_column``), and the curator PROVIDED reference IDs
    (``gold_hmdb_column`` / ``gold_pubchem_column``). ``source_file_column`` tags which COMETS
    dataset a row came from (cross-dataset pairing / traceability).

    Run mode mirrors the metabolite name-input arm: ``name_column`` is the SOLE query,
    ``provided_id_columns=[]``, so nothing but the name reaches BioMapper (runner's assigned>0 guard
    enforces the name path). The curator group label and provided IDs are held out.

    ANTI-TRIVIAL guard (``__post_init__``, fail-loud): the held-out ``group_label_column`` must exist
    and must NOT equal ``name_column`` — a label-equals-query config would leak the grouping into the
    input and let every curator pair self-link to a trivial 100%.
    """

    key: str = "metlinkr-comets"
    arm: str = "metabolite"
    entity_type: str = "metabolite"
    input_type: str = "name"
    name_column: str = "metabolite_name"  # query handed to mapper (from IPT_METABOLITE_NAME)
    # HELD OUT — the COMETS curator manual cross-link grouping (oracle (a) gold). Two rows sharing a
    # value are the SAME compound per the expert curators.
    group_label_column: str = "curator_group_label"
    # HELD OUT — the curator/Metabolon provided reference IDs (oracle (b) structural anchor).
    gold_hmdb_column: str = "curator_hmdb"
    gold_pubchem_column: str = "curator_pubchem"
    source_file_column: str = "source_file"  # which COMETS dataset (cross-dataset pairing)
    # Vocabs the name is mapped to; a link is BioMapper-confirmed iff both members share a canonical
    # id in ANY of these (union — not per-vocab).
    target_vocabs: tuple[str, ...] = ("CHEBI", "HMDB", "PUBCHEM", "KEGG", "REFMET")
    source_doi: str = METLINKR_DOI
    source_pmcid: str = METLINKR_PMCID
    source_url: str = METLINKR_SI_URL  # canonical ACS SI (provenance)
    fetch_url: str = METLINKR_FETCH_URL  # working EuropePMC mirror (live fetch)
    si_zip_member: str = METLINKR_SI_ZIP_MEMBER
    manual_mappings_member: str = METLINKR_MANUAL_MAPPINGS_MEMBER
    expected_manual_mappings_sha256: str = METLINKR_MANUAL_MAPPINGS_SHA256
    license: str = (
        "metLinkR SI (Patt et al. 2025, ACS J. Proteome Res.); COMETS/Metabolon-derived curator "
        "mappings — see ACS supporting-information terms."
    )

    def __post_init__(self) -> None:
        if not (self.group_label_column and self.group_label_column.strip()):
            raise ValueError(
                f"{self.key}: anti-trivial violation — a held-out group_label_column is required to "
                f"adjudicate a link against the curator grouping; none was given."
            )
        if self.group_label_column == self.name_column:
            raise ValueError(
                f"{self.key}: anti-trivial violation — group_label_column {self.group_label_column!r} "
                f"equals the query name_column; the curator grouping must be held out, not the input. "
                f"Refusing a config that would self-link to a trivial 100%."
            )


METLINKR = MetLinkRDatasetConfig()

# The metLinkR registry (single entry; the closest same-task tool).
METLINKR_REGISTRY: dict[str, MetLinkRDatasetConfig] = {METLINKR.key: METLINKR}

# Published same-task baseline. Following the CompetitorResult discipline (Metabolon-96.5% scar):
# metLinkR's curator-agreement headline is TRANSCRIBED + VERIFIED against the paper's Results text
# (Patt et al. 2025, "MetLinkR vs Manual Annotation" subsection) — NOT asserted from memory. The
# verified sentences (PMC12053952 full text, checked 2026-07-16):
#   - "Among metabolite entities identified across data sets by the curator, metLinkR identified
#      these entities at an 85.3% rate."  -> curator agreement = 85.3% (our oracle-(a) comparator).
#   - "When removing identifiers that metLinkR was unable to map ... that number rose to a 90.7%
#      rate."  -> 90.7% excluding unmapped (a different, mapped-only denominator; recorded for context).
#   - Global mapping rate 82.3% (5-dataset set) / 72.5% (13-dataset set) — overall harmonization
#      success, NOT a curator-agreement or structural number, so it is context only (no competitor
#      cell; conflating it with oracle (a)/(b) would be an apples-to-oranges comparison).
# ``doi`` + ``table_ref`` make the cell citeable so citation_spot_check admits it. The structural-
# concordance metric has NO competitor cell: metLinkR reports no InChIKey-oracle number (the point).
METLINKR_CURATOR_AGREEMENT_VALUE = 0.853  # verified: "identified these entities at an 85.3% rate"
METLINKR_CURATOR_AGREEMENT_EXCL_UNMAPPED = 0.907  # verified context: "rose to a 90.7% rate"
METLINKR_GLOBAL_MAPPING_5SET = 0.823  # verified context: "global mapping rate of 82.3%" (5-set)
METLINKR_GLOBAL_MAPPING_13SET = 0.725  # verified context: "global mapping rate of 72.5%" (13-set)
METLINKR_TABLE_REF = (
    "Patt et al. 2025, J. Proteome Res. (DOI 10.1021/acs.jproteome.4c01051, PMC12053952), Results & "
    "Discussion — 'MetLinkR vs Manual Annotation': 'metLinkR identified these entities at an 85.3% "
    "rate' (90.7% excluding unmapped identifiers)"
)
METLINKR_COMPETITORS: tuple[CompetitorResult, ...] = (
    CompetitorResult(
        tool="metLinkR",
        metric="curator_agreement_rate",
        input_type="cross_link",
        value=METLINKR_CURATOR_AGREEMENT_VALUE,  # 85.3%, verified against the paper's Results text
        doi=METLINKR_DOI,
        table_ref=METLINKR_TABLE_REF,
    ),
)
