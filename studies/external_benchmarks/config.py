"""Registry entries for the external-benchmarks study.

Only Hajjar-100 is active this pass (metabolite arm, name input). NECS, MetaBench,
and the gene/protein backbones are deferred to a validated follow-on.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DatasetConfig:
    """A benchmark dataset registry entry.

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
    gold_chebi_column: str  # held-out ground-truth ChEBI id
    gold_inchikey_column: str  # held-out curated InChIKey — the independent structure oracle
    gold_smiles_column: str | None  # optional; enables the RDKit second-source structure check
    source_doi: str
    source_url: str
    license: str


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


REGISTRY: dict[str, DatasetConfig] = {HAJJAR.key: HAJJAR}
