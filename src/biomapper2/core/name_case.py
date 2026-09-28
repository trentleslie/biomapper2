"""Case-robust name lookup for the case-sensitive name parsers (RefMet ``/match`` and Goslin).

Two upstream parsers read a metabolite NAME case-sensitively, so the same analyte spelled with
different case could resolve to different KG nodes and never link across cohorts:

* RefMet ``/match`` accepts ``acetylcarnitine (C2)`` and ``1-linolenoyl-GPC (18:3)*`` but returns
  no match for ``acetylcarnitine (c2)`` and ``1-linolenoyl-gpc (18:3)*``.
* Goslin parses ``12,13-DiHOME`` and ``12-HETE`` but not ``12,13-dihome`` or ``12-hete``.

RefMet's fuzzy matcher can also return a DIFFERENT record for the lower-case spelling rather than none:
``1-(1-enyl-oleoyl)-gpe (p-18:1)*`` matches the ambiguous ``LPE P-18:1 or LPE O-18:2`` where the
Metabolon spelling ``...-GPE (P-18:1)*`` matches the plasmalogen ``LPE P-18:1``. A retry that fires only
on a miss cannot reach that case.

The fix is NOT to lowercase: the lowercase spelling is exactly the one those parsers reject or misread.
Instead, when a name carries one of the recognized notations below, the caller queries
:func:`canonical_query` FIRST, a spelling derived ONLY from the casefolded name, and falls back to the
name as given only if that misses. Any two spellings that differ only in case therefore issue the
identical first query and receive the same answer.

The variant touches three narrow, recognized notations and nothing else:

1. Metabolon chain notation in a parenthetical: ``(c2)`` -> ``(C2)``, ``(c5:1)`` -> ``(C5:1)``,
   ``(c4-oh)`` -> ``(C4-OH)``, ``(p-16:0)`` -> ``(P-16:0)``, ``(o-18:1)`` -> ``(O-18:1)``.
2. Glycerophospholipid head-group abbreviations as whole tokens: ``gpc`` / ``gpe`` / ``gpi`` / ``gps``
   / ``gpg`` / ``gpa`` -> upper case.
3. Position-prefixed oxylipin names in Goslin's casing: ``12,13-dihome`` -> ``12,13-DiHOME``,
   ``12-hete`` -> ``12-HETE``, ``14,15-eet`` -> ``14,15-EET``.

Everything else in the returned string is the casefolded name. A name with none of these notations is
queried exactly as given, so its lookup is unchanged.

Deliberately NOT case-restored here (case carries meaning, or the notation is outside this fix):
identifiers and CURIE local parts, SMILES (lower case marks aromatic atoms), InChI / InChIKey,
stereo and configuration descriptors (``D-``/``L-`` configuration vs ``d-``/``l-`` rotation, ``R``/``S``,
``E``/``Z``, ``sn-``), ether / plasmalogen ``O-``/``P-`` letters outside the chain parenthetical,
``N-``/``S-``/``O-`` locants, element symbols, gene and protein symbols, and lipid-class shorthand such
as ``pc 34:1`` (Goslin also rejects that, but restoring class case is a separate change).
"""

from __future__ import annotations

import re

# (c2) (c5:1) (c4-oh) (c3-dc) (c10:2) (c6-dc-m) ... : acyl chain length [+ unsaturation] [+ suffixes]
_ACYL_PAREN = re.compile(r"\(c(\d+(?::\d+)?(?:-[a-z]{1,3})*)\)")
# (p-16:0) (o-18:1): plasmalogen / ether chain inside a parenthetical
_ETHER_PAREN = re.compile(r"\(([op])-(\d+:\d+)\)")
# whole-token glycerophospholipid head groups: -gpc, -gpe, gpi ...
_GP_TOKEN = re.compile(r"(?<![a-z])gp([acegis])(?![a-z])")

# Goslin's casing for oxylipin trivial-name tokens (pygoslin FattyAcids grammar / lipid-list).
# Longest first so "dihome" is not consumed as "home".
_OXYLIPIN_CASE = {
    "dihotre": "DiHOTrE",
    "dihome": "DiHOME",
    "dihode": "DiHODE",
    "dihete": "DiHETE",
    "hpotre": "HpOTrE",
    "hpome": "HpOME",
    "hpode": "HpODE",
    "hpete": "HpETE",
    "hotre": "HOTrE",
    "hete": "HETE",
    "hode": "HODE",
    "home": "HOME",
    "hepe": "HEPE",
    "eet": "EET",
}
# Only when preceded by a position locant ("12-", "12,13-"), so ordinary words are never touched.
_OXYLIPIN = re.compile(
    r"(?<![a-z0-9])(\d+(?:,\d+)*-)(" + "|".join(sorted(_OXYLIPIN_CASE, key=len, reverse=True)) + r")(?![a-z])"
)


# Case-meaningful stereo / configuration markers, detected on the CASEFOLDED name. "D-" (configuration)
# and "d-" (dextrorotatory) are different claims, as are 12(S)- and 12(R)-HETE; once casefolded the
# original case cannot be recovered. A name carrying one is never retried, for either spelling, so no
# stereoisomer is ever fabricated by a case change.
_CASE_MEANINGFUL = re.compile(r"(?<![a-z0-9])[dl]-|\(\d*[rsez](?:,\s*\d*[rsez])*\)")


def case_key(name: str) -> str:
    """The case-insensitive identity of a name: casefolded, surrounding whitespace stripped."""
    return name.strip().casefold()


def canonical_case_variant(name: str) -> str:
    """The canonical-case spelling of ``name``, computed from its casefolded form only.

    Two names that differ only in case always return the identical string. Returns the casefolded
    name unchanged when none of the recognized notations is present.
    """
    k = case_key(name)
    k = _ACYL_PAREN.sub(lambda m: f"(C{m.group(1).upper()})", k)
    k = _ETHER_PAREN.sub(lambda m: f"({m.group(1).upper()}-{m.group(2)})", k)
    k = _GP_TOKEN.sub(lambda m: f"GP{m.group(1).upper()}", k)
    k = _OXYLIPIN.sub(lambda m: m.group(1) + _OXYLIPIN_CASE[m.group(2)], k)
    return k


def canonical_query(name: str) -> str | None:
    """The canonical-case spelling to query INSTEAD of ``name`` first, or None to query ``name`` as given.

    None when the name carries a case-meaningful stereo marker (D-/L-, (R)/(S), (E)/(Z)), when the
    variant equals the name as given (nothing to change), or when no recognized notation is present
    (the variant would only be a lower-cased copy, which is the spelling the case-sensitive parsers
    reject). Callers fall back to the name as given when the canonical query misses.
    """
    if _CASE_MEANINGFUL.search(case_key(name)):
        return None
    variant = canonical_case_variant(name)
    if variant == name or variant == case_key(name):
        return None
    return variant
