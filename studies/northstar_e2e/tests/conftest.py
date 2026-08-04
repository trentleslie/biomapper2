"""Shared offline fixtures for the northstar_e2e slice.

Everything here is network-isolated: no live Kestrel / KEGG / Anthropic calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def anon():
    """Placeholder fixture so pytest collects this package before real fixtures land."""
    return object()


class FakeKestrel:
    """Offline KestrelEquivalents: chosen_kg_id -> KEGG compound(s), from a fixture map."""

    def __init__(self, mapping: dict[str, list[str]]):
        self._mapping = mapping

    def kegg_compounds_for(self, kg_node_ids):
        return {nid: self._mapping.get(nid, []) for nid in kg_node_ids}


@pytest.fixture
def fake_kestrel():
    return FakeKestrel(
        {
            "CHEBI:4167": ["C00031"],  # glucose -> glycolysis
            "CHEBI:16414": ["C00183"],  # valine -> BCAA degradation
        }
    )


def _fake_llm_fn(prompt: str) -> dict:
    """Deterministic offline interpreter: echoes candidate pathways it sees + T2D."""
    ranked = []
    for token in prompt.split():
        t = token.strip(",.()[]")
        if t.startswith("map") and t[3:].isdigit() and t not in ranked:
            ranked.append(t)
    return {"ranked_pathways": ranked, "disease_label": "type 2 diabetes"}


@pytest.fixture
def fake_llm_fn():
    return _fake_llm_fn


class FakeMapper:
    """Offline mapper: resolves a surface name to a ChEBI via a fixture table.

    Mirrors the mapper.map_dataset_to_kg contract used by annotate(): writes a
    *_MAPPED.tsv and returns (path, stats). A row it can't resolve gets empty
    chosen_kg_id.
    """

    def __init__(self, name_to_chebi: dict[str, str]):
        self._table = name_to_chebi

    def map_dataset_to_kg(
        self,
        *,
        dataset,
        entity_type,
        name_column,
        provided_id_columns,
        vocab,
        annotation_mode,
        output_dir,
        output_prefix,
        **kwargs,
    ):
        df = dataset.copy()
        df["chosen_kg_id"] = df[name_column].map(lambda n: self._table.get(str(n).strip(), ""))
        out = Path(output_dir) / f"{output_prefix}_MAPPED.tsv"
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out, sep="\t", index=False)
        stats = {"mapped_to_kg_assigned": int((df["chosen_kg_id"] != "").sum())}
        return str(out), stats


@pytest.fixture
def fake_mapper():
    # Clean canonical names AND their messy synonyms resolve, so arm0 (clean names, the
    # ceiling) fully resolves while arm1 (messy) exercises the synonym path.
    return FakeMapper(
        {
            "dextrose": "CHEBI:4167",
            "D-glucose": "CHEBI:4167",
            "valine": "CHEBI:16414",
            "L-valine": "CHEBI:16414",
        }
    )
