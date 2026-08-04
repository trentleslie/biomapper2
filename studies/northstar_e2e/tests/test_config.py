from studies.northstar_e2e.config import SUHRE, NorthStarConfig


def test_suhre_is_config():
    assert isinstance(SUHRE, NorthStarConfig)


def test_suhre_fields():
    assert SUHRE.key == "suhre-t2d"
    assert SUHRE.entity_type == "metabolite"
    assert SUHRE.name_column == "metabolite_name"
    assert SUHRE.pathway_vocab == "KEGG"
    assert SUHRE.source_doi == "10.1371/journal.pone.0013953"
    assert "dysregulated" in SUHRE.question.lower()
    assert isinstance(SUHRE.mess_seed, int)
