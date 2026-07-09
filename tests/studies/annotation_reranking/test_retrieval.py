from unittest.mock import patch
from studies.annotation_reranking import retrieval
from studies.annotation_reranking.models_data import Candidate

FAKE_SEARCH = {"1-methylhistidine": [
    {"id": "CHEBI:70958", "score": 4.9, "name": "1-methylhistidine", "synonyms": []},
    {"id": "CHEBI:27596", "score": 4.1, "name": "N(pros)-methyl-L-histidine", "synonyms": []},
]}
FAKE_EQUIV = {"CHEBI:70958": ["RM:0001", "HMDB:0000001"], "CHEBI:27596": ["HMDB:0000479"]}

def test_fetch_returns_enriched_candidates():
    with patch.object(retrieval, "_raw_hybrid_search", return_value=FAKE_SEARCH), \
         patch.object(retrieval, "_fetch_equivalent_ids", return_value=FAKE_EQUIV):
        cands = retrieval.fetch_candidates("1-methylhistidine", "metabolite", top_n=20)
    assert [c.id for c in cands] == ["CHEBI:70958", "CHEBI:27596"]
    assert isinstance(cands[0], Candidate)
    assert cands[0].equivalent_ids == ["RM:0001", "HMDB:0000001"]
    assert cands[0].has_refmet() and not cands[1].has_refmet()

def test_top_n_is_passed_through():
    captured = {}
    def spy(text, category, prefixes, limit):
        captured["limit"] = limit
        return {text: []}
    with patch.object(retrieval, "_raw_hybrid_search", side_effect=spy), \
         patch.object(retrieval, "_fetch_equivalent_ids", return_value={}):
        retrieval.fetch_candidates("x", "metabolite", top_n=15)
    assert captured["limit"] == 15


def test_fetch_equivalent_ids_flattening():
    """_fetch_equivalent_ids must flatten {curie: {prefix: [local_ids]}} to {curie: [CURIE, ...]}."""
    from unittest.mock import patch
    from biomapper2.core.linker import Linker

    nested = {"CHEBI:15365": {"RM": ["0001"], "HMDB": ["HMDB0001879"]}}
    with patch.object(Linker, "get_equivalent_ids", return_value=nested):
        result = retrieval._fetch_equivalent_ids(["CHEBI:15365"])

    assert set(result["CHEBI:15365"]) == {"RM:0001", "HMDB:HMDB0001879"}

    # A Candidate built from those equivalent_ids must have has_refmet() True.
    from studies.annotation_reranking.models_data import Candidate
    c = Candidate(id="CHEBI:15365", score=1.0, name="aspirin",
                  equivalent_ids=result["CHEBI:15365"])
    assert c.has_refmet() is True


import os, pytest

@pytest.mark.external
@pytest.mark.skipif(not os.getenv("KESTREL_API_KEY"), reason="needs KESTREL_API_KEY")
def test_live_fetch_one_case():
    cands = retrieval.fetch_candidates("1-methylhistidine", "metabolite", top_n=20)
    assert 1 <= len(cands) <= 20
    assert all(c.id.startswith("CHEBI:") for c in cands)
