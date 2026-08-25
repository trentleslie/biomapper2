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

import pandas as pd

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


def _rdkit_hint(legacy_smiles: str | None, modern_smiles: str | None) -> str:
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
        return _result(
            "corrupt",
            arbiter="modern",
            offline_resolved=True,
            klass="corrupt_legacy_cell",
            reason="legacy cell is the 4000 placeholder",
        )
    if mk == "4000" and lk and lk != "4000":
        return _result(
            "corrupt",
            arbiter="legacy",
            offline_resolved=True,
            klass="corrupt_modern_cell",
            reason="modern cell is the 4000 placeholder",
        )
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
        return _result(
            "kind_a_bad_key",
            arbiter="legacy",
            offline_resolved=True,
            klass="modern_key_wrong",
            reason="modern key contradicts its own SMILES",
        )
    if modern_selfconsistent and not legacy_selfconsistent:
        return _result(
            "kind_a_bad_key",
            arbiter="modern",
            offline_resolved=True,
            klass="legacy_key_wrong",
            reason="legacy key contradicts its own SMILES",
        )
    if not legacy_selfconsistent and not modern_selfconsistent:
        return _result("undecidable", reason="neither key matches its own SMILES")

    # Both self-consistent -> the vintages drew genuinely different structures.
    if _b1(lk) == _b1(mk):
        # Connectivity agrees; the disagreement is stereo-only.
        l_stereo, m_stereo = _has_stereo(legacy_smiles), _has_stereo(modern_smiles)
        if l_stereo and m_stereo:
            return _result(
                "stereo_conflict",
                klass="genuine_stereo",
                reason="both vintages specify stereo and disagree — needs anchor",
            )
        if l_stereo and not m_stereo:
            return _result("completeness", arbiter="legacy", offline_resolved=True, klass="modern_stereo_unspecified")
        if m_stereo and not l_stereo:
            return _result("completeness", arbiter="modern", offline_resolved=True, klass="legacy_stereo_unspecified")
        return _result("stereo_odd", reason="stereo keys differ but neither SMILES carries stereo markers")

    # Connectivity differs -> KIND B. RDKit is not authoritative; attach a hint, route to anchor.
    return _result(
        "kind_b_structure",
        rdkit_hint=_rdkit_hint(legacy_smiles, modern_smiles),
        reason="two self-consistent vintages with different connectivity — needs anchor",
    )


def classify_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify many rows; return per-row results plus a per-kind tally (the positive control)."""
    results = [classify_row(**r) for r in rows]
    counts = Counter(r["kind"] for r in results)
    return {"rows": results, "kind_counts": dict(counts)}


# --- Unit 5: repaired gold column + per-row provenance (total function over all rows) ----------

_ARBITER_KEY = {"legacy": "gold_inchikey", "modern": "gold_inchikey_standard"}
_NEEDS_ANCHOR = frozenset({"kind_b_structure", "stereo_conflict", "stereo_odd"})


def _repair_one(row: dict) -> dict[str, Any]:
    """Decide the repaired gold key + provenance for ONE row. Total: every row gets a state."""
    lk = str(row.get("gold_inchikey", "") or "").strip()
    mk = str(row.get("gold_inchikey_standard", "") or "").strip()
    ls = row.get("gold_smiles", "")
    ms = row.get("gold_smiles_standard", "")
    formula = row.get("gold_formula", "")

    if not lk and not mk:
        return {
            "repaired_inchikey": "",
            "repair_state": "no_gold",
            "repair_kind": "",
            "repair_arbiter": "",
            "repair_rule": "no gold InChIKey in either vintage",
        }
    if lk and not mk:
        return {
            "repaired_inchikey": lk,
            "repair_state": "legacy_only",
            "repair_kind": "",
            "repair_arbiter": "legacy",
            "repair_rule": "only the legacy vintage carries a key",
        }
    if mk and not lk:
        return {
            "repaired_inchikey": mk,
            "repair_state": "modern_only",
            "repair_kind": "",
            "repair_arbiter": "modern",
            "repair_rule": "only the modern vintage carries a key",
        }

    res = classify_row(lk, ls, mk, ms, formula)
    kind = res["kind"]
    if kind == "agree":
        return {
            "repaired_inchikey": mk,
            "repair_state": "agreed",
            "repair_kind": kind,
            "repair_arbiter": "modern",
            "repair_rule": f"keys agree at {COMPARISON_RULE}; standard form kept",
        }
    if res["offline_resolved"] and res["arbiter"] in _ARBITER_KEY:
        chosen = lk if res["arbiter"] == "legacy" else mk
        return {
            "repaired_inchikey": chosen,
            "repair_state": "resolved_offline",
            "repair_kind": kind,
            "repair_arbiter": res["arbiter"],
            "repair_rule": res["reason"] or kind,
        }
    if kind in _NEEDS_ANCHOR:
        return {
            "repaired_inchikey": "",
            "repair_state": "pending_anchor",
            "repair_kind": kind,
            "repair_arbiter": "",
            "repair_rule": f"{kind}: awaiting external name/CID anchor",
        }
    return {
        "repaired_inchikey": "",
        "repair_state": "undecidable",
        "repair_kind": kind,
        "repair_arbiter": "",
        "repair_rule": res["reason"] or "undecidable",
    }


def build_repaired_gold(input_df: pd.DataFrame) -> pd.DataFrame:
    """Return input_df with the repaired gold column + per-row provenance, for EVERY row."""
    prov = pd.DataFrame([_repair_one(r) for r in input_df.to_dict("records")], index=input_df.index)
    return pd.concat([input_df, prov], axis=1)


def pending_anchor_names(repaired_df: pd.DataFrame) -> list[str]:
    """Names still awaiting the external anchor pass — the input to the (gated) name/CID fetch."""
    mask = repaired_df["repair_state"] == "pending_anchor"
    return repaired_df.loc[mask, "chemical_name"].astype(str).tolist()


def apply_anchor_resolutions(repaired_df: pd.DataFrame, anchor_map: dict[str, str]) -> pd.DataFrame:
    """Apply external name/CID -> InChIKey resolutions to pending_anchor rows.

    A name absent from ``anchor_map`` (the anchor could not resolve it) STAYS pending — never
    silently defaulted to a vintage. ``anchor_map`` is produced by the gated live pass; this
    transform is offline and testable with a stand-in map.
    """
    out = repaired_df.copy()
    for idx, row in out.iterrows():
        if row["repair_state"] != "pending_anchor":
            continue
        key = anchor_map.get(str(row["chemical_name"]))
        if key:
            out.at[idx, "repaired_inchikey"] = key  # type: ignore[index]
            out.at[idx, "repair_state"] = "resolved_anchor"  # type: ignore[index]
            out.at[idx, "repair_rule"] = "external name/CID anchor selected this structure"  # type: ignore[index]
    return out


# --- External name/CID anchor for pending rows (Unit 5, R2a) -----------------------------------
# The DECISION logic (anchor_choice) and the map application (apply_anchor_resolutions) are pure
# and offline-tested. Only fetch_anchor_resolutions touches the network, and it is a SUPERVISED
# OPERATOR STEP — never call it inside an automated pipeline tail.


def anchor_choice(resolved_key: str | None, legacy_key: str, modern_key: str) -> str | None:
    """Given an INDEPENDENTLY resolved key (from name/CID, not from either vintage's SMILES),
    return which vintage it corroborates at the adjudication key: 'legacy' | 'modern' | None.

    None means the anchor matches NEITHER vintage — a real finding (both vintages may be wrong),
    never silently forced onto one.
    """
    if not resolved_key:
        return None
    a = _adj(resolved_key)
    if a == _adj(legacy_key):
        return "legacy"
    if a == _adj(modern_key):
        return "modern"
    return None


def fetch_anchor_resolutions(pending_df: pd.DataFrame, resolver) -> dict[str, str]:
    """Build the name -> chosen-vintage-key map for pending_anchor rows via an INDEPENDENT anchor.

    ``resolver`` is a callable ``(name: str, cid: str) -> str | None`` returning a full InChIKey
    resolved from the compound identity (name or PubChem CID), NOT from either vintage's SMILES.
    Inject the live PubChem resolver in production (SUPERVISED) or a stand-in in tests.

    A name whose anchor matches neither vintage, or does not resolve, is OMITTED from the map so
    apply_anchor_resolutions leaves it pending — never a silent default.
    """
    out: dict[str, str] = {}
    for _, row in pending_df.iterrows():
        if row.get("repair_state") != "pending_anchor":
            continue
        name = str(row["chemical_name"])
        cid = str(row.get("gold_pubchem", "") or "")
        resolved = resolver(name, cid)
        choice = anchor_choice(resolved, str(row.get("gold_inchikey", "")), str(row.get("gold_inchikey_standard", "")))
        if choice == "legacy":
            out[name] = str(row["gold_inchikey"])
        elif choice == "modern":
            out[name] = str(row["gold_inchikey_standard"])
    return out
