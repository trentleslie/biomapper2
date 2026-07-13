"""Held-out query set loading, content-SHA pinning, and the WS-A gold adapter.

The v1 held-out set (``held_out_query_set_v1.jsonl``) lets Tier-3 start immediately.
When WS-A's shared hard-case gold set lands, ``load_ws_a_gold_set`` swaps it in
without touching the rest of the harness (same ``Query`` type downstream).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from studies.tier3_determinism.models import Query

HELD_OUT_QUERY_SET: Path = Path(__file__).parent / "data" / "held_out_query_set_v1.jsonl"

# WS-A gold records are only usable as Tier-3 queries if they were actually
# adjudicated (non-null gold) and marked for a consumer that shares our accuracy bar.
_ELIGIBLE_CONSUMERS = {"tier1", "ablation"}


def content_sha256(path: Path) -> str:
    """SHA-256 of the file's raw bytes -- pins the exact dataset used for a run."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _iter_jsonl(path: Path) -> list[dict]:
    text = Path(path).read_text()
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def load_query_set(path: Path) -> list[Query]:
    """Load a Tier-3 held-out query set (one JSON object per line)."""
    return [Query.model_validate(rec) for rec in _iter_jsonl(path)]


def load_ws_a_gold_set(path: Path) -> list[Query]:
    """Adapt WS-A's ``gold_set.jsonl`` into Tier-3 queries.

    Keeps only rows that were adjudicated to a gold CURIE and tagged for a
    consumer with an accuracy bar (``tier1``/``ablation``). The expert-unadjudicated
    residual (``gold_curie is None``) and tbench-only rows are dropped.
    """
    queries: list[Query] = []
    for rec in _iter_jsonl(path):
        gold = rec.get("gold_curie")
        eligible = set(rec.get("eligible_for") or [])
        if not gold or not (eligible & _ELIGIBLE_CONSUMERS):
            continue
        namespace = gold.split(":", 1)[0]
        name = rec["query_name"]
        queries.append(
            Query(
                query_id=f"wsa-{hashlib.sha1(name.encode()).hexdigest()[:10]}",
                query_name=name,
                entity_type="metabolite",  # WS-A is the metabolite gold set
                target_namespace=namespace,
                gold_curie=gold,
                source="ws_a_gold",
            )
        )
    return queries
