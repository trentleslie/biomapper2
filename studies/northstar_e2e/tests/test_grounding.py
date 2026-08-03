import pandas as pd

from studies.northstar_e2e import grounding


def test_ground_pathways_traces_provenance(fake_kestrel):
    mapped = pd.DataFrame({"chosen_kg_id": ["CHEBI:4167", "CHEBI:16414"]})
    membership = {"C00031": ("map00010", "map00500"), "C00183": ("map00280",)}
    g = grounding.ground_pathways(mapped, "chosen_kg_id", fake_kestrel, membership)
    assert set(g.candidate_pathways) == {"map00010", "map00500", "map00280"}
    # Every candidate traces to a resolved entity, not to a disease title-match.
    assert g.provenance["map00280"] == ["CHEBI:16414"]
    assert "CHEBI:4167" in g.provenance["map00010"]


def test_ground_pathways_ignores_unresolved_rows(fake_kestrel):
    mapped = pd.DataFrame({"chosen_kg_id": ["CHEBI:4167", "", None, "CHEBI:99999"]})
    membership = {"C00031": ("map00010",)}
    g = grounding.ground_pathways(mapped, "chosen_kg_id", fake_kestrel, membership)
    assert g.candidate_pathways == ("map00010",)
