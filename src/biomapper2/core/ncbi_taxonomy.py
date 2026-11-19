"""Pinned NCBI prokaryote taxonomy snapshot loader (16S taxon resolution, plan U3).

Why this exists
---------------
Kestrel hybrid-search rows carry no lineage, and its filters cannot separate kingdoms, so a 16S label such
as "Proteus" can commit the salamander (NCBITaxon:210425) instead of the bacterium (583). The taxon
annotator therefore checks every candidate against this offline snapshot: is the hit a prokaryote, is it
the non-prokaryote side of a homonym pair, and does one of its NCBI names equal the label's name at the
label's rank.

Files (all written by ``scripts/build_ncbi_taxon_snapshot.py`` from one NCBI taxdump)::

    prokaryote_taxa_<date>.tsv           taxid parent_taxid rank name name_class
    prokaryote_taxa_<date>.tsv.version   first non-empty line = the version stamped on taxon rows
    merged_<date>.tsv                    old_taxid new_taxid
    homonyms_<date>.tsv                  name prokaryote_taxids nonprokaryote_taxids (ids "|"-joined)

The node set is Bacteria (2) and Archaea (2157) from domain to genus plus every ancestor on each path, so
every parent pointer resolves inside the snapshot (the domain nodes have an empty parent). The parent
pointers are kept for PR2's lineage/LCA ladder; PR1 uses membership, homonymy, rank-scoped name lookup and
merged ids only.

The snapshot ships inside the package (``biomapper2/data/ncbi_taxonomy/``) and is read through
``importlib.resources``. ``config.NCBI_TAXONOMY_SNAPSHOT_PATH`` overrides it (path to the
``prokaryote_taxa_*.tsv`` file; the companion files are found next to it by date). A missing or malformed
snapshot raises :class:`NcbiTaxonomyError` at first use on the taxon path; nothing here degrades to "not a
prokaryote". A missing ``.version`` sidecar is tolerated with a loud warning and ``version() is None``.

Loading happens once per resolved source and is cached; ``reset()`` clears the cache (tests).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING

from .. import config

if TYPE_CHECKING:  # importlib.resources.abc is 3.11+; annotations only (requires-python >= 3.10)
    from importlib.resources.abc import Traversable

PACKAGED_DIR = ("data", "ncbi_taxonomy")
PACKAGED_SNAPSHOT = "prokaryote_taxa_2026-11-19.tsv"
TAXA_HEADER = ("taxid", "parent_taxid", "rank", "name", "name_class")
MERGED_HEADER = ("old_taxid", "new_taxid")
HOMONYM_HEADER = ("name", "prokaryote_taxids", "nonprokaryote_taxids")
SCIENTIFIC_NAME = "scientific name"
DOMAIN_TAXIDS = frozenset({2, 2157})
_TAXA_NAME = re.compile(r"^prokaryote_taxa_(?P<date>[0-9A-Za-z_.-]+)\.tsv$")
_INT = re.compile(r"^[1-9][0-9]*$")

logger = logging.getLogger(__name__)


class NcbiTaxonomyError(RuntimeError):
    """The NCBI taxonomy snapshot is missing or malformed."""


@dataclass(frozen=True)
class Node:
    taxid: int
    parent: int | None
    rank: str
    scientific_name: str
    names: tuple[tuple[str, str], ...]  # (name, name_class), scientific name first


@dataclass(frozen=True)
class Snapshot:
    """A parsed, immutable snapshot."""

    nodes: dict[int, Node]
    by_name: dict[str, tuple[int, ...]]  # casefolded name -> taxids carrying it (any kept class)
    merged: dict[int, int]  # old taxid -> current taxid
    homonyms: dict[str, frozenset[int]]  # casefolded name -> non-prokaryote taxids sharing it
    homonym_nonprokaryote: frozenset[int]
    version: str | None
    source: str

    def current_taxid(self, taxid: int) -> int | None:
        if taxid in self.nodes:
            return taxid
        return self.merged.get(taxid)

    def lookup(self, name: str, rank: str | None = None) -> list[int]:
        ids = self.by_name.get(name.strip().casefold(), ())
        return sorted(t for t in ids if rank is None or self.nodes[t].rank == rank)


def _parse_tsv(text: str, header: tuple[str, ...], source: str) -> list[list[str]]:
    lines = text.splitlines()
    if not lines or tuple(lines[0].rstrip("\r").split("\t")) != header:
        raise NcbiTaxonomyError(f"NCBI taxonomy {source}: expected the header {header!r}")
    rows = []
    for lineno, raw in enumerate(lines[1:], start=2):
        if not raw.strip():
            continue
        fields = raw.rstrip("\r").split("\t")
        if len(fields) != len(header):
            raise NcbiTaxonomyError(f"NCBI taxonomy {source}: malformed row {lineno}: {raw!r}")
        rows.append(fields)
    return rows


def _ids(field: str, source: str, lineno: int) -> list[int]:
    parts = field.split("|")
    if not all(_INT.match(p) for p in parts):
        raise NcbiTaxonomyError(f"NCBI taxonomy {source}: malformed taxid list on row {lineno}: {field!r}")
    return [int(p) for p in parts]


def _parse(taxa_text: str, merged_text: str, homonym_text: str, version_text: str | None, source: str) -> Snapshot:
    names: dict[int, list[tuple[str, str]]] = {}
    info: dict[int, tuple[int | None, str]] = {}
    for lineno, (tid, parent, rank, name, name_class) in enumerate(
        _parse_tsv(taxa_text, TAXA_HEADER, source), start=2
    ):
        if not _INT.match(tid) or (parent and not _INT.match(parent)) or not rank or not name or not name_class:
            raise NcbiTaxonomyError(f"NCBI taxonomy {source}: malformed row {lineno}: {tid!r} {name!r}")
        taxid = int(tid)
        node_info = (int(parent) if parent else None, rank)
        if info.setdefault(taxid, node_info) != node_info:
            raise NcbiTaxonomyError(f"NCBI taxonomy {source}: taxid {taxid} has conflicting parent/rank (row {lineno})")
        names.setdefault(taxid, []).append((name, name_class))
    if not info:
        raise NcbiTaxonomyError(f"NCBI taxonomy {source} holds no taxa")

    nodes: dict[int, Node] = {}
    by_name: dict[str, set[int]] = {}
    for taxid, (parent, rank) in info.items():
        if parent is None and taxid not in DOMAIN_TAXIDS:
            raise NcbiTaxonomyError(f"NCBI taxonomy {source}: taxid {taxid} has no parent")
        if parent is not None and parent not in info:
            raise NcbiTaxonomyError(f"NCBI taxonomy {source}: parent {parent} of taxid {taxid} is not in the snapshot")
        scientific = [n for n, cls in names[taxid] if cls == SCIENTIFIC_NAME]
        if len(scientific) != 1:
            raise NcbiTaxonomyError(f"NCBI taxonomy {source}: taxid {taxid} needs exactly one scientific name")
        ordered = tuple(sorted(names[taxid], key=lambda nc: (nc[1] != SCIENTIFIC_NAME, nc[1], nc[0])))
        nodes[taxid] = Node(taxid, parent, rank, scientific[0], ordered)
        for name, _ in ordered:
            by_name.setdefault(name.casefold(), set()).add(taxid)

    merged: dict[int, int] = {}
    for lineno, (old, new) in enumerate(_parse_tsv(merged_text, MERGED_HEADER, source + " merged"), start=2):
        if not (_INT.match(old) and _INT.match(new)) or int(new) not in nodes:
            raise NcbiTaxonomyError(f"NCBI taxonomy {source} merged: malformed row {lineno}: {old!r} -> {new!r}")
        merged[int(old)] = int(new)

    homonyms: dict[str, frozenset[int]] = {}
    for lineno, (name, prok, nonprok) in enumerate(
        _parse_tsv(homonym_text, HOMONYM_HEADER, source + " homonyms"), start=2
    ):
        if not name:
            raise NcbiTaxonomyError(f"NCBI taxonomy {source} homonyms: malformed row {lineno}")
        prok_ids = _ids(prok, source + " homonyms", lineno)
        if any(t not in nodes for t in prok_ids):
            raise NcbiTaxonomyError(f"NCBI taxonomy {source} homonyms: row {lineno} names a taxid not in the snapshot")
        homonyms[name.casefold()] = frozenset(_ids(nonprok, source + " homonyms", lineno))

    version = next((ln.strip() for ln in (version_text or "").splitlines() if ln.strip()), None)
    if version is None:
        logger.warning(
            "NCBI taxonomy snapshot %s has no .version sidecar (or it is empty): taxon rows will carry "
            "no snapshot version. Rebuild it with scripts/build_ncbi_taxon_snapshot.py.",
            source,
        )
    return Snapshot(
        nodes=nodes,
        by_name={k: tuple(sorted(v)) for k, v in by_name.items()},
        merged=merged,
        homonyms=homonyms,
        homonym_nonprokaryote=frozenset(t for ids in homonyms.values() for t in ids),
        version=version,
        source=source,
    )


def _companions(name: str) -> tuple[str, str, str]:
    match = _TAXA_NAME.match(name)
    if not match:
        raise NcbiTaxonomyError(f"NCBI taxonomy snapshot file name {name!r} is not prokaryote_taxa_<date>.tsv")
    date = match.group("date")
    return f"merged_{date}.tsv", f"homonyms_{date}.tsv", f"{name}.version"


def _read(folder: Path | Traversable, name: str, source: str) -> Snapshot:
    merged_name, homonym_name, version_name = _companions(name)
    taxa = folder.joinpath(name)
    if not taxa.is_file():
        raise NcbiTaxonomyError(f"NCBI taxonomy snapshot not found at {source}")
    texts = []
    for companion in (merged_name, homonym_name):
        path = folder.joinpath(companion)
        if not path.is_file():
            raise NcbiTaxonomyError(f"NCBI taxonomy snapshot {source}: companion file {companion} is missing")
        texts.append(path.read_text(encoding="utf-8"))
    sidecar = folder.joinpath(version_name)
    version_text = sidecar.read_text(encoding="utf-8") if sidecar.is_file() else None
    return _parse(taxa.read_text(encoding="utf-8"), texts[0], texts[1], version_text, source)


def load(path: Path | str) -> Snapshot:
    """Parse a snapshot (and its companions) without touching the cache."""
    path = Path(path)
    return _read(path.parent, path.name, str(path))


_CACHE: dict[str, Snapshot] = {}


def _source() -> tuple[str, Path | Traversable, str]:
    if config.NCBI_TAXONOMY_SNAPSHOT_PATH:
        path = Path(config.NCBI_TAXONOMY_SNAPSHOT_PATH)
        return str(path), path.parent, path.name
    folder = resources.files("biomapper2").joinpath(*PACKAGED_DIR)
    return "<packaged:" + "/".join((*PACKAGED_DIR, PACKAGED_SNAPSHOT)) + ">", folder, PACKAGED_SNAPSHOT


def load_or_raise() -> Snapshot:
    """The configured (or packaged) snapshot, cached per source. Raises when missing or malformed."""
    key, folder, name = _source()
    if key not in _CACHE:
        _CACHE[key] = _read(folder, name, key)
    return _CACHE[key]


def is_present() -> bool:
    try:
        load_or_raise()
    except NcbiTaxonomyError:
        return False
    return True


def version() -> str | None:
    return load_or_raise().version if is_present() else None


def reset() -> None:
    """Drop the load cache (tests repointing ``NCBI_TAXONOMY_SNAPSHOT_PATH``)."""
    _CACHE.clear()


# ------------------------------------------------------------------------------- module-level helpers


def lookup(name: str, rank: str | None = None) -> list[int]:
    """Taxids carrying ``name`` (any kept name class, case-insensitive), optionally at ``rank``."""
    return load_or_raise().lookup(name, rank)


def current_taxid(taxid: int) -> int | None:
    """The snapshot's current id for ``taxid`` (itself, or its merge target), else None."""
    return load_or_raise().current_taxid(taxid)


def is_prokaryote(taxid: int) -> bool:
    """True when ``taxid`` (or its merge target) is a Bacteria/Archaea node from domain to genus, or an
    ancestor on such a path (clade/no-rank nodes included). Species and strains are not in the snapshot."""
    return current_taxid(taxid) is not None


def names_of(taxid: int) -> tuple[str, ...]:
    snap = load_or_raise()
    current = snap.current_taxid(taxid)
    return tuple(name for name, _ in snap.nodes[current].names) if current is not None else ()


def rank_of(taxid: int) -> str | None:
    snap = load_or_raise()
    current = snap.current_taxid(taxid)
    return snap.nodes[current].rank if current is not None else None


def scientific_name(taxid: int) -> str | None:
    snap = load_or_raise()
    current = snap.current_taxid(taxid)
    return snap.nodes[current].scientific_name if current is not None else None


def homonym_nonprokaryote_taxids(name: str) -> frozenset[int]:
    """The non-prokaryote taxids that share ``name`` with a prokaryote taxon (empty if not a homonym)."""
    return load_or_raise().homonyms.get(name.strip().casefold(), frozenset())


def is_homonym_nonprokaryote_side(taxid: int) -> bool:
    """True when ``taxid`` is the non-prokaryote side of any prokaryote homonym pair (e.g. 55087, 210425)."""
    return taxid in load_or_raise().homonym_nonprokaryote
