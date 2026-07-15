"""Pham et al. 2019 name-DISAMBIGUATION adapter (metabolite arm — referent-set structure oracle).

Turns the paper's ambiguous-name examples into a mapper-ready ``input_df`` (the bare ambiguous NAME
query + a held-out SET of legitimate structural referents) and a ``dataset_card`` recording N
ambiguous names, mean ambiguity degree, per-database coverage, pinned source SHA, and license.

Regime (why this arm is different):
  - The other metabolite arms are one name -> one gold InChIKey. Pham's finding is that a single
    name/abbreviation (``tmp``, ``suc``, ``PPP``, ``H``) maps to STRUCTURALLY-DISTINCT compounds across
    the 11 databases. So the gold is a SET of distinct InChIKey first-blocks (the name's legitimate
    referents), and "correct" is STRUCTURAL-MEMBERSHIP (BioMapper lands on SOME real referent), never
    "picked the one true structure" — there isn't one. See ``scorers/pham_scorer.py``.
  - Only genuinely ambiguous names (>= ``config.min_referents`` distinct referents) enter the scored
    set; a name with a single referent is not a disambiguation case and is DROPPED (documented, like
    the blank-name drop in ``metaboliteannotator``). Never fabricated: a dropped name is simply not a
    hard case.

Circularity guard (the load-bearing design point):
  - The referent InChIKeys are supplied by an INDEPENDENT source — MetaNetX ``chem_prop.tsv`` (the
    paper's own MNXRef bridge namespace, which ships a curated InChIKey per MNXM id), cross-checked
    against PubChem-by-name — and preserved VERBATIM in the held-out gold column. Zero shared infra
    with BioMapper's resolver. Only BioMapper's PREDICTION is resolved through the KG oracle (scorer).
  - The mapper is later called with ``name_column=config.name_column`` and ``provided_id_columns=[]``
    — the gold columns ride along untouched and are consumed only by the scorer.

ACQUISITION / SOURCE STATUS: ``needs-reconstruction``. The paper ships NO supplementary data file
(verified against the EuropePMC full-text XML for PMC6409771: no <supplementary-material> tags, no
Data-Availability/Supplementary section, no MDPI ``/s1`` link, no Zenodo/figshare/authors' repo). The
concrete ambiguous cases are the paper's Table 9 / Table 3; the full population is reconstructible only
from MetaNetX ``chem_xref.tsv`` (name<->ID, 31 Oct 2018 download) joined to ``chem_prop.tsv`` (InChIKey
per MNXM). ``reconstruct_from_metanetx`` FAILS LOUD on the needs-reconstruction sentinel so an
unresolved source can never be silently scored (mirrors ``metaboliteannotator.fetch_maf_set``). The
offline unit tests drive the transform on an in-memory Table 9 fixture, so it is fully testable now.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import pandas as pd

from ..config import PHAM_DISAMBIGUATION, PHAM_NEEDS_RECONSTRUCTION_SENTINEL, PhamDisambiguationDatasetConfig

# Canonical raw-table columns (one row per (ambiguous name, candidate) pair) -> candidate raw headers
# (case-insensitive, first match wins). The ambiguous NAME and the candidate INCHIKEY are REQUIRED (the
# InChIKey is the independent oracle); the rest are provenance/coverage.
NAME_CANDIDATES: tuple[str, ...] = ("metabolite_name", "name", "abbreviation", "Abbreviation")
INCHIKEY_CANDIDATES: tuple[str, ...] = ("inchikey", "inchi_key", "InChIKey", "InChI Key")
CANDIDATE_ID_CANDIDATES: tuple[str, ...] = ("candidate_id", "database_id", "id", "IDs in Database")
DATABASE_CANDIDATES: tuple[str, ...] = ("source_database", "database", "Database")
METANETX_CANDIDATES: tuple[str, ...] = ("metanetx_id", "mnx_id", "MetaNetX ID", "mnxm")
COMPOUND_CANDIDATES: tuple[str, ...] = ("compound_name", "compound", "Compound(s)")


class SourceNotReconstructedError(RuntimeError):
    """Raised when a load is attempted against the needs-reconstruction placeholder source.

    The Pham paper ships no downloadable SI, so the real ambiguous-name population must be
    RECONSTRUCTED from MetaNetX (``chem_xref.tsv`` name<->ID @ 2018-10-31 joined to ``chem_prop.tsv``
    for independent InChIKeys). This guard refuses a placeholder before any scoring, exactly as
    ``metaboliteannotator`` refuses a needs-fetching accession.
    """


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _norm(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _resolve_column(raw_df: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    """First raw header matching any candidate (case-insensitive, exact after strip)."""
    lookup = {str(c).strip().lower(): c for c in raw_df.columns}
    for cand in candidates:
        hit = lookup.get(cand.strip().lower())
        if hit is not None:
            return hit
    return None


def first_block(inchikey: Any) -> str | None:
    """First InChIKey block (2-D connectivity skeleton), or None if absent/blank.

    Duplicated small helper (not imported from the scorer) so the adapter has no scorer dependency;
    identical semantics to ``structure_oracle_scorer.first_block``.
    """
    if inchikey is None or (isinstance(inchikey, float) and pd.isna(inchikey)):
        return None
    s = str(inchikey).strip()
    if not s or s.lower() == "nan":
        return None
    return s.split("-")[0]


def _candidate_curie(candidate_id: str, database: str) -> str:
    """A candidate identifier as a CURIE: keep an existing prefix, else prefix with its database.

    Table 9 ships DB-specific ids (``MetaCyc:SUC``, bare ``188980`` under Reactome, ``C01081`` under
    KEGG). An already-prefixed value is kept as-is; a bare value is prefixed with its source database
    so the coverage/traceability column is unambiguous.
    """
    cid = _norm(candidate_id)
    if not cid:
        return ""
    if ":" in cid:
        return cid
    db = _norm(database)
    return f"{db}:{cid}" if db else cid


def reconstruct_from_metanetx(
    source: Any,
    config: PhamDisambiguationDatasetConfig = PHAM_DISAMBIGUATION,
) -> pd.DataFrame:
    """Reconstruct the raw ambiguous-name candidate table from MetaNetX (network/data path).

    The paper ships no SI, so the real population is rebuilt by joining MetaNetX ``chem_xref.tsv``
    (name<->ID crosswalk, 31 Oct 2018) to ``chem_prop.tsv`` (InChIKey per MNXM bridge id). This is the
    INDEPENDENT structure source (disjoint from BioMapper's resolver). Isolated here so the transform
    (``build_input_df``/``build_card``) is unit-testable without it. FAILS LOUD on the needs-
    reconstruction sentinel before any work, so an unresolved source is never silently scored.

    Not exercised by the offline suite (needs the two MetaNetX bulk files); the concrete join is a
    follow-on once the files are pinned. Kept as the single fail-loud entry so the scaffold refuses to
    score a placeholder.
    """
    if isinstance(source, str) and source.strip().startswith(PHAM_NEEDS_RECONSTRUCTION_SENTINEL):
        raise SourceNotReconstructedError(
            f"source {source!r} is a needs-reconstruction placeholder: Pham et al. 2019 "
            f"(DOI {config.source_doi}, PMID {config.source_pmid}) ships NO downloadable supplementary "
            f"data. The ambiguous-name population must be reconstructed from MetaNetX chem_xref.tsv "
            f"(name<->ID, 31 Oct 2018 download) joined to chem_prop.tsv (independent InChIKey per MNXM). "
            f"Supply the reconstructed raw table (or the two MetaNetX files) before scoring."
        )
    raise SourceNotReconstructedError(
        "reconstruct_from_metanetx is a fail-loud placeholder: the MetaNetX chem_xref/chem_prop join is "
        "a follow-on. Pass a reconstructed raw DataFrame (or the Table 9 fixture) to load_pham instead."
    )


def build_input_df(
    raw_df: pd.DataFrame,
    config: PhamDisambiguationDatasetConfig = PHAM_DISAMBIGUATION,
) -> pd.DataFrame:
    """Build the mapper-ready input_df: ambiguous NAME query + held-out referent-SET gold columns.

    One row per unique ambiguous name. For each name, collapse its candidate rows into:
      - ``gold_referent_inchikey_column``: ``|``-delimited DISTINCT full InChIKeys (referent set, the
        oracle — order-preserving dedup on the InChIKey first-block so charge/stereo variants of the
        same skeleton collapse to one referent);
      - ``gold_referent_id_column``: ``|``-delimited candidate CURIEs across DBs (coverage/traceability);
      - ``gold_metanetx_column``: ``|``-delimited distinct MNXM bridge ids (independent-source provenance);
      - ``referent_count_column``: number of DISTINCT structural referents (the ambiguity degree).

    A blank name is dropped (nothing to query). A name with fewer than ``config.min_referents`` distinct
    referents is DROPPED — it is not a disambiguation case (documented, never fabricated).
    """
    name_raw = _resolve_column(raw_df, NAME_CANDIDATES)
    ik_raw = _resolve_column(raw_df, INCHIKEY_CANDIDATES)
    if name_raw is None:
        raise KeyError(
            f"Pham raw table is missing a recognizable ambiguous-name column; tried {NAME_CANDIDATES!r} "
            f"against {list(raw_df.columns)!r}"
        )
    if ik_raw is None:
        raise KeyError(
            f"Pham raw table is missing a recognizable InChIKey column (the independent structure "
            f"oracle); tried {INCHIKEY_CANDIDATES!r} against {list(raw_df.columns)!r}"
        )
    cid_raw = _resolve_column(raw_df, CANDIDATE_ID_CANDIDATES)
    db_raw = _resolve_column(raw_df, DATABASE_CANDIDATES)
    mnx_raw = _resolve_column(raw_df, METANETX_CANDIDATES)

    # Group candidates by ambiguous name, preserving first-appearance order for determinism.
    order: list[str] = []
    groups: dict[str, dict[str, Any]] = {}
    for _, row in raw_df.iterrows():
        name = _norm(row[name_raw])
        if not name:
            continue  # blank name — nothing to query
        rec = groups.get(name)
        if rec is None:
            rec = {"inchikeys": {}, "curies": [], "mnx": []}  # block -> full inchikey (dedup by skeleton)
            groups[name] = rec
            order.append(name)
        ik = _norm(row[ik_raw])
        block = first_block(ik)
        if block is not None and block not in rec["inchikeys"]:
            rec["inchikeys"][block] = ik  # first full InChIKey seen for this connectivity skeleton
        curie = _candidate_curie(_norm(row[cid_raw]) if cid_raw else "", _norm(row[db_raw]) if db_raw else "")
        if curie and curie not in rec["curies"]:
            rec["curies"].append(curie)
        mnx = _norm(row[mnx_raw]) if mnx_raw else ""
        if mnx and mnx not in rec["mnx"]:
            rec["mnx"].append(mnx)

    rows: list[dict[str, Any]] = []
    for name in order:
        rec = groups[name]
        referent_count = len(rec["inchikeys"])
        if referent_count < config.min_referents:
            continue  # not a disambiguation case — drop (documented)
        rows.append(
            {
                config.name_column: name,
                config.gold_referent_inchikey_column: "|".join(rec["inchikeys"].values()),
                config.gold_referent_id_column: "|".join(rec["curies"]),
                config.gold_metanetx_column: "|".join(rec["mnx"]),
                config.referent_count_column: referent_count,
            }
        )
    columns = [
        config.name_column,
        config.gold_referent_inchikey_column,
        config.gold_referent_id_column,
        config.gold_metanetx_column,
        config.referent_count_column,
    ]
    return pd.DataFrame(rows, columns=columns)


def build_card(
    raw_df: pd.DataFrame,
    source_sha: str,
    config: PhamDisambiguationDatasetConfig = PHAM_DISAMBIGUATION,
) -> dict[str, Any]:
    """Build the dataset_card: N ambiguous names, ambiguity-degree summary, per-DB coverage, SHA, license."""
    input_df = build_input_df(raw_df, config)
    n = len(input_df)
    counts = input_df[config.referent_count_column].astype(int) if n else pd.Series([], dtype=int)
    mean_referents = float(counts.mean()) if n else 0.0
    max_referents = int(counts.max()) if n else 0

    # Per-database coverage: how many candidate CURIEs came from each surveyed DB (traceability).
    per_database: dict[str, int] = {db: 0 for db in config.databases}
    for cell in input_df.get(config.gold_referent_id_column, pd.Series([""] * n)):
        for curie in str(cell).split("|"):
            prefix = curie.split(":", 1)[0].strip() if ":" in curie else ""
            for db in config.databases:
                if prefix.lower() == db.lower():
                    per_database[db] += 1

    return {
        "dataset": config.key,
        "arm": config.arm,
        "entity_type": config.entity_type,
        "input_type": config.input_type,
        "target_vocabs": list(config.target_vocabs),
        "n_ambiguous_names": n,
        "min_referents": config.min_referents,
        "ambiguity_degree": {"mean_referents": mean_referents, "max_referents": max_referents},
        "referent_oracle_column": config.gold_referent_inchikey_column,
        "per_database_candidate_coverage": per_database,
        "databases": list(config.databases),
        "source_status": config.source_status,
        "source_doi": config.source_doi,
        "source_pmid": config.source_pmid,
        "source_url": config.source_url,
        "source_sha256": source_sha,
        "license": config.license,
    }


@dataclass(frozen=True)
class PhamBundle:
    input_df: pd.DataFrame
    card: dict[str, Any]


def load_pham(
    source: bytes | str | pd.DataFrame,
    config: PhamDisambiguationDatasetConfig = PHAM_DISAMBIGUATION,
) -> PhamBundle:
    """Load from a reconstructed raw DataFrame (tests/fixture), raw CSV bytes, or a source string.

    A string source routes through ``reconstruct_from_metanetx``, which FAILS LOUD on the needs-
    reconstruction sentinel (no downloadable SI exists). A DataFrame's card SHA is pinned over its
    canonical CSV bytes so the pin is deterministic for tests.
    """
    if isinstance(source, pd.DataFrame):
        raw_df = source
        raw_bytes = raw_df.to_csv(index=False).encode("utf-8")
    elif isinstance(source, bytes):
        raw_bytes = source
        import io

        raw_df = pd.read_csv(io.BytesIO(raw_bytes), dtype=str).fillna("")
    elif isinstance(source, str):
        raw_df = reconstruct_from_metanetx(source, config)  # fails loud on placeholder
        raw_bytes = raw_df.to_csv(index=False).encode("utf-8")
    else:
        raise TypeError(f"unsupported source type {type(source)!r}")

    sha = sha256_bytes(raw_bytes)
    return PhamBundle(input_df=build_input_df(raw_df, config), card=build_card(raw_df, sha, config))
