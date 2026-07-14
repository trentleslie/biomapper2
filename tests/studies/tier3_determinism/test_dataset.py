"""Tests for the held-out query set loader, SHA pinning, and WS-A gold adapter."""

import json
from pathlib import Path

from studies.tier3_determinism import dataset
from studies.tier3_determinism.models import Query


def test_load_query_set_returns_typed_queries(tmp_path: Path) -> None:
    records = [
        {
            "query_id": "m1",
            "query_name": "glucose",
            "entity_type": "metabolite",
            "target_namespace": "CHEBI",
            "gold_curie": "CHEBI:17234",
        }
    ]
    p = tmp_path / "qs.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in records) + "\n")

    queries = dataset.load_query_set(p)

    assert len(queries) == 1
    assert isinstance(queries[0], Query)
    assert queries[0].gold_curie == "CHEBI:17234"


def test_content_sha256_is_stable_and_byte_sensitive(tmp_path: Path) -> None:
    a = tmp_path / "a.jsonl"
    a.write_text('{"x": 1}\n')
    first = dataset.content_sha256(a)
    assert first == dataset.content_sha256(a)  # stable
    a.write_text('{"x": 2}\n')
    assert dataset.content_sha256(a) != first  # byte-sensitive


def test_packaged_held_out_set_is_metabolite_led_with_gold() -> None:
    queries = dataset.load_query_set(dataset.HELD_OUT_QUERY_SET)

    assert len(queries) >= 8
    metabolites = [q for q in queries if q.entity_type == "metabolite"]
    assert len(metabolites) > len(queries) / 2  # metabolite-led
    assert all(q.gold_curie for q in queries)  # v1 set is fully adjudicated
    assert len({q.query_id for q in queries}) == len(queries)  # unique ids


def test_ws_a_adapter_keeps_only_adjudicated_eligible_records(tmp_path: Path) -> None:
    ws_a_records = [
        {  # kept: has gold + eligible
            "query_name": "cis-piceid",
            "gold_curie": "CHEBI:76155",
            "adjudication_method": "inchikey_auto",
            "eligible_for": ["tier1", "ablation"],
        },
        {  # dropped: no gold (expert-needed residual)
            "query_name": "ambiguous thing",
            "gold_curie": None,
            "adjudication_method": "expert",
            "eligible_for": [],
        },
        {  # dropped: gold present but not eligible for our consumers
            "query_name": "not eligible",
            "gold_curie": "CHEBI:1",
            "adjudication_method": "inchikey_auto",
            "eligible_for": ["tbench"],
        },
    ]
    p = tmp_path / "gold_set.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in ws_a_records) + "\n")

    queries = dataset.load_ws_a_gold_set(p)

    assert len(queries) == 1
    q = queries[0]
    assert q.query_name == "cis-piceid"
    assert q.gold_curie == "CHEBI:76155"
    assert q.entity_type == "metabolite"
    assert q.target_namespace == "CHEBI"  # derived from the gold CURIE prefix
