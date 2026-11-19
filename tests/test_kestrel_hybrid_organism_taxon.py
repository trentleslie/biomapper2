"""NCBITaxon preference for OrganismTaxon, on a live-recorded hybrid-search response (16S plan U2)."""

import json
from pathlib import Path

from biomapper2.config import CATEGORY_PREFERRED_NAMESPACES
from biomapper2.core.annotators.kestrel_hybrid import KestrelHybridSearchAnnotator

_FIXTURE = Path(__file__).parent / "fixtures" / "kestrel_hybrid_search_organism_taxon.json"


def _rows(term: str) -> list[dict]:
    return json.loads(_FIXTURE.read_text())["response"][term]


def test_fixture_was_recorded_live_with_ncbitaxon_rows():
    fixture = json.loads(_FIXTURE.read_text())
    assert fixture["request"]["category"] == "biolink:OrganismTaxon"
    # The live prefix spelling the config must match (a wrong string is a silent no-op).
    assert any(r["id"].startswith("NCBITaxon:") for r in _rows("Prevotellaceae"))


def test_select_canonical_prefers_ncbitaxon_over_higher_scoring_umls():
    rows = _rows("Prevotellaceae")
    assert rows[0]["id"] == "UMLS:C1080666"  # the conflated node outranks the NCBI one
    chosen, is_canonical = KestrelHybridSearchAnnotator._select_canonical(
        rows, CATEGORY_PREFERRED_NAMESPACES["biolink:OrganismTaxon"], "Prevotellaceae"
    )
    assert is_canonical
    assert chosen is not None and chosen["id"] == "NCBITaxon:171552"
