"""Gene/protein arm scorer — CURIE-equality Top-1 accuracy + coverage/precision/recall/F1.

There is no structure oracle for genes/proteins; correctness is CURIE equality between
BioMapper's *assigned* cross-reference CURIEs and the backbone's authoritative held-out
cross-refs. This mirrors the mapper's own ``analysis.py`` "assigned-vs-provided" semantics
(``_calculate_precision/_recall/_f1``), applied to the held-out gold instead of a provided id.

Per the Hajjar calibration (``chosen_kg_id`` is annotation-driven, not vocab-steered), ONE
accuracy number is reported per dataset — the CURIE match is taken across ALL of the backbone's
target namespaces at once (a per-namespace breakdown is retained for traceability only, never
plotted). BioMapper's predicted CURIEs are drawn from ``chosen_kg_id`` plus its
``kg_equivalent_ids`` (any namespace); the gold restricts the comparison to the target
namespaces, so the source-namespace query id can never trivially self-match.
"""

from __future__ import annotations

import ast
from typing import Any

import pandas as pd

from ..config import CurieDatasetConfig

CHOSEN_COL = "chosen_kg_id"
EQUIV_COL = "kg_equivalent_ids"
CURIE_DELIM = "|"


def normalize_curie(curie: Any) -> str | None:
    """Canonicalize a CURIE for equality: strip, uppercase the prefix, keep the local part.

    Gene/protein identifiers (Ensembl/UniProt/Entrez/RefSeq) are conventionally case-stable in
    the local part but the *prefix* casing varies across sources (``Ensembl`` vs ``ENSEMBL``),
    so only the prefix is uppercased. Returns None for blank/NaN.
    """
    if curie is None or (isinstance(curie, float) and pd.isna(curie)):
        return None
    s = str(curie).strip()
    if not s or s.lower() == "nan":
        return None
    if ":" in s:
        prefix, local = s.split(":", 1)
        return f"{prefix.strip().upper()}:{local.strip()}"
    return s.upper()


def split_gold_curies(value: Any) -> set[str]:
    """Split a ``|``-delimited gold CURIE cell into a normalized set.

    The single canonical gold-cell splitter reused across every arm (gene/protein CURIE
    equality, provided-ID reachability, and metabolite name-hit ID concordance) so a gold
    cell like ``"CHEBI:17234|CHEBI:4167"`` is parsed identically everywhere. ``_split_curies``
    is retained as a back-compat alias for existing imports.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return set()
    out: set[str] = set()
    for part in str(value).split(CURIE_DELIM):
        n = normalize_curie(part)
        if n is not None:
            out.add(n)
    return out


# Back-compat alias — the splitter was originally module-private; callers (provided_id_scorer,
# this module) may still import the underscore name.
_split_curies = split_gold_curies


def _parse_equiv(value: Any) -> dict[str, Any]:
    """Parse the ``kg_equivalent_ids`` cell (a dict, a dict-repr string from a TSV, or NaN)."""
    if isinstance(value, dict):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return {}
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return {}
    try:
        parsed = ast.literal_eval(s)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, SyntaxError):
        return {}


def predicted_curies(row: pd.Series) -> set[str]:
    """All CURIEs BioMapper assigned for a row: ``chosen_kg_id`` + every ``kg_equivalent_ids``.

    ``kg_equivalent_ids`` is ``{prefix: [local_id, ...]}`` with the prefix STRIPPED from each
    value (biomapper2 ``Linker.get_equivalent_ids``), so each cross-ref CURIE is reconstructed as
    ``prefix:local_id``. A value that already carries a prefix (defensive) is taken as-is. The gold
    set — restricted to the target namespaces — does the filtering at intersection time.
    """
    out: set[str] = set()
    chosen = normalize_curie(row.get(CHOSEN_COL))
    if chosen is not None:
        out.add(chosen)
    for namespace, ids in _parse_equiv(row.get(EQUIV_COL)).items():
        values = ids if isinstance(ids, (list, tuple, set)) else [ids]
        for v in values:
            raw = str(v).strip()
            if not raw:
                continue
            curie = raw if ":" in raw else f"{namespace}:{raw}"
            n = normalize_curie(curie)
            if n is not None:
                out.add(n)
    return out


def gold_curies(row: pd.Series, config: CurieDatasetConfig) -> set[str]:
    """Union of the held-out authoritative cross-ref CURIEs across the target namespaces."""
    out: set[str] = set()
    for _namespace, column in config.gold_curie_columns:
        out |= _split_curies(row.get(column))
    return out


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or (precision + recall) == 0:
        return 0.0 if (precision is not None and recall is not None) else None
    return 2 * precision * recall / (precision + recall)


def score_curie(mapped_df: pd.DataFrame, config: CurieDatasetConfig, vocab: str | None = None) -> dict[str, Any]:
    """CURIE-equality scoring. One headline accuracy per dataset + coverage/precision/recall/F1.

    - scored denominator = rows carrying ≥1 gold cross-ref (the accuracy/recall base).
    - correct = the row's predicted CURIE set intersects its gold CURIE set.
    - coverage = rows with ≥1 predicted CURIE / total.
    - precision = correct / (rows with BOTH a prediction and a gold) — assigned-vs-provided.
    - recall = correct / scored.
    """
    total = len(mapped_df)
    n_predicted = 0
    scored = 0
    both = 0  # rows with a prediction AND a gold (precision denominator)
    correct = 0
    per_namespace: dict[str, dict[str, int]] = {ns: {"correct": 0, "scored": 0} for ns, _ in config.gold_curie_columns}
    per_row: list[dict[str, Any]] = []

    for _, row in mapped_df.iterrows():
        preds = predicted_curies(row)
        golds = gold_curies(row, config)
        has_pred = bool(preds)
        has_gold = bool(golds)
        if has_pred:
            n_predicted += 1
        if has_gold:
            scored += 1
        row_correct = bool(preds & golds)
        if has_pred and has_gold:
            both += 1
            if row_correct:
                correct += 1
        # Per-namespace breakdown (traceability only; never the headline).
        for namespace, column in config.gold_curie_columns:
            ns_gold = _split_curies(row.get(column))
            if ns_gold:
                per_namespace[namespace]["scored"] += 1
                if preds & ns_gold:
                    per_namespace[namespace]["correct"] += 1
        per_row.append(
            {
                "query": row.get(config.name_column),
                "predicted": sorted(preds),
                "gold": sorted(golds),
                "scored": has_gold,
                "correct": has_gold and row_correct,
            }
        )

    top1 = (correct / scored) if scored else None
    precision = (correct / both) if both else None
    recall = (correct / scored) if scored else None
    return {
        "vocab": vocab,
        "arm": config.arm,
        "input_type": config.input_type,
        "comparable_core": {
            "metric": "top1_accuracy",
            "top1_accuracy": top1,
            "correct": correct,
            "scored_denominator": scored,
        },
        "coverage": {"n_predicted": n_predicted, "total": total, "fraction": (n_predicted / total) if total else 0.0},
        "curie_stats": {
            "precision": precision,
            "recall": recall,
            "f1": _f1(precision, recall),
            "predicted_and_gold": both,
        },
        "per_namespace": per_namespace,
        "per_row": per_row,
    }
