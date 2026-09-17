"""Pinned local Tier B freeze loader: a frozen name to InChIKey corpus for independent structure
evidence.

Why this exists
---------------
Tier B resolves the QUERY NAME against an external registry (PubChem, Metabolomics Workbench) to
corroborate or refute the committed node. Making that live call per unique name across a whole run is
a real cost against rate-limited services, and it was the reason Tier B shipped opt-in. This loader
reads a FROZEN name to InChIKey corpus so the hot path is served from disk: a HIT resolves with no
network, and only a MISS falls back to the live path (behind a circuit breaker). That is what makes
Tier B SAFE to run on by default. It mirrors the RefMet freeze in core/annotators/refmet_snapshot.py.

Format (tab-separated, with a header)::

    name    inchikey    source

``name`` is the query string. ``inchikey`` is the frozen structure: a full InChIKey or a first block,
placed verbatim (upper-cased) into ``TierBResult.inchikey_block``; the live PubChem path emits a
first block, so a corpus built from it stores first blocks, and a full key is accepted too (it lets a
stereo-level agreement register, matching the lipid hop). An EMPTY ``inchikey`` positively records
"this name has no independent structure" (a frozen unresolvable, still no network). ``source`` is
optional and names the registry the row came from; empty defaults to ``pubchem`` (the hop that is
independent of every annotator the resolver source-weights toward, which keeps the independence claim
honest). The only required columns are ``name`` and ``inchikey``.

Lookup is by NORMALIZED name (strip + casefold), so the corpus is case- and surrounding-whitespace
insensitive. Loading is done ONCE per resolved path and cached (immutable); the cache is keyed on the
resolved path so a test that repoints the env picks up a new freeze, and ``reset()`` clears it. A
missing/unreadable path, or a corrupt header, reports NOT present (never raises): the freeze is
inactive and every name falls to the live path.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path

from .. import config

logger = logging.getLogger(__name__)

# The registry a row is attributed to when its ``source`` column is empty. PubChem is independent of
# every annotator the resolver source-weights toward, so it is the honest default for the independence
# calculation in certificate.issue.
_DEFAULT_SOURCE = "pubchem"


def _normalize(name: str) -> str:
    """The single lookup key: leading/trailing whitespace stripped, then case-folded."""
    return name.strip().casefold()


@dataclass(frozen=True)
class FrozenStructureHit:
    """One row of the freeze: the frozen independent structure for a single query name.

    ``inchikey`` is None for a row that positively records "no structure for this name"; a caller
    treats that as a deterministic unresolvable, NOT as a miss (a miss returns None from ``lookup``).
    """

    inchikey: str | None
    source: str
    version: str | None


@dataclass(frozen=True)
class _LoadedSnapshot:
    """A parsed, immutable freeze: the normalized lookup table plus the derived version."""

    version: str | None
    by_normalized: dict[str, FrozenStructureHit]

    def lookup(self, name: str) -> FrozenStructureHit | None:
        return self.by_normalized.get(_normalize(name))


# Cache keyed on the resolved path string. A load that FAILED is stored as None so a broken/unreadable
# freeze is not retried on every call yet still reports NOT present.
_CACHE: dict[str, _LoadedSnapshot | None] = {}


def reset() -> None:
    """Drop the load cache. Tests repointing the env call this; production never."""
    _CACHE.clear()


def _parse(path: Path) -> _LoadedSnapshot:
    """Read and index the freeze TSV. Raises on an unreadable file or a missing 'name'/'inchikey'
    header: a corrupt freeze must be rejected (reported NOT present), not trusted as an authoritative
    empty corpus that silently turns every name into a miss."""
    version = config.derive_tier_b_snapshot_version(path)
    by_normalized: dict[str, FrozenStructureHit] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None or "name" not in reader.fieldnames or "inchikey" not in reader.fieldnames:
            raise ValueError(f"Tier B freeze {path} is missing the required 'name'/'inchikey' header")
        for row in reader:
            name = (row.get("name") or "").strip()
            if not name:
                continue
            inchikey = (row.get("inchikey") or "").strip().upper() or None
            source = (row.get("source") or "").strip() or _DEFAULT_SOURCE
            hit = FrozenStructureHit(inchikey=inchikey, source=source, version=version)
            # First occurrence wins on a duplicate key; the freeze is expected to be unique per name.
            by_normalized.setdefault(_normalize(name), hit)
    return _LoadedSnapshot(version=version, by_normalized=by_normalized)


def _current() -> _LoadedSnapshot | None:
    """The loaded freeze for the currently configured path, or None when unset/unloadable."""
    path = config.get_tier_b_snapshot_path()
    if path is None:
        return None
    key = str(path)
    if key not in _CACHE:
        try:
            _CACHE[key] = _parse(path)
        except (OSError, ValueError) as exc:
            logger.warning("Tier B freeze at %s could not be loaded (%s); falling back to live lookups", path, exc)
            _CACHE[key] = None
    return _CACHE[key]


def is_present() -> bool:
    """True iff a freeze is configured AND loadable. The freeze-first rollout switch."""
    return _current() is not None


def version() -> str | None:
    """Version of the loaded freeze (sidecar or filename stem), or None when not present."""
    snapshot = _current()
    return snapshot.version if snapshot is not None else None


def lookup(name: str) -> FrozenStructureHit | None:
    """Frozen independent structure for ``name`` (normalized), or None on a miss.

    None means the name is NOT in the freeze (a miss, which falls back to live). A row that exists but
    carries an empty ``inchikey`` still returns a FrozenStructureHit (inchikey None): the freeze
    positively recorded that the name has no independent structure.
    """
    if not name:
        return None
    snapshot = _current()
    if snapshot is None:
        return None
    return snapshot.lookup(name)
