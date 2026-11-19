"""Deterministic parser for 16S classifier taxonomy labels.

A pure function, no I/O. It turns one label into the levels it names, the name and rank the resolver
should query, and a label class that tells the annotator how far to trust that name.

Supported formats (one per public 16S reference in the baseline panel):

* Greengenes 13_8 / RDP / QIIME  ``k__Bacteria;p__Firmicutes;...;g__Dorea``
* HMP                            ``Root;p__...;g__Alistipes``
* SILVA (QIIME export)           ``D_0__Bacteria;...;D_5__Bifidobacterium`` (depth, a rank *hint*)
* MGnify v4.1                    ``sk__Bacteria;k__;p__...;g__Alistipes`` (``sk__`` is the domain)
* Greengenes2 / GTDB             ``d__Bacteria;p__Firmicutes_A;...;g__Faecalibacterium_A_123``
* bare names                     ``Bacteroides``, ``Homo sapiens`` (not 16S format, rank unknown)

Grammar rules:

* ``Root;`` is optional and ignored.
* ``sk__`` is the domain. ``k__`` is the domain when the label has no ``sk__``, and the kingdom when it
  does (MGnify writes the current NCBI kingdom there, e.g. ``k__Bacillati``).
* ``d__`` is the domain, unless its value is a ``denovo...`` OTU code, which ends parsing.
* SILVA ``D_n__`` gives a depth, used only as a rank hint (``rank_is_hint``); the caller confirms it.
* Parsing stops at ``s__``, ``t__``, ``D_6__`` and deeper, and ``d__denovo...``: no species resolution.
* A depth-hinted or unranked level that repeats its parent's name (SILVA padding, ``D_4__X;D_5__X``)
  is dropped. An explicitly ranked repeat (``p__Actinobacteria;c__Actinobacteria``) is kept.
* In an unprefixed lineage (``Bacteria;...;Escherichia;Escherichia coli``) a binomial slot is the species
  level: it is truncated to its genus (a rank hint) and parsing stops.
* Placeholders (uncultured, unidentified, unclassified, unknown, metagenome, ambiguous_taxa, incertae
  sedis, empty) are never the query name.

Label class precedence (first match wins): eukaryote, organelle, bracketed, incertae_sedis, merged,
superset, latin, informal. ``empty`` means no usable level.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Every class the parser can emit. Module-level so a typo in a consumer fails a test, not silently.
LABEL_CLASSES = frozenset(
    {
        "eukaryote",
        "organelle",
        "bracketed",
        "incertae_sedis",
        "merged",
        "superset",
        "latin",
        "informal",
        "empty",
    }
)

RANKS = ("domain", "kingdom", "phylum", "class", "order", "family", "genus")

_LETTER_PREFIX = {"p": "phylum", "c": "class", "o": "order", "f": "family", "g": "genus"}
_SILVA_DEPTH = {0: "domain", 1: "phylum", 2: "class", 3: "order", 4: "family", 5: "genus"}

_PREFIXED = re.compile(r"^(sk|[kdpcofgst])__(.*)$", re.S)
_SILVA = re.compile(r"^D_(\d+)__(.*)$", re.S)
_PLACEHOLDER = re.compile(
    r"^(uncultured|unidentified|unclassified|unknown|ambiguous[_ ]taxa|incertae[_ ]sedis|unassigned)\b"
    r"|metagenome$|^other$|^none$",
    re.I,
)
_EUKARYOTE = re.compile(
    r"^(Eukaryota|Eukarya|Metazoa|Fungi|Viridiplantae|Chloroplastida|Opisthokonta|SAR|Archaeplastida|"
    r"Amoebozoa|Excavata|Animalia|Plantae)$",
    re.I,
)
_ORGANELLE = re.compile(r"^(chloroplast|chloroplasts|mitochondria|mitochondrion)$", re.I)
_INCERTAE = re.compile(r"incertae[_ ]sedis", re.I)
_MERGED = re.compile(r"^[A-Z][a-z]+(?:\s*[-/]\s*[A-Z][a-z]+)+$")
# A Latin genus-like token: capital then at least three lowercase letters (Candidatus handled by caller).
_LATIN_TOKEN = re.compile(r"[A-Z][a-z]{3,}")
_LATIN = re.compile(r"^(Candidatus )?[A-Z][a-z]+$")
_GLUED_CANDIDATUS = re.compile(r"^Candidatus([A-Z][a-z]+)$")
# A SILVA genus slot that holds a binomial ("D_5__Enterobacter cancerogenus"): truncate to the genus.
_GENUS_BINOMIAL = re.compile(r"^((?:Candidatus )?[A-Z][a-z]+) [a-z]+$")
_BARE_LATIN = re.compile(r"^(Candidatus )?[A-Z][a-z]+( [a-z]+)?$")
# Superset suffixes over a Latin base genus. Order matters: the longest suffix forms first.
_SUPERSET = (
    re.compile(r"^(?P<base>(?:Candidatus )?[A-Z][a-z]+)[_ ]sensu[_ ]stricto(?:[_ ]\d+)?$", re.I),
    re.compile(r"^(?P<base>(?:Candidatus )?[A-Z][a-z]+)_[A-Z]{1,2}(?:_\d+)?$"),  # GTDB / GG2: Name_A, Name_A_123
    re.compile(r"^(?P<base>(?:Candidatus )?[A-Z][a-z]+)[_ ]\d+$"),  # SILVA: Prevotella_9, Ruminococcus 1
    re.compile(r"^(?P<base>(?:Candidatus )?[A-Z][a-z]+)_[IVXLivxl]+[a-z]?$"),  # RDP clusters: Clostridium_XlVb
)


@dataclass(frozen=True)
class TaxonLevel:
    """One named, non-placeholder level of a label."""

    rank: str | None
    name: str
    rank_is_hint: bool = False


@dataclass(frozen=True)
class TaxonParse:
    """The deterministic parse of one label."""

    label: str
    is_16s_format: bool
    levels: tuple[TaxonLevel, ...]
    query_name: str | None
    query_rank: str | None
    rank_is_hint: bool
    label_class: str
    has_latin_token: bool


def _normalize_name(value: str) -> str:
    name = " ".join(value.strip().split())
    if name.lower().startswith("candidatus_"):
        name = "Candidatus " + name[len("candidatus_") :]
    glued = _GLUED_CANDIDATUS.match(name)
    if glued:  # RDP writes "CandidatusSolibacter"
        name = "Candidatus " + glued.group(1)
    return name


def _is_placeholder(name: str) -> bool:
    return not name or bool(_PLACEHOLDER.search(name.replace("_", " ").strip()))


def _superset_base(name: str) -> str | None:
    for pattern in _SUPERSET:
        match = pattern.match(name)
        if match:
            return match.group("base")
    return None


def _classify(levels: tuple[TaxonLevel, ...], query: str | None) -> str:
    if any(_EUKARYOTE.match(lv.name) for lv in levels):
        return "eukaryote"
    if any(_ORGANELLE.match(lv.name) for lv in levels):
        return "organelle"
    if query is None:
        return "empty"
    if "[" in query:
        return "bracketed"
    if _INCERTAE.search(query):
        return "incertae_sedis"
    if _MERGED.match(query):
        return "merged"
    if _superset_base(query) is not None:
        return "superset"
    if _LATIN.match(query):
        return "latin"
    return "informal"


def _split_levels(label: str) -> tuple[bool, list[TaxonLevel]]:
    """Return (is_16s_format, raw levels in order, placeholders included as empty names)."""
    parts = [p.strip() for p in label.split(";")]
    has_sk = any(p.startswith("sk__") for p in parts)
    is_16s = ";" in label or any(_PREFIXED.match(p) or _SILVA.match(p) for p in parts)
    levels: list[TaxonLevel] = []
    for part in parts:
        if part in ("", "Root"):
            continue
        prefixed = _PREFIXED.match(part)
        silva = _SILVA.match(part)
        if prefixed:
            tag, value = prefixed.group(1), prefixed.group(2)
            if tag in ("s", "t"):
                break
            if tag == "d" and value.strip().lower().startswith("denovo"):
                break
            if tag == "sk" or tag == "d":
                rank = "domain"
            elif tag == "k":
                rank = "kingdom" if has_sk else "domain"
            else:
                rank = _LETTER_PREFIX[tag]
            levels.append(TaxonLevel(rank, _normalize_name(value)))
        elif silva:
            depth = int(silva.group(1))
            if depth >= 6:
                break
            levels.append(TaxonLevel(_SILVA_DEPTH[depth], _normalize_name(silva.group(2)), rank_is_hint=True))
        else:
            name = _normalize_name(part)
            # A placeholder ("Ambiguous taxa", "Incertae sedis", "Unknown family") is not a binomial: left
            # whole so the placeholder filter drops it and parsing continues to any deeper real level.
            binomial = None if _is_placeholder(name) else _GENUS_BINOMIAL.match(name)
            if binomial:
                # An unranked lineage slot holding a binomial ("...;Escherichia;Escherichia coli") is the
                # species level: keep its genus (a hint the caller confirms) and stop, as at ``s__``.
                levels.append(TaxonLevel("genus", binomial.group(1), rank_is_hint=True))
                break
            levels.append(TaxonLevel(None, name))
    return is_16s, levels


def parse_taxon_label(label: str | None) -> TaxonParse:
    """Parse one 16S classifier label (or bare name) into levels, query name/rank and label class."""
    text = "" if label is None else str(label)
    if not text.strip():
        return TaxonParse(text, False, (), None, None, False, "empty", False)

    is_16s, raw_levels = _split_levels(text)

    if not is_16s:
        name = _normalize_name(text)
        if _is_placeholder(name):
            return TaxonParse(text, False, (), None, None, False, "empty", False)
        level = TaxonLevel(None, name)
        cls = _classify((), name)
        if cls == "informal" and _BARE_LATIN.match(name):
            cls = "latin"
        return TaxonParse(text, False, (level,), name, None, False, cls, bool(_LATIN_TOKEN.search(name)))

    named: list[TaxonLevel] = []
    for level in raw_levels:
        if _is_placeholder(level.name):
            continue
        if named and named[-1].name.casefold() == level.name.casefold():
            if level.rank is None or level.rank_is_hint:
                # Padded repeat (SILVA depth padding, or a plain lineage's species slot truncated to the
                # genus it repeats): drop the child, but let a ranked child name an unranked parent.
                if named[-1].rank is None and level.rank is not None:
                    named[-1] = level
                continue
            # An explicitly ranked child (``p__Actinobacteria;c__Actinobacteria``) is a real level: keep it.
        named.append(level)
    levels = tuple(named)

    if not levels:
        return TaxonParse(text, True, (), None, None, False, "empty", False)

    deepest = levels[-1]
    binomial = _GENUS_BINOMIAL.match(deepest.name) if deepest.rank == "genus" else None
    if binomial:
        deepest = TaxonLevel(deepest.rank, binomial.group(1), deepest.rank_is_hint)
        levels = levels[:-1] + (deepest,)
    cls = _classify(levels, deepest.name)
    query = deepest.name
    if cls == "superset":
        query = _superset_base(deepest.name) or deepest.name
    elif cls in ("incertae_sedis", "informal"):
        query = deepest.name.replace("_", " ")
    return TaxonParse(
        label=text,
        is_16s_format=True,
        levels=levels,
        query_name=query,
        query_rank=deepest.rank,
        rank_is_hint=deepest.rank_is_hint,
        label_class=cls,
        has_latin_token=bool(_LATIN_TOKEN.search(deepest.name)),
    )
