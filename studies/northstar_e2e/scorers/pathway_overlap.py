"""Structured ranked-pathway overlap scorer (primary, objective metric).

Scores the interpreter's ranked KEGG pathway list against the curated gold set:
precision/recall/F1, Hits@k, and rank-of-gold (the Geistlinger-style metric).
Disease label is matched on a normalized substring so "Type 2 Diabetes Mellitus"
counts as the T2D label. F1 is the scalar the validity gate consumes.
"""

from __future__ import annotations

from typing import Any

from ..gold import DISEASE_LABEL, GOLD_PATHWAYS


def _disease_match(predicted: str, gold: str) -> bool:
    p, g = predicted.strip().lower(), gold.strip().lower()
    return bool(p) and (g in p or p in g)


def score_pathways(
    interp,
    gold_pathways: tuple[str, ...] = GOLD_PATHWAYS,
    disease_label: str = DISEASE_LABEL,
    k_values: tuple[int, ...] = (1, 3, 5),
) -> dict[str, Any]:
    ranked = list(interp.ranked_pathways)
    gold = set(gold_pathways)
    predicted = set(ranked)

    tp = len(predicted & gold)
    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(gold) if gold else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    ranks = {gid: (ranked.index(gid) + 1 if gid in ranked else None) for gid in gold_pathways}
    found_ranks = [r for r in ranks.values() if r is not None]
    first_gold_rank = min(found_ranks) if found_ranks else None

    hits_at_k = {}
    for k in k_values:
        topk = set(ranked[:k])
        hits_at_k[k] = len(topk & gold) / len(gold) if gold else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "hits_at_k": hits_at_k,
        "rank_of_gold": ranks,
        "first_gold_rank": first_gold_rank,
        "disease_match": _disease_match(interp.disease_label, disease_label),
        "n_gold": len(gold),
        "n_predicted": len(predicted),
    }


def primary_metric(score: dict[str, Any]) -> float:
    return float(score["f1"])
