"""Shared gold-InChIKey structure predicate (Unit 7).

The recovered Unit-0 gate scripts each carried their OWN copy of a predicate that accepted only
the legacy TWO-block form (``len(parts) == 2 and len(parts[0]) == 14``). Run against a repaired
gold — whose resolved rows carry STANDARD three-block keys — that predicate silently rejects every
repaired key and computes the gate on almost no rows, returning a confident-but-empty verdict. This
single shared predicate replaces both copies and accepts either vintage's form.
"""

from __future__ import annotations

_CORRUPT = frozenset({"", "4000"})


def has_gold_structure(inchikey: str | None) -> bool:
    """True if the value is a usable gold InChIKey in EITHER vintage form.

    Accepts the legacy two-block (``AAAAAAAAAAAAAA-BBBBBBBBBB``) and the standard three-block
    (``AAAAAAAAAAAAAA-BBBBBBBBBB-C``) forms; rejects blank and the corrupt ``4000`` placeholder.
    """
    v = (inchikey or "").strip()
    if v in _CORRUPT:
        return False
    parts = v.split("-")
    return len(parts) in (2, 3) and len(parts[0]) == 14


def row_has_gold_structure(row: dict, gold_column: str = "gold_inchikey") -> bool:
    """Whether a row carries a usable gold key in the NAMED column.

    The repaired gold is stored in ``repaired_inchikey``, separate from the legacy
    ``gold_inchikey``. To run the Unit-0 sizing gate against the REPAIRED ruler, pass
    ``gold_column="repaired_inchikey"``; the default reads the legacy column, so a caller that
    forgets would silently evaluate the gate against the legacy gold — the exact wrong-column
    failure this whole repair exists to remove.
    """
    return has_gold_structure(row.get(gold_column, ""))
