"""Gene/protein cross-reference backbone adapters (CURIE-equality arm).

Three authoritative cross-reference tables, each turned into a mapper-ready ``input_df`` (a
source-namespace symbol/accession query + held-out gold cross-ref CURIE columns) and a
``dataset_card``:

  - **HGNC complete set** — approved gene symbol -> Ensembl / Entrez / UniProt.
  - **UniProt idmapping_selected.tab** — UniProt accession -> RefSeq / Ensembl. This file is
    multi-GB, so it is **streamed and reservoir-subsampled** (never loaded-then-sampled): the
    record generator yields one parsed row at a time and the reservoir holds only ``n`` rows.
  - **NCBI gene2ensembl** — Entrez GeneID -> Ensembl gene.

Every gold column is an AUTHORITATIVE cross-reference stated explicitly in ``config`` (the
gold-column identity is load-bearing). Multi-valued cross-refs (e.g. several UniProt IDs for one
symbol) are ``|``-joined; the ``curie_scorer`` splits on ``|``. The subsample is deterministic
(reservoir, ``seed=42`` pinned on the card) so the scored subset is reproducible.

Network is isolated behind ``stream_source_lines`` so the parse + subsample + card transforms
are fully unit-testable on an in-memory line iterator.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

import pandas as pd

from ..config import HGNC, NCBI_GENE2ENSEMBL, UNIPROT_IDMAPPING, CurieDatasetConfig

CURIE_DELIM = "|"


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def reservoir_sample(items: Iterable[Any], n: int, seed: int) -> list[Any]:
    """Deterministic reservoir sample (Algorithm R) of ``n`` items from a stream.

    Single pass, O(n) memory — the whole population is never materialized. Deterministic given
    ``seed`` and the item order, so the scored subset is reproducible and recordable.
    """
    rng = random.Random(seed)
    reservoir: list[Any] = []
    for i, item in enumerate(items):
        if i < n:
            reservoir.append(item)
        else:
            j = rng.randint(0, i)
            if j < n:
                reservoir[j] = item
    return reservoir


def _curie(prefix: str, local: str) -> str:
    local = str(local).strip()
    return f"{prefix}:{local}" if local else ""


def _multi_curie(prefix: str, raw: str, sep: str = "|") -> str:
    """Join multiple local ids (already ``sep``-delimited) into ``sep``-joined CURIEs."""
    parts = [p.strip() for p in str(raw).split(sep) if p.strip()]
    return CURIE_DELIM.join(_curie(prefix, p) for p in parts if p)


# ---------------------------------------------------------------------------
# Per-backbone streaming record parsers. Each yields a dict keyed by the config's
# name_column + gold columns; filtering (taxon / empty query) happens DURING the stream so the
# reservoir samples from the eligible population, not the raw file.
# ---------------------------------------------------------------------------


def hgnc_records(lines: Iterable[str]) -> Iterator[dict[str, str]]:
    """Parse the HGNC complete set (TSV *with* header). symbol -> Ensembl/Entrez/UniProt."""
    it = iter(lines)
    try:
        header = next(it)
    except StopIteration:
        return
    cols = header.rstrip("\n").split("\t")
    idx = {name: i for i, name in enumerate(cols)}
    sym_i = idx.get("symbol")
    ens_i = idx.get("ensembl_gene_id")
    ent_i = idx.get("entrez_id")
    uni_i = idx.get("uniprot_ids")
    if sym_i is None:
        raise KeyError(f"HGNC header missing 'symbol'; got {cols[:8]!r}...")

    def _get(fields: list[str], i: int | None) -> str:
        return fields[i].strip() if (i is not None and i < len(fields)) else ""

    for line in it:
        fields = line.rstrip("\n").split("\t")
        symbol = _get(fields, sym_i)
        if not symbol:
            continue
        yield {
            "symbol": symbol,
            "gold_ensembl": _curie("ENSEMBL", _get(fields, ens_i)),
            "gold_entrez": _curie("NCBIGene", _get(fields, ent_i)),
            "gold_uniprot": _multi_curie("UniProtKB", _get(fields, uni_i)),
        }


# idmapping_selected.tab: no header, fixed columns (0-based):
#   0 UniProtKB-AC | 2 GeneID(Entrez) | 3 RefSeq | 12 NCBI-taxon | 18 Ensembl
_UNIPROT_AC = 0
_UNIPROT_REFSEQ = 3
_UNIPROT_TAXON = 12
_UNIPROT_ENSEMBL = 18


def uniprot_records(lines: Iterable[str], tax_filter: str | None = None) -> Iterator[dict[str, str]]:
    """Parse UniProt idmapping_selected.tab (no header). accession -> RefSeq/Ensembl."""
    for line in lines:
        fields = line.rstrip("\n").split("\t")
        if len(fields) <= _UNIPROT_ENSEMBL:
            continue
        if tax_filter is not None and fields[_UNIPROT_TAXON].strip() != tax_filter:
            continue
        ac = fields[_UNIPROT_AC].strip()
        if not ac:
            continue
        yield {
            "uniprotkb_ac": ac,
            "gold_refseq": _multi_curie("RefSeq", fields[_UNIPROT_REFSEQ].replace(";", "|")),
            "gold_ensembl": _multi_curie("ENSEMBL", fields[_UNIPROT_ENSEMBL].replace(";", "|")),
        }


def gene2ensembl_records(lines: Iterable[str], tax_filter: str | None = None) -> Iterator[dict[str, str]]:
    """Parse NCBI gene2ensembl (header starts with '#'). Entrez GeneID -> Ensembl gene."""
    for line in lines:
        if line.startswith("#"):
            continue
        fields = line.rstrip("\n").split("\t")
        if len(fields) < 3:
            continue
        tax_id, gene_id, ensembl_gene = fields[0].strip(), fields[1].strip(), fields[2].strip()
        if tax_filter is not None and tax_id != tax_filter:
            continue
        if not gene_id:
            continue
        yield {
            "gene_id": gene_id,
            "gold_ensembl": _curie("ENSEMBL", ensembl_gene),
        }


_RECORDS_FN = {
    HGNC.key: lambda lines, cfg: hgnc_records(lines),
    UNIPROT_IDMAPPING.key: lambda lines, cfg: uniprot_records(lines, cfg.tax_filter),
    NCBI_GENE2ENSEMBL.key: lambda lines, cfg: gene2ensembl_records(lines, cfg.tax_filter),
}


def stream_source_lines(url: str, *, timeout: float = 300.0) -> Iterator[str]:
    """Stream a (optionally gzipped) source line-by-line (network). Isolated; not unit-tested.

    Uses HTTP streaming + on-the-fly gzip so a multi-GB source (UniProt idmapping) is never held
    in memory — the reservoir sampler consumes this generator directly.
    """
    import gzip

    import requests

    resp = requests.get(url, stream=True, timeout=timeout)
    resp.raise_for_status()
    if url.endswith(".gz"):
        with gzip.GzipFile(fileobj=resp.raw) as gz:
            for raw in gz:
                yield raw.decode("utf-8", "replace").rstrip("\n")
    else:
        for line in resp.iter_lines(decode_unicode=True):
            if line is not None:
                yield line


def build_input_df(records: list[dict[str, str]], config: CurieDatasetConfig) -> pd.DataFrame:
    """Build the mapper-ready input_df from sampled records.

    Guarantees the name query column + every configured gold column exist (missing values are
    empty strings), so the run mode is name-only with the gold held out for the scorer.
    """
    gold_cols = [col for _, col in config.gold_curie_columns]
    columns = [config.name_column, *gold_cols]
    rows = [{c: rec.get(c, "") for c in columns} for rec in records]
    return pd.DataFrame(rows, columns=columns)


def build_card(
    input_df: pd.DataFrame,
    *,
    n_scanned: int,
    source_sha: str,
    config: CurieDatasetConfig,
) -> dict[str, Any]:
    """Build the dataset_card: N, subsample n/seed, per-column coverage, gold identity, SHA."""
    n = len(input_df)
    coverage: dict[str, dict[str, Any]] = {}
    for namespace, column in config.gold_curie_columns:
        col = input_df[column] if column in input_df.columns else pd.Series([""] * n)
        present = int(col.map(lambda s: bool(str(s).strip())).sum())
        coverage[namespace] = {"n": present, "fraction": (present / n) if n else 0.0}
    return {
        "dataset": config.key,
        "arm": config.arm,
        "entity_type": config.entity_type,
        "input_type": config.input_type,
        "target_vocabs": list(config.target_vocabs),
        "n_rows": n,
        "n_scanned": n_scanned,
        "subsample": {"n": config.subsample_n, "seed": config.subsample_seed, "method": "reservoir"},
        "tax_filter": config.tax_filter,
        # AUTHORITATIVE gold cross-ref columns, stated explicitly (identity is load-bearing).
        "gold_curie_columns": {ns: col for ns, col in config.gold_curie_columns},
        "coverage": coverage,
        "source_label": config.source_label,
        "source_url": config.source_url,
        # SHA pins the deterministic SUBSAMPLE (exactly what was scored) — the multi-GB source
        # cannot be hashed inline, so reproducibility is (source version + seed + n) -> subsample.
        "subsample_sha256": source_sha,
        "license": config.license,
    }


def subsample_from_lines(lines: Iterable[str], config: CurieDatasetConfig) -> tuple[pd.DataFrame, int]:
    """Stream -> filter -> reservoir-subsample -> input_df. Returns (input_df, n_scanned).

    ``n_scanned`` counts eligible records seen (post-filter), for card transparency.
    """
    records_fn = _RECORDS_FN.get(config.key)
    if records_fn is None:
        raise KeyError(f"no backbone record parser registered for {config.key!r}")

    counter = {"n": 0}

    def _counting(it: Iterator[dict[str, str]]) -> Iterator[dict[str, str]]:
        for rec in it:
            counter["n"] += 1
            yield rec

    sampled = reservoir_sample(_counting(records_fn(lines, config)), config.subsample_n, config.subsample_seed)
    return build_input_df(sampled, config), counter["n"]


@dataclass(frozen=True)
class BackboneBundle:
    input_df: pd.DataFrame
    card: dict[str, Any]


def load_backbone(source: Iterable[str] | str, config: CurieDatasetConfig) -> BackboneBundle:
    """Load a backbone from a line iterator (tests) or a URL string (streamed, network)."""
    lines: Iterable[str] = stream_source_lines(source) if isinstance(source, str) else source
    input_df, n_scanned = subsample_from_lines(lines, config)
    sha = sha256_bytes(input_df.to_csv(index=False).encode("utf-8"))
    card = build_card(input_df, n_scanned=n_scanned, source_sha=sha, config=config)
    return BackboneBundle(input_df=input_df, card=card)
