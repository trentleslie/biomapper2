"""Pham et al. 2019 name-DISAMBIGUATION adapter (metabolite arm — referent-set structure oracle).

Turns the paper's ambiguous-name regime into a mapper-ready ``input_df`` (the bare ambiguous NAME
query + a held-out SET of legitimate structural referents) and a ``dataset_card`` recording the
population sizes (total names + ambiguous subset), ambiguity degree, per-source coverage, the pinned
MetaNetX release/SHA/md5, and license.

Regime (why this arm is different):
  - The other metabolite arms are one name -> one gold InChIKey. Pham's finding is that a single
    name/abbreviation (``tmp``, ``suc``, ``PPP``, ``H``) maps to STRUCTURALLY-DISTINCT compounds across
    the surveyed databases. So the gold is a SET of distinct InChIKey first-blocks (the name's
    legitimate referents), and "correct" is STRUCTURAL-MEMBERSHIP (BioMapper lands on SOME real
    referent), never "picked the one true structure" — there isn't one. See ``scorers/pham_scorer.py``.
  - The approved scoring design scores the FULL reconstructed population (every name with >= 1
    resolvable structural referent) and BREAKS OUT the ambiguous subset (>= 2 distinct referents) as
    the headline. So the adapter no longer pre-filters to ambiguous-only: a name with a single referent
    is retained (``min_referents=1``); only a blank name or a name with zero resolvable structures is
    dropped (documented, never fabricated).

Circularity guard (the load-bearing design point):
  - The referent InChIKeys are supplied by an INDEPENDENT source — MetaNetX ``chem_prop.tsv`` (the
    paper's own MNXRef bridge namespace, which ships a curated InChIKey per MNXM id), cross-checked
    against PubChem-by-name (disagreements are FLAGGED, never silently trusted) — and preserved
    VERBATIM in the held-out gold column. Zero shared infra with BioMapper's resolver. Only BioMapper's
    PREDICTION is resolved through the KG oracle (scorer).
  - The mapper is later called with ``name_column=config.name_column`` and ``provided_id_columns=[]``
    — the gold columns ride along untouched and are consumed only by the scorer.

RECONSTRUCTION (2026-07-16): the paper ships NO supplementary data file (verified against the
EuropePMC full-text XML for PMC6409771). The ambiguous-name population is reconstructed from the
paper's own inputs — MetaNetX ``chem_xref.tsv`` (its ``description`` field is a ``||``-delimited list
of cross-database synonym NAMES per MNXM id) joined to ``chem_prop.tsv`` (INDEPENDENT curated InChIKey
per MNXM). Per the approved design the CURRENT MetaNetX release is used (4.5, dated 2025/08/13) — NOT
the paper's 2018 snapshot — and the exact files are SHA/md5-pinned on the card. ``reconstruct_from_
metanetx`` FAILS LOUD on the needs-reconstruction sentinel so an unresolved source can never be
silently scored (mirrors ``metaboliteannotator.fetch_maf_set``). The offline unit tests drive the
transform + the parse/group logic on tiny in-memory chem_prop/chem_xref fixtures, so it is fully
testable without the 1.4 GB bulk files.
"""

from __future__ import annotations

import contextlib
import hashlib
import re
import socket
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..config import (
    METANETX_FTP_BASE,
    METANETX_RELEASE,
    PHAM_DISAMBIGUATION,
    PHAM_NEEDS_RECONSTRUCTION_SENTINEL,
    PhamDisambiguationDatasetConfig,
)

# Canonical raw-table columns (one row per (ambiguous name, candidate) pair) -> candidate raw headers
# (case-insensitive, first match wins). The ambiguous NAME and the candidate INCHIKEY are REQUIRED (the
# InChIKey is the independent oracle); the rest are provenance/coverage.
NAME_CANDIDATES: tuple[str, ...] = ("metabolite_name", "name", "abbreviation", "Abbreviation")
INCHIKEY_CANDIDATES: tuple[str, ...] = ("inchikey", "inchi_key", "InChIKey", "InChI Key")
CANDIDATE_ID_CANDIDATES: tuple[str, ...] = ("candidate_id", "database_id", "id", "IDs in Database")
DATABASE_CANDIDATES: tuple[str, ...] = ("source_database", "database", "Database")
METANETX_CANDIDATES: tuple[str, ...] = ("metanetx_id", "mnx_id", "MetaNetX ID", "mnxm")
COMPOUND_CANDIDATES: tuple[str, ...] = ("compound_name", "compound", "Compound(s)")

# MetaNetX ``chem_xref`` descriptions use this exact string for obsolete/secondary cross-refs that carry
# NO real name — never treat it as a metabolite name.
_NON_NAME_DESCRIPTIONS: frozenset[str] = frozenset({"secondary/obsolete/fantasy identifier"})


class SourceNotReconstructedError(RuntimeError):
    """Raised when a load is attempted against the needs-reconstruction placeholder source.

    The Pham paper ships no downloadable SI, so the real ambiguous-name population must be
    RECONSTRUCTED from MetaNetX (``chem_xref.tsv`` name<->MNXM joined to ``chem_prop.tsv`` for
    independent InChIKeys). This guard refuses a placeholder before any scoring, exactly as
    ``metaboliteannotator`` refuses a needs-fetching accession.
    """


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def md5_file(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _norm(value: Any) -> str:
    return "" if value is None else str(value).strip()


def normalize_name(name: Any) -> str:
    """Ambiguity grouping key: casefolded, whitespace-collapsed name (empty for a blank name).

    Case/whitespace variants of the same string (``TMP``/``tmp``, ``L-Alanine``/``L-ALANINE  ``)
    collapse to ONE ambiguous name so distinct source-database spellings do not inflate the population.
    The display name kept for the mapper query is the FIRST-SEEN original form (see the population
    builder) — the query stays human/resolver-friendly while grouping stays case-insensitive.
    """
    s = _norm(name)
    if not s:
        return ""
    return " ".join(s.split()).casefold()


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


# ==================================================================================================
# LIPID vs NON-LIPID classifier (documented, defensible) — see PhamDisambiguationDatasetConfig.
# ==================================================================================================
#
# A referent (one distinct structure of an ambiguous name) is classified LIPID by two signals, the
# namespace signal PREFERRED over the name-pattern fallback:
#
#   1. Namespace / cross-reference signal (preferred, authoritative): the referent's MetaNetX MNXM id
#      carries a cross-reference into a dedicated LIPID database namespace — LIPID MAPS (``lipidmaps``)
#      or SwissLipids (``slm``). A compound that LIPID MAPS / SwissLipids curate as a lipid IS a lipid;
#      this is an independent curatorial judgment, not a string heuristic.
#   2. Canonical lipid-shorthand NAME pattern (fallback, only when signal 1 is absent): the referent's
#      compound name follows the community lipid shorthand — a lipid-class abbreviation followed by a
#      composition (``TG(``, ``PC(``, ``PE(``, ``Cer(``, ``SM(`` ...) or an acyl-chain shorthand with
#      two ``carbons:double-bonds`` chains joined by ``/`` (``18:1/16:0``, ``d18:1/24:0``).
#
# A NAME is assigned to the LIPID stratum when its referents are PREDOMINANTLY lipids (>= 50% of its
# distinct referents are lipid); otherwise NON-lipid. The >=50% (ties -> lipid) rule keeps the NON-lipid
# stratum — the reported headline — PURE: a name only lands there when a strict majority of its
# referents are non-lipids.
#
# False-positive / false-negative risk (documented, not hidden):
#   - FALSE POSITIVE (non-lipid wrongly called lipid): a non-lipid name that (a) happens to have a
#     LIPID MAPS / SwissLipids xref — rare, those namespaces are lipid-scoped — or (b) matches the
#     shorthand regex by accident. The regex requires either a leading lipid-class token immediately
#     followed by ``(``/space, or a TWO-chain ``a:b/c:d`` acyl shorthand, both of which are highly
#     lipid-specific, so accidental matches are unlikely. A false positive removes a real non-lipid case
#     from the headline stratum (conservative: it can only shrink, never inflate, the headline).
#   - FALSE NEGATIVE (lipid wrongly called non-lipid): a lipid with NO LIPID MAPS / SwissLipids xref AND
#     a full IUPAC name (no shorthand) — this leaks into the non-lipid stratum. The namespace signal
#     catches the large majority of genuine lipids (LIPID MAPS + SwissLipids are the two dominant lipid
#     resources MetaNetX integrates), so residual leakage is small; it is the one direction that could
#     contaminate the headline, so the per-name stratum + referent counts are persisted on the card for
#     audit. Neither signal fabricates chemistry — both read MetaNetX's own curated cross-refs / names.

# MetaNetX chem_xref source-namespace prefixes for the two dedicated lipid resources. Confirmed against
# the real chem_xref.tsv (release 4.5), which carries case + "model" (``M``-suffixed) spelling variants:
# SwissLipids appears as ``slm:`` / ``SLM:`` and LIPID MAPS as ``lipidmaps:`` / ``lipidmapsM:``. All are
# lowercased before the check, so the set enumerates the lowercased variants.
LIPID_SOURCE_PREFIXES: frozenset[str] = frozenset({"slm", "lipidmaps", "lipidmapsm"})

# Fallback name-pattern signal (used ONLY when a referent has no lipid-namespace cross-ref). Anchored,
# case-insensitive lipid-class token immediately followed by a composition delimiter.
_LIPID_CLASS_RE = re.compile(
    r"(?i)^(?:TAG|TG|DAG|DG|MAG|MG|PC|PE|PS|PI|PG|PA|PIP[123]?|BMP|CL|LPC|LPE|LPS|LPI|LPG|LPA"
    r"|CER|SM|HEX2?CER|GLCCER|GALCER|LACCER|CE|FAHFA|FA|WE|MGDG|DGDG|SQDG|SPH|CoQ)[\s(]"
)
# Two-chain acyl shorthand (``18:1/16:0``, ``d18:1/24:0``) — highly lipid-specific, low false-positive.
_LIPID_ACYL_RE = re.compile(r"(?i)\b[dtme]?\d{1,2}:\d{1,2}/\d{1,2}:\d{1,2}\b")


def name_is_lipid_pattern(name: Any) -> bool:
    """True iff ``name`` matches the canonical lipid-shorthand fallback pattern (class token or acyl)."""
    s = _norm(name)
    if not s:
        return False
    return bool(_LIPID_CLASS_RE.match(s) or _LIPID_ACYL_RE.search(s))


def classify_referent_lipid(compound_name: Any, source_prefixes: Iterable[str]) -> bool:
    """Classify one referent LIPID/non-lipid. Namespace signal (LIPID MAPS / SwissLipids xref) preferred;
    the lipid-shorthand name pattern is the fallback used only when no lipid-namespace signal is present.
    """
    prefixes = {str(p).strip().lower() for p in source_prefixes if str(p).strip()}
    if prefixes & LIPID_SOURCE_PREFIXES:
        return True
    return name_is_lipid_pattern(compound_name)


def name_stratum(is_lipid_flags: Iterable[bool]) -> str:
    """Stratum for a name from its distinct referents' lipid flags: ``"lipid"`` iff >= 50% are lipid.

    A name with no resolvable referents is ``"non_lipid"`` (it is not a lipid case). The >= 50% rule
    (ties -> lipid) keeps the reported NON-lipid headline stratum pure — a name lands there only when a
    strict majority of its referents are non-lipids.
    """
    flags = list(is_lipid_flags)
    if not flags:
        return "non_lipid"
    return "lipid" if (sum(1 for f in flags if f) / len(flags)) >= 0.5 else "non_lipid"


def _prefix_of(source_curie: str) -> str:
    """Namespace prefix of a chem_xref source token (``lipidmaps:LMFA...`` -> ``lipidmaps``)."""
    s = _norm(source_curie)
    return s.split(":", 1)[0].strip().lower() if ":" in s else s.strip().lower()


def _truthy(value: Any) -> bool:
    """Parse a lipid flag from a raw cell that may be a bool or a CSV-roundtripped string."""
    if isinstance(value, bool):
        return value
    return _norm(value).lower() in {"1", "true", "yes", "t"}


def _candidate_curie(candidate_id: str, database: str) -> str:
    """A candidate identifier as a CURIE: keep an existing prefix, else prefix with its database."""
    cid = _norm(candidate_id)
    if not cid:
        return ""
    if ":" in cid:
        return cid
    db = _norm(database)
    return f"{db}:{cid}" if db else cid


# ==================================================================================================
# MetaNetX reconstruction — the real ambiguous-name population from chem_xref + chem_prop.
# ==================================================================================================


@dataclass(frozen=True)
class MetaNetXFiles:
    """The two pinned MetaNetX bulk files + their provenance (release, date, SHA-256, md5).

    ``chem_prop_path`` ships an INDEPENDENT curated InChIKey per MNXM id (the structure oracle);
    ``chem_xref_path``'s ``description`` field ships the ``||``-delimited cross-database synonym NAMES
    per MNXM (the name<->structure crosswalk). The SHA/md5 pins make the mutable "current release"
    reproducible.
    """

    chem_prop_path: str
    chem_xref_path: str
    release: str = METANETX_RELEASE
    version: str = ""  # MNXref VERSION header (e.g. "4.5")
    version_date: str = ""  # MNXref DATE header (e.g. "2025/08/13")
    chem_prop_sha256: str = ""
    chem_xref_sha256: str = ""
    chem_prop_md5: str = ""
    chem_xref_md5: str = ""

    def provenance(self) -> dict[str, Any]:
        return {
            "source": "MetaNetX/MNXref",
            "release": self.release,
            "version": self.version,
            "version_date": self.version_date,
            "chem_prop": {"sha256": self.chem_prop_sha256, "md5": self.chem_prop_md5},
            "chem_xref": {"sha256": self.chem_xref_sha256, "md5": self.chem_xref_md5},
            "ftp_base": METANETX_FTP_BASE,
        }


@contextlib.contextmanager
def _force_ipv4() -> Iterator[None]:
    """Force IPv4 for the duration of the block (the desktop's IPv6 route to some hosts is dead).

    Filters ``socket.getaddrinfo`` to ``AF_INET`` results only, so ``requests`` never attempts an
    IPv6 connection that hangs. Restored on exit.
    """
    orig = socket.getaddrinfo

    def ipv4_only(host, port, family=0, type=0, proto=0, flags=0):  # noqa: A002 - shadow ok, socket API
        return orig(host, port, socket.AF_INET, type, proto, flags)

    socket.getaddrinfo = ipv4_only  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.getaddrinfo = orig  # type: ignore[assignment]


def _metanetx_url(release: str, filename: str) -> str:
    return f"{METANETX_FTP_BASE}/{release}/{filename}"


def _parse_header_version(path: str) -> tuple[str, str]:
    """Read the MNXref ``#VERSION`` / ``#DATE`` from a chem_* file header (best effort)."""
    version = ""
    date = ""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.startswith("#"):
                break
            up = line.upper()
            if "VERSION:" in up and not version:
                version = line.split(":", 1)[1].strip()
            elif "DATE:" in up and not date:
                date = line.split(":", 1)[1].strip()
            if version and date:
                break
    return version, date


def fetch_metanetx_files(
    dest_dir: str,
    release: str = METANETX_RELEASE,
    *,
    timeout: float = 1800.0,
    verify_md5: bool = True,
) -> MetaNetXFiles:
    """Download ``chem_prop.tsv`` + ``chem_xref.tsv`` for ``release`` (IPv4-forced), pin SHA/md5.

    Network is isolated here so the transform/parse are unit-testable without the 1.4 GB files.
    Verifies each file against the upstream ``.md5`` (fail-loud on mismatch) and records SHA-256 +
    md5 + the MNXref VERSION/DATE header for reproducibility.
    """
    import os

    import requests

    os.makedirs(dest_dir, exist_ok=True)
    paths: dict[str, str] = {}
    md5s: dict[str, str] = {}
    with _force_ipv4():
        for filename in ("chem_prop.tsv", "chem_xref.tsv"):
            dest = os.path.join(dest_dir, filename)
            with requests.get(_metanetx_url(release, filename), timeout=timeout, stream=True) as resp:
                resp.raise_for_status()
                with open(dest, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=1 << 20):
                        fh.write(chunk)
            paths[filename] = dest
            if verify_md5:
                want = requests.get(_metanetx_url(release, f"{filename}.md5"), timeout=60).text.split()[0]
                got = md5_file(dest)
                if want and got != want:
                    raise RuntimeError(
                        f"MetaNetX {filename} md5 mismatch (release {release}): got {got}, upstream {want} "
                        f"— refusing to reconstruct from a corrupt/altered download."
                    )
                md5s[filename] = got
            else:
                md5s[filename] = md5_file(dest)

    version, date = _parse_header_version(paths["chem_prop.tsv"])
    return MetaNetXFiles(
        chem_prop_path=paths["chem_prop.tsv"],
        chem_xref_path=paths["chem_xref.tsv"],
        release=release,
        version=version,
        version_date=date,
        chem_prop_sha256=sha256_file(paths["chem_prop.tsv"]),
        chem_xref_sha256=sha256_file(paths["chem_xref.tsv"]),
        chem_prop_md5=md5s["chem_prop.tsv"],
        chem_xref_md5=md5s["chem_xref.tsv"],
    )


def _iter_data_rows(path: str) -> Iterator[list[str]]:
    """Yield tab-split fields for each non-comment data row of a MetaNetX chem_* file."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line or line.startswith("#"):
                continue
            yield line.rstrip("\n").split("\t")


def parse_chem_prop(path: str) -> dict[str, tuple[str, str]]:
    """Stream ``chem_prop.tsv`` -> ``{MNXM id: (InChIKey, name)}`` for rows carrying an InChIKey.

    Columns: ``#ID name reference formula charge mass InChI InChIKey SMILES``. Only MNXM ids with a
    non-empty InChIKey are kept — a compound with no independent structure cannot anchor a referent.
    """
    prop: dict[str, tuple[str, str]] = {}
    for f in _iter_data_rows(path):
        if len(f) < 8:
            continue
        mnxm = f[0].strip()
        inchikey = f[7].strip()
        if not mnxm or not inchikey:
            continue
        prop[mnxm] = (inchikey, f[1].strip())
    return prop


def _iter_chem_xref_names(path: str) -> Iterator[tuple[str, str, str]]:
    """Stream ``chem_xref.tsv`` -> ``(source_curie, MNXM id, synonym_name)`` per synonym.

    Columns: ``#source ID description``. ``description`` is a ``||``-delimited list of cross-database
    synonym names for the (source, MNXM) mapping; each real synonym is yielded once. The obsolete/
    secondary sentinel description carries no name and is skipped.
    """
    for f in _iter_data_rows(path):
        if len(f) < 3:
            continue
        source = f[0].strip()
        mnxm = f[1].strip()
        description = f[2].strip()
        if not mnxm or not description or description in _NON_NAME_DESCRIPTIONS:
            continue
        for syn in description.split("||"):
            syn = syn.strip()
            if syn:
                yield source, mnxm, syn


@dataclass
class _NameGroup:
    display: str
    block_ik: dict[str, str]  # first-seen full InChIKey per connectivity skeleton (the referent set)
    block_mnxm: dict[str, str]
    block_name: dict[str, str]
    block_curie: dict[str, str]
    block_is_lipid: dict[str, bool] = field(default_factory=dict)  # per-referent lipid flag (finalized)

    def stratum(self) -> str:
        """LIPID/non-lipid stratum for this name from its referents' lipid flags (>= 50% -> lipid)."""
        return name_stratum(self.block_is_lipid.get(b, False) for b in self.block_ik)


@dataclass
class ReferentPopulation:
    """The reconstructed name -> referent-set population + summary counts (full + per stratum)."""

    groups: dict[str, _NameGroup]  # normalized-name -> group
    n_names_total: int
    n_ambiguous: int  # names with >= ambiguous_min_referents distinct structural referents
    n_lipid: int = 0  # full-population names in the LIPID stratum
    n_non_lipid: int = 0  # full-population names in the NON-lipid stratum
    n_ambiguous_lipid: int = 0  # ambiguous-subset names in the LIPID stratum
    n_ambiguous_non_lipid: int = 0  # ambiguous-subset names in the NON-lipid stratum (the headline)

    def ambiguous_names(self, ambiguous_min: int = 2) -> list[str]:
        """Normalized names with >= ``ambiguous_min`` distinct structural referents (deterministic order)."""
        return [k for k, g in self.groups.items() if len(g.block_ik) >= ambiguous_min]

    def names_in_stratum(self, stratum: str, *, ambiguous_min: int | None = None) -> list[str]:
        """Normalized names in ``stratum`` (``"lipid"``/``"non_lipid"``), deterministic order.

        ``ambiguous_min`` restricts to names with >= that many distinct referents (the ambiguous
        subset); ``None`` returns the full population of the stratum.
        """
        out: list[str] = []
        for k, g in self.groups.items():
            if g.stratum() != stratum:
                continue
            if ambiguous_min is not None and len(g.block_ik) < ambiguous_min:
                continue
            out.append(k)
        return out


def build_referent_population(
    prop: dict[str, tuple[str, str]],
    xref_path: str,
    config: PhamDisambiguationDatasetConfig = PHAM_DISAMBIGUATION,
) -> ReferentPopulation:
    """Group MetaNetX synonym names -> distinct InChIKey first-blocks (the referent SET per name).

    Each ``chem_xref`` synonym that maps (via its MNXM id) to a ``chem_prop`` InChIKey contributes that
    structure to the name's referent set. Distinct connectivity skeletons (first-blocks) are the
    referents; charge/stereo variants of one skeleton collapse to a single referent (first full
    InChIKey kept). A name with >= ``config.ambiguous_min_referents`` distinct skeletons is ambiguous.
    """
    groups: dict[str, _NameGroup] = {}
    # Global MNXM -> set of source-namespace prefixes (the LIPID MAPS / SwissLipids signal is authoritative
    # at the MNXM level: a lipid's lipidmaps/slm xref may ride a DIFFERENT synonym row than the ambiguous
    # name, so the namespace signal is accumulated across ALL of the MNXM's xref rows, not just this name's).
    mnxm_prefixes: dict[str, set[str]] = {}
    for source, mnxm, syn in _iter_chem_xref_names(xref_path):
        mnxm_prefixes.setdefault(mnxm, set()).add(_prefix_of(source))
        rec = prop.get(mnxm)
        if rec is None:
            continue  # no independent structure -> cannot anchor a referent
        inchikey, compound_name = rec
        block = first_block(inchikey)
        if block is None:
            continue
        key = normalize_name(syn)
        if not key:
            continue
        g = groups.get(key)
        if g is None:
            g = _NameGroup(display=syn.strip(), block_ik={}, block_mnxm={}, block_name={}, block_curie={})
            groups[key] = g
        if block not in g.block_ik:
            g.block_ik[block] = inchikey
            g.block_mnxm[block] = mnxm
            g.block_name[block] = compound_name
            # Representative source CURIE for this referent (source like ``chebi:57945`` is already a CURIE).
            g.block_curie[block] = source

    # Finalize per-referent lipid flags now that the full MNXM->prefixes map is complete (a referent's
    # lipidmaps/slm xref may have appeared on a later row than the referent's first sighting).
    for g in groups.values():
        for block, mnxm in g.block_mnxm.items():
            g.block_is_lipid[block] = classify_referent_lipid(
                g.block_name.get(block, ""), mnxm_prefixes.get(mnxm, set())
            )

    ambiguous_min = int(config.ambiguous_min_referents)
    n_ambiguous = 0
    n_lipid = n_non_lipid = n_ambiguous_lipid = n_ambiguous_non_lipid = 0
    for g in groups.values():
        stratum = g.stratum()
        is_amb = len(g.block_ik) >= ambiguous_min
        if stratum == "lipid":
            n_lipid += 1
        else:
            n_non_lipid += 1
        if is_amb:
            n_ambiguous += 1
            if stratum == "lipid":
                n_ambiguous_lipid += 1
            else:
                n_ambiguous_non_lipid += 1
    return ReferentPopulation(
        groups=groups,
        n_names_total=len(groups),
        n_ambiguous=n_ambiguous,
        n_lipid=n_lipid,
        n_non_lipid=n_non_lipid,
        n_ambiguous_lipid=n_ambiguous_lipid,
        n_ambiguous_non_lipid=n_ambiguous_non_lipid,
    )


def population_to_raw_table(
    population: ReferentPopulation,
    config: PhamDisambiguationDatasetConfig = PHAM_DISAMBIGUATION,
    *,
    names: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Emit the raw candidate table (one row per (name, referent)) that ``build_input_df`` consumes.

    ``names`` (normalized keys) restricts the emitted rows — used by the live smoke to materialize
    just the sampled names without rebuilding the whole population table.
    """
    selected = list(population.groups) if names is None else [normalize_name(n) for n in names]
    rows: list[dict[str, Any]] = []
    for key in selected:
        g = population.groups.get(key)
        if g is None:
            continue
        for block, full_ik in g.block_ik.items():
            curie = g.block_curie.get(block, "")
            db, _, cid = curie.partition(":") if ":" in curie else ("", "", curie)
            rows.append(
                {
                    "metabolite_name": g.display,
                    "source_database": db,
                    "candidate_id": cid,
                    "metanetx_id": g.block_mnxm.get(block, ""),
                    "compound_name": g.block_name.get(block, ""),
                    "inchikey": full_ik,
                    # Per-referent lipid flag (namespace-signal-aware; carried so build_input_df need not
                    # re-derive the namespace signal, which it cannot see from the raw table alone).
                    "is_lipid_referent": bool(g.block_is_lipid.get(block, False)),
                }
            )
    return pd.DataFrame(
        rows,
        columns=[
            "metabolite_name",
            "source_database",
            "candidate_id",
            "metanetx_id",
            "compound_name",
            "inchikey",
            "is_lipid_referent",
        ],
    )


def reconstruct_from_metanetx(
    source: Any,
    config: PhamDisambiguationDatasetConfig = PHAM_DISAMBIGUATION,
) -> pd.DataFrame:
    """Reconstruct the raw ambiguous-name candidate table from MetaNetX (data path).

    ``source`` is a ``MetaNetXFiles`` (the two pinned bulk files) -> the FULL reconstructed candidate
    table is built and returned. The needs-reconstruction SENTINEL string still FAILS LOUD (no
    downloadable SI exists), so an unresolved source is never silently scored.
    """
    if isinstance(source, MetaNetXFiles):
        prop = parse_chem_prop(source.chem_prop_path)
        population = build_referent_population(prop, source.chem_xref_path, config)
        return population_to_raw_table(population, config)
    if isinstance(source, str) and source.strip().startswith(PHAM_NEEDS_RECONSTRUCTION_SENTINEL):
        raise SourceNotReconstructedError(
            f"source {source!r} is a needs-reconstruction placeholder: Pham et al. 2019 "
            f"(DOI {config.source_doi}, PMID {config.source_pmid}) ships NO downloadable supplementary "
            f"data. Supply a MetaNetXFiles (chem_prop.tsv + chem_xref.tsv, release "
            f"{METANETX_RELEASE}) — or a reconstructed raw table — before scoring."
        )
    raise SourceNotReconstructedError(
        f"reconstruct_from_metanetx expects a MetaNetXFiles or the needs-reconstruction sentinel; got "
        f"{type(source)!r}. Pass the two pinned MetaNetX files (or a reconstructed raw DataFrame to "
        f"load_pham directly)."
    )


# ==================================================================================================
# PubChem cross-check (independent second source) — FLAG disagreements, never silently trust one source.
# ==================================================================================================


def crosscheck_pubchem(
    name_to_blocks: dict[str, set[str]],
    *,
    timeout: float = 30.0,
    sleep_s: float = 0.25,
) -> dict[str, dict[str, Any]]:
    """For each name, look up PubChem-by-name InChIKey(s) and FLAG disagreements with MetaNetX.

    Independent of BioMapper's resolver AND of MetaNetX: hits PubChem PUG-REST name->InChIKey (IPv4-
    forced). A name is FLAGGED (``agrees=False``) when PubChem returns structure(s) whose first-block
    is NOT among the MetaNetX referent blocks — i.e. the two independent sources disagree on what the
    name means. Never used to build gold (no circularity, no source-fusion) — only to surface
    disagreements for human review. A PubChem miss/error is recorded, not fatal.
    """
    import time

    import requests

    out: dict[str, dict[str, Any]] = {}
    with _force_ipv4():
        for name, mnx_blocks in name_to_blocks.items():
            entry: dict[str, Any] = {"metanetx_blocks": sorted(mnx_blocks)}
            try:
                url = (
                    "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
                    f"{requests.utils.quote(name)}/property/InChIKey/JSON"
                )
                resp = requests.get(url, timeout=timeout)
                if resp.status_code == 404:
                    entry.update({"pubchem_blocks": [], "agrees": None, "note": "pubchem-miss"})
                else:
                    resp.raise_for_status()
                    props = resp.json().get("PropertyTable", {}).get("Properties", [])
                    pc_blocks = sorted({fb for p in props if (fb := first_block(p.get("InChIKey")))})
                    entry.update(
                        {
                            "pubchem_blocks": pc_blocks,
                            "agrees": bool(pc_blocks) and bool(set(pc_blocks) & mnx_blocks),
                        }
                    )
            except Exception as exc:  # network/parse hiccup — record, do not abort the cross-check
                entry.update({"pubchem_blocks": [], "agrees": None, "note": f"error:{type(exc).__name__}"})
            out[name] = entry
            time.sleep(sleep_s)  # be gentle with PUG-REST (5 req/s cap)
    return out


def summarize_pubchem_crosscheck(crosscheck: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Aggregate ``crosscheck_pubchem`` output into agree / disagree / inconclusive counts.

    ``agrees`` is tri-state per name: ``True`` (PubChem-by-name shares >= 1 referent block with
    MetaNetX), ``False`` (the two independent sources disagree — flagged for review), or ``None`` (a
    PubChem miss/error — neither confirmed nor refuted). The summary is what the report cites, so the
    report can only ever state numbers that actually ran.
    """
    agree = sum(1 for e in crosscheck.values() if e.get("agrees") is True)
    disagree = sum(1 for e in crosscheck.values() if e.get("agrees") is False)
    inconclusive = sum(1 for e in crosscheck.values() if e.get("agrees") is None)
    return {
        "n_checked": len(crosscheck),
        "n_agree": agree,
        "n_disagree": disagree,
        "n_inconclusive": inconclusive,
    }


# ==================================================================================================
# Transform: raw candidate table -> mapper-ready input_df + dataset card.
# ==================================================================================================


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
    referents is DROPPED — at the default ``min_referents=1`` this only drops names with zero resolvable
    structures (documented, never fabricated); the full retained population feeds the scorer.
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
    cmpd_raw = _resolve_column(raw_df, COMPOUND_CANDIDATES)
    # The per-referent lipid flag is emitted by the MetaNetX reconstruction (``population_to_raw_table``);
    # when a raw table lacks it (hand-built DataFrame/CSV), each referent's lipid status is derived from
    # the fallback signals available on the row (source-database prefix + compound-name pattern).
    lipid_raw = _resolve_column(raw_df, (config.is_lipid_referent_column, "is_lipid_referent"))

    # Group candidates by ambiguous name, preserving first-appearance order for determinism. The grouping
    # KEY is ``normalize_name`` (casefold + whitespace-collapse) so case/whitespace variants of one name
    # (``suc``/``SUC``, ``L-Alanine``/``L-ALANINE  ``) collapse to a SINGLE referent set rather than
    # splitting into spurious one-referent rows (which would corrupt ``referent_count``/``n_ambiguous``).
    # The first-seen ORIGINAL display form is kept as the human/resolver-friendly query written to
    # ``config.name_column``. This mirrors the MetaNetX reconstruction path (``build_referent_population``).
    order: list[str] = []
    groups: dict[str, dict[str, Any]] = {}
    for _, row in raw_df.iterrows():
        display = _norm(row[name_raw])
        if not display:
            continue  # blank name — nothing to query
        key = normalize_name(display)
        rec = groups.get(key)
        if rec is None:
            # display -> first-seen original spelling (the query); block -> full inchikey (dedup by
            # skeleton); block_lipid -> per-referent lipid flag.
            rec = {"display": display, "inchikeys": {}, "curies": [], "mnx": [], "block_lipid": {}}
            groups[key] = rec
            order.append(key)
        ik = _norm(row[ik_raw])
        block = first_block(ik)
        if block is not None and block not in rec["inchikeys"]:
            rec["inchikeys"][block] = ik  # first full InChIKey seen for this connectivity skeleton
            if lipid_raw is not None:
                rec["block_lipid"][block] = _truthy(row[lipid_raw])
            else:  # fallback: derive lipid status from the row's own source prefix + compound name
                db_prefix = _prefix_of(_norm(row[db_raw])) if db_raw else ""
                cmpd = _norm(row[cmpd_raw]) if cmpd_raw else ""
                rec["block_lipid"][block] = classify_referent_lipid(cmpd, {db_prefix} if db_prefix else set())
        curie = _candidate_curie(_norm(row[cid_raw]) if cid_raw else "", _norm(row[db_raw]) if db_raw else "")
        if curie and curie not in rec["curies"]:
            rec["curies"].append(curie)
        mnx = _norm(row[mnx_raw]) if mnx_raw else ""
        if mnx and mnx not in rec["mnx"]:
            rec["mnx"].append(mnx)

    rows: list[dict[str, Any]] = []
    for key in order:
        rec = groups[key]
        referent_count = len(rec["inchikeys"])
        if referent_count < config.min_referents:
            continue  # no resolvable structure — drop (documented)
        rows.append(
            {
                config.name_column: rec["display"],
                config.gold_referent_inchikey_column: "|".join(rec["inchikeys"].values()),
                config.gold_referent_id_column: "|".join(rec["curies"]),
                config.gold_metanetx_column: "|".join(rec["mnx"]),
                config.referent_count_column: referent_count,
                config.stratum_column: name_stratum(rec["block_lipid"].values()),
            }
        )
    columns = [
        config.name_column,
        config.gold_referent_inchikey_column,
        config.gold_referent_id_column,
        config.gold_metanetx_column,
        config.referent_count_column,
        config.stratum_column,
    ]
    return pd.DataFrame(rows, columns=columns)


def build_card(
    raw_df: pd.DataFrame,
    source_sha: str,
    config: PhamDisambiguationDatasetConfig = PHAM_DISAMBIGUATION,
    *,
    metanetx: MetaNetXFiles | None = None,
    source_status: str | None = None,
) -> dict[str, Any]:
    """Build the dataset_card: full-population + ambiguous-subset sizes, ambiguity degree, per-DB
    coverage, MetaNetX provenance (SHA/md5/release), SHA, license."""
    input_df = build_input_df(raw_df, config)
    n = len(input_df)
    counts = input_df[config.referent_count_column].astype(int) if n else pd.Series([], dtype=int)
    ambiguous_min = int(config.ambiguous_min_referents)
    n_ambiguous = int((counts >= ambiguous_min).sum()) if n else 0
    amb_counts = counts[counts >= ambiguous_min] if n else pd.Series([], dtype=int)
    mean_referents = float(counts.mean()) if n else 0.0
    max_referents = int(counts.max()) if n else 0
    mean_amb_referents = float(amb_counts.mean()) if len(amb_counts) else 0.0

    # LIPID vs NON-LIPID stratum sizes (critical: quantifies how much of the population is the abbreviation
    # / cross-class ambiguity Pham is about vs lipid-isomer nomenclature that overlaps the LMSD arm).
    strata = input_df[config.stratum_column] if n else pd.Series([], dtype=str)
    is_amb = counts >= ambiguous_min if n else pd.Series([], dtype=bool)
    n_lipid = int((strata == "lipid").sum()) if n else 0
    n_non_lipid = int((strata == "non_lipid").sum()) if n else 0
    n_amb_lipid = int(((strata == "lipid") & is_amb).sum()) if n else 0
    n_amb_non_lipid = int(((strata == "non_lipid") & is_amb).sum()) if n else 0

    # Per-source coverage: how many candidate CURIEs came from each surveyed source-prefix (traceability).
    per_source: dict[str, int] = {}
    for cell in input_df.get(config.gold_referent_id_column, pd.Series([""] * n)):
        for curie in str(cell).split("|"):
            prefix = curie.split(":", 1)[0].strip() if ":" in curie else ""
            if prefix:
                per_source[prefix] = per_source.get(prefix, 0) + 1

    card: dict[str, Any] = {
        "dataset": config.key,
        "arm": config.arm,
        "entity_type": config.entity_type,
        "input_type": config.input_type,
        "target_vocabs": list(config.target_vocabs),
        "n_names": n,  # FULL reconstructed population (>= min_referents referents)
        "n_ambiguous": n_ambiguous,  # highlighted hard-case subset (>= ambiguous_min_referents)
        "min_referents": config.min_referents,
        "ambiguous_min_referents": ambiguous_min,
        # LIPID vs NON-LIPID stratification (approved 2026-07-16). Headline = the NON-lipid ambiguous
        # subset (Pham's distinct contribution); the lipid subset overlaps the LMSD arm.
        "strata": {
            "full_population": {"lipid": n_lipid, "non_lipid": n_non_lipid},
            "ambiguous_subset": {"lipid": n_amb_lipid, "non_lipid": n_amb_non_lipid},
            "lipid_classifier": {
                "namespace_signal": sorted(LIPID_SOURCE_PREFIXES),
                "rule": "referent lipid if MNXM has a LIPID MAPS/SwissLipids xref, else lipid-shorthand "
                "name pattern; name is lipid-stratum if >= 50% of its distinct referents are lipid",
            },
        },
        "ambiguity_degree": {
            "mean_referents": mean_referents,
            "max_referents": max_referents,
            "mean_ambiguous_referents": mean_amb_referents,
        },
        "referent_oracle_column": config.gold_referent_inchikey_column,
        "per_source_candidate_coverage": per_source,
        "databases": list(config.databases),
        "source_status": source_status if source_status is not None else config.source_status,
        "source_doi": config.source_doi,
        "source_pmid": config.source_pmid,
        "source_url": config.source_url,
        "source_sha256": source_sha,
        "license": config.license,
    }
    if metanetx is not None:
        card["metanetx"] = metanetx.provenance()
    return card


@dataclass(frozen=True)
class PhamBundle:
    input_df: pd.DataFrame
    card: dict[str, Any]


def load_pham(
    source: bytes | str | pd.DataFrame | MetaNetXFiles,
    config: PhamDisambiguationDatasetConfig = PHAM_DISAMBIGUATION,
) -> PhamBundle:
    """Load from MetaNetX files (real reconstruction), a reconstructed raw DataFrame/CSV bytes, or the
    needs-reconstruction sentinel (fails loud — no downloadable SI exists).

    For ``MetaNetXFiles`` the raw candidate table is reconstructed and the card records the pinned
    MetaNetX provenance; the card SHA is the combined SHA of the two source files (the mutable current
    release is reproducible from those pins, NOT from a giant reconstructed CSV). For a DataFrame/bytes
    the card SHA is pinned over the canonical CSV bytes so it is deterministic for tests.
    """
    metanetx: MetaNetXFiles | None = None
    source_status: str | None = None
    if isinstance(source, MetaNetXFiles):
        metanetx = source
        raw_df = reconstruct_from_metanetx(source, config)
        sha = sha256_bytes(f"{source.chem_prop_sha256}:{source.chem_xref_sha256}".encode())
        source_status = "resolved"
        return PhamBundle(
            input_df=build_input_df(raw_df, config),
            card=build_card(raw_df, sha, config, metanetx=metanetx, source_status=source_status),
        )
    if isinstance(source, pd.DataFrame):
        raw_df = source
        raw_bytes = raw_df.to_csv(index=False).encode("utf-8")
    elif isinstance(source, bytes):
        raw_bytes = source
        import io

        raw_df = pd.read_csv(io.BytesIO(raw_bytes), dtype=str).fillna("")
    elif isinstance(source, str):
        raw_df = reconstruct_from_metanetx(source, config)  # fails loud on placeholder / bad type
        raw_bytes = raw_df.to_csv(index=False).encode("utf-8")
    else:
        raise TypeError(f"unsupported source type {type(source)!r}")

    sha = sha256_bytes(raw_bytes)
    return PhamBundle(input_df=build_input_df(raw_df, config), card=build_card(raw_df, sha, config))


# ==================================================================================================
# Deterministic WITHIN-strata subsample for the gated run (mirrors RefMet: reservoir + seed, persisted).
# ==================================================================================================


def _stratum_n(stratum: str, config: PhamDisambiguationDatasetConfig) -> int | None:
    return config.subsample_n_lipid if stratum == "lipid" else config.subsample_n_non_lipid


def subsample_within_strata(
    input_df: pd.DataFrame,
    config: PhamDisambiguationDatasetConfig = PHAM_DISAMBIGUATION,
    *,
    ambiguous_only: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Reservoir-subsample EACH stratum independently to its per-stratum n (or keep it in full).

    The reconstructed ambiguous population is a lipid-isomer majority, so a single global subsample would
    swamp the NON-lipid headline. Each stratum is therefore sampled on its OWN so the non-lipid stratum
    keeps enough cases to report. Deterministic (seed ``config.subsample_seed``, first-appearance row
    order), so the scored subset is reproducible and persistable. Returns ``(subsampled_df, meta)`` where
    ``meta`` records per-stratum available/target/sampled counts + the seed.

    When ``ambiguous_only`` is True the population is first restricted to the genuine disambiguation
    cases — names with ``>= config.ambiguous_min_referents`` distinct structural referents — so the
    headline is scored on the hard slice, not a full-population sample where ambiguous names are a small
    minority (a full-population non-lipid draw yields only a handful of truly ambiguous names).
    """
    from .backbones import reservoir_sample

    seed = int(config.subsample_seed)
    if ambiguous_only:
        counts = input_df[config.referent_count_column].astype(int)
        input_df = input_df[counts >= int(config.ambiguous_min_referents)]
    strata_order = ["non_lipid", "lipid"]  # non-lipid first (the headline) for deterministic output order
    kept_frames: list[pd.DataFrame] = []
    meta: dict[str, Any] = {"seed": seed, "method": "reservoir", "ambiguous_only": ambiguous_only, "per_stratum": {}}
    stratum_series = input_df.get(config.stratum_column)
    for stratum in strata_order:
        if stratum_series is None:
            sub = input_df.iloc[0:0]
        else:
            sub = input_df[stratum_series == stratum]
        available = len(sub)
        target = _stratum_n(stratum, config)
        if target is None or available <= target:
            sampled_positions = list(range(available))  # keep the stratum in full
        else:
            sampled_positions = sorted(reservoir_sample(range(available), target, seed))
        kept = sub.iloc[sampled_positions]
        kept_frames.append(kept)
        meta["per_stratum"][stratum] = {
            "available": available,
            "target": target,
            "sampled": len(kept),
        }
    subsampled = pd.concat(kept_frames, ignore_index=True) if kept_frames else input_df.iloc[0:0]
    return subsampled, meta


def stratified_subsample_filename(key: str) -> str:
    """Filename for the persisted within-strata subsample beside the dataset card."""
    return f"{key}_stratified_subsample.csv"


def persist_stratified_subsample(subsampled_df: pd.DataFrame, key: str, out_dir: Any) -> Any:
    """Write the exact within-strata subsample beside the card (the scored input, reproducible)."""
    import os

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, stratified_subsample_filename(key))
    with open(path, "wb") as fh:
        fh.write(subsampled_df.to_csv(index=False).encode("utf-8"))
    return path
