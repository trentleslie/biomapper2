"""NECS gold-disagreement classifier and repair (Units 4-5).

The MOESM5 NECS annotation ships two vintages whose InChIKey columns disagree. This module
classifies each disagreement by KIND — using the file's own SMILES/formula, never a key-to-key
comparison — and (Unit 5) rebuilds the gold column as a per-row consequence of that classification.

KIND is the load-bearing split, and it is fully offline:
  * kind_a_bad_key   — one key contradicts its OWN SMILES; that key is the defect, the SMILES is
                       correct. Resolved offline toward the self-consistent vintage.
  * kind_b_structure — both keys are self-consistent but the two SMILES differ in connectivity;
                       the vintages drew genuinely different structures. Needs the external
                       name/CID anchor (Unit 5, gated). RDKit canonicalization is NOT authoritative
                       here (misses ring-chain sugars, over-merges regioisomers), so only a
                       non-binding ``rdkit_hint`` is attached.
  * stereo_conflict  — same connectivity, both vintages specify stereo and disagree. Needs anchor.
  * completeness     — same connectivity, one vintage specifies stereo and the other does not.
                       Resolved offline toward the stereo-complete vintage.
  * corrupt          — a legacy ``4000`` placeholder cell. Modern wins, offline.
  * undecidable      — a SMILES is absent/unparseable, or neither key is self-consistent.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from . import structure_compare as sc

COMPARISON_RULE = "block1+block2[:8]"
_STEREO_MARKER = re.compile(r"[@/\\]")


def _b1(key: str) -> str:
    return key.split("-")[0].upper() if key else ""


def _adj(key: str) -> str:
    """block1 + '-' + first 8 of block2 — the adjudication key the benchmark scores at."""
    parts = (key or "").split("-")
    return parts[0].upper() + "-" + (parts[1][:8].upper() if len(parts) > 1 else "")


def _has_stereo(smiles: str | None) -> bool:
    return bool(_STEREO_MARKER.search(smiles or ""))


def _rdkit_hint(legacy_smiles: str, modern_smiles: str) -> str:
    """Non-authoritative preliminary class for a kind_b row. NEVER the final verdict."""
    if sc.same_canonical(legacy_smiles, modern_smiles) is True:
        return "tautomer_or_charge?"
    if sc.same_formula(legacy_smiles, modern_smiles) is False:
        return "wrong_molecule_formula_differs?"
    return "wrong_molecule_formula_identical?"


def _result(kind: str, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "kind": kind,
        "klass": kw.get("klass", kind),
        "arbiter": kw.get("arbiter"),
        "offline_resolved": kw.get("offline_resolved", False),
        "rdkit_hint": kw.get("rdkit_hint"),
        "comparison_rule": COMPARISON_RULE,
        "reason": kw.get("reason", ""),
    }
    return base


def classify_row(
    legacy_key: str | None,
    legacy_smiles: str | None,
    modern_key: str | None,
    modern_smiles: str | None,
    formula: str | None = "",
) -> dict[str, Any]:
    """Classify one key-vs-key disagreement by KIND from the row's own structures."""
    lk = (legacy_key or "").strip()
    mk = (modern_key or "").strip()

    # Corrupt placeholder cells: the other vintage wins outright.
    if lk == "4000" and mk and mk != "4000":
        return _result("corrupt", arbiter="modern", offline_resolved=True,
                       klass="corrupt_legacy_cell", reason="legacy cell is the 4000 placeholder")
    if mk == "4000" and lk and lk != "4000":
        return _result("corrupt", arbiter="legacy", offline_resolved=True,
                       klass="corrupt_modern_cell", reason="modern cell is the 4000 placeholder")
    if not lk or not mk:
        return _result("undecidable", reason="a vintage key is absent")

    if _adj(lk) == _adj(mk):
        return _result("agree", offline_resolved=True, reason=f"keys agree at {COMPARISON_RULE}")

    l_conn = sc.connectivity(legacy_smiles)
    m_conn = sc.connectivity(modern_smiles)
    if l_conn is None or m_conn is None:
        return _result("undecidable", reason="a vintage SMILES is absent/unparseable")

    legacy_selfconsistent = l_conn == _b1(lk)
    modern_selfconsistent = m_conn == _b1(mk)

    # KIND A — a key contradicts its own SMILES. That key is the defect; the SMILES is the arbiter.
    if legacy_selfconsistent and not modern_selfconsistent:
        return _result("kind_a_bad_key", arbiter="legacy", offline_resolved=True,
                       klass="modern_key_wrong", reason="modern key contradicts its own SMILES")
    if modern_selfconsistent and not legacy_selfconsistent:
        return _result("kind_a_bad_key", arbiter="modern", offline_resolved=True,
                       klass="legacy_key_wrong", reason="legacy key contradicts its own SMILES")
    if not legacy_selfconsistent and not modern_selfconsistent:
        return _result("undecidable", reason="neither key matches its own SMILES")

    # Both self-consistent -> the vintages drew genuinely different structures.
    if _b1(lk) == _b1(mk):
        # Connectivity agrees; the disagreement is stereo-only.
        l_stereo, m_stereo = _has_stereo(legacy_smiles), _has_stereo(modern_smiles)
        if l_stereo and m_stereo:
            return _result("stereo_conflict", klass="genuine_stereo",
                           reason="both vintages specify stereo and disagree — needs anchor")
        if l_stereo and not m_stereo:
            return _result("completeness", arbiter="legacy", offline_resolved=True,
                           klass="modern_stereo_unspecified")
        if m_stereo and not l_stereo:
            return _result("completeness", arbiter="modern", offline_resolved=True,
                           klass="legacy_stereo_unspecified")
        return _result("stereo_odd",
                       reason="stereo keys differ but neither SMILES carries stereo markers")

    # Connectivity differs -> KIND B. RDKit is not authoritative; attach a hint, route to anchor.
    return _result("kind_b_structure", rdkit_hint=_rdkit_hint(legacy_smiles, modern_smiles),
                   reason="two self-consistent vintages with different connectivity — needs anchor")


def classify_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify many rows; return per-row results plus a per-kind tally (the positive control)."""
    results = [classify_row(**r) for r in rows]
    counts = Counter(r["kind"] for r in results)
    return {"rows": results, "kind_counts": dict(counts)}
