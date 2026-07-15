"""Canonical namespace <-> per-tool code tables + CURIE-representation alignment.

The gold cross-refs are CURIEs in the harness's canonical convention (``ENSEMBL:ENSG...``,
``NCBIGene:672``, ``UniProtKB:P38398``, ``RefSeq:NP_009225``). Each competitor speaks its own
namespace vocabulary and returns bare local IDs; this module maps between the two and, critically,
aligns the *representation* of a competitor's local ID to the gold convention so a tool is scored
on mapping capability, not formatting:

  - Ensembl gene / RefSeq accessions are stripped of any ``.N`` version suffix (the backbone gold
    columns are unversioned). This alignment is applied UNIFORMLY to every tool's output; the
    ``curie_scorer`` itself is reused verbatim, so the correctness rule is unchanged.

``BACKBONE_SOURCE_NAMESPACE`` records the SOURCE namespace of each gene/protein backbone's query
column (the ``CurieDatasetConfig`` carries the query column name but not its namespace), so the
runner can tell each tool what it's mapping *from*.
"""

from __future__ import annotations

from collections.abc import Iterable

# Canonical namespace prefixes as they appear in the backbone gold columns.
ENSEMBL = "ENSEMBL"
NCBIGENE = "NCBIGene"
UNIPROTKB = "UniProtKB"
REFSEQ = "RefSeq"
SYMBOL = "SYMBOL"  # HGNC approved gene symbol (source only)

# Source namespace of each backbone's query column (identity is load-bearing for direction).
BACKBONE_SOURCE_NAMESPACE: dict[str, str] = {
    "hgnc-complete-set": SYMBOL,
    "uniprot-idmapping": UNIPROTKB,
    "ncbi-gene2ensembl": NCBIGENE,
}

# Namespaces whose local IDs carry a ``.N`` version suffix the gold omits (aligned before scoring).
# UniProtKB is included because g:Convert's ``UNIPROTSWISSPROT`` target returns VERSIONED accessions
# (e.g. ``P04637.307``) while the backbone gold is unversioned (``P04637``). A UniProt accession never
# legitimately contains a ``.<digits>`` (isoforms use ``-N``), so stripping a trailing numeric ``.N``
# aligns representation without ever mangling a real id — the tool is scored on mapping, not format.
_VERSIONED = frozenset({ENSEMBL, REFSEQ, UNIPROTKB})


def _canonical_ns(ns: str) -> str:
    """Case-insensitive match of a requested namespace to a canonical constant."""
    lookup = {n.upper(): n for n in (ENSEMBL, NCBIGENE, UNIPROTKB, REFSEQ, SYMBOL)}
    return lookup.get(str(ns).strip().upper(), str(ns).strip())


def canonicalize_local(namespace: str, local: str) -> str:
    """Align a competitor's bare local ID to the gold's representation for ``namespace``.

    Strips an Ensembl/RefSeq ``.N`` version suffix (gold is unversioned); leaves other namespaces
    untouched. Returns "" for a blank/sentinel value so it drops out of the prediction set.
    """
    s = str(local).strip()
    if not s or s.lower() in {"none", "nan", "null", "-", "na", "n/a"}:
        return ""
    canon = _canonical_ns(namespace)
    if canon in _VERSIONED and "." in s:
        head, _, tail = s.rpartition(".")
        if head and tail.isdigit():  # only strip a genuine numeric version suffix
            s = head
    return s


def to_curie(namespace: str, local: str) -> str:
    """Build a gold-convention CURIE from a namespace + a competitor's bare local ID.

    Returns "" when the local ID is blank/sentinel (so it never enters the prediction set). If the
    value already carries the canonical prefix it is returned aligned, not double-prefixed.
    """
    canon = _canonical_ns(namespace)
    raw = str(local).strip()
    if ":" in raw and not raw.startswith("http"):
        prefix, _, tail = raw.partition(":")
        if prefix.upper() == canon.upper():
            raw = tail
    aligned = canonicalize_local(canon, raw)
    return f"{canon}:{aligned}" if aligned else ""


def curies_to_equiv_cell(curies: Iterable[str]) -> dict[str, list[str]]:
    """Pack a set of full CURIEs into a ``kg_equivalent_ids`` cell the ``curie_scorer`` consumes.

    Grouped ``{prefix: [local, ...]}`` — exactly the shape ``predicted_curies`` reconstructs, so a
    competitor's prediction is scored by the identical rule as BioMapper's. Deterministic ordering.
    """
    grouped: dict[str, list[str]] = {}
    for curie in sorted({c for c in curies if c}):
        prefix, _, local = curie.partition(":")
        grouped.setdefault(prefix, [])
        if local and local not in grouped[prefix]:
            grouped[prefix].append(local)
    return grouped


# --- per-tool namespace code tables (canonical -> tool code; missing key => unsupported) ---------

# g:Profiler / g:Convert target codes (source is auto-detected by g:Convert, so no source code
# beyond "the organism is human"). RefSeq gold here is protein accessions (idmapping col 3).
GCONVERT_TARGET: dict[str, str] = {
    ENSEMBL: "ENSG",
    NCBIGENE: "ENTREZGENE_ACC",
    UNIPROTKB: "UNIPROTSWISSPROT",
    REFSEQ: "REFSEQ_PEPTIDE_ACC",
}
GCONVERT_SOURCE: frozenset[str] = frozenset({SYMBOL, UNIPROTKB, NCBIGENE})  # auto-detected input

# bioDBnet db2db controlled-vocabulary db names.
BIODBNET_DB: dict[str, str] = {
    SYMBOL: "Gene Symbol",
    ENSEMBL: "Ensembl Gene ID",
    NCBIGENE: "Gene ID",
    UNIPROTKB: "UniProt Accession",
    REFSEQ: "RefSeq Protein Accession",
}

# UniProt REST idmapping from/to db codes.
UNIPROT_DB: dict[str, str] = {
    SYMBOL: "Gene_Name",
    UNIPROTKB: "UniProtKB_AC-ID",
    NCBIGENE: "GeneID",
    ENSEMBL: "Ensembl",
    REFSEQ: "RefSeq_Protein",
}
# UniProt idmapping requires the SOURCE to be a UniProtKB db when the TARGET is a UniProtKB db and
# vice-versa; for cross-ref targets the source must be UniProtKB_AC-ID or a supported name/xref.
UNIPROT_TARGET_CODES: dict[str, str] = {
    ENSEMBL: "Ensembl",
    NCBIGENE: "GeneID",
    UNIPROTKB: "UniProtKB",
    REFSEQ: "RefSeq_Protein",
}
