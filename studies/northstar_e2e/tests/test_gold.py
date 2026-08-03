from studies.northstar_e2e import gold


def test_gold_metabolite_count_in_range():
    assert 12 <= len(gold.GOLD_METABOLITES) <= 18


def test_gold_pathways_count_in_range():
    assert 3 <= len(gold.GOLD_PATHWAYS) <= 5


def test_gold_ids_well_formed():
    for m in gold.GOLD_METABOLITES:
        assert m.name.strip()
        assert m.hmdb.startswith("HMDB")
        assert m.chebi.startswith("CHEBI:")
        assert m.kegg_compound.startswith("C") and m.kegg_compound[1:].isdigit()
        assert m.direction in {"up", "down"}


def test_gold_pathways_are_kegg_map_ids():
    for p in gold.GOLD_PATHWAYS:
        assert p.startswith("map") and p[3:].isdigit()
        assert p in gold.GOLD_PATHWAY_NAMES


def test_disease_label_normalized():
    assert gold.DISEASE_LABEL == "type 2 diabetes"


def test_assert_known_answer_passes():
    gold.assert_known_answer()  # raises on any structural violation
