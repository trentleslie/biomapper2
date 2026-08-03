def test_pygoslin_is_importable_and_parses_shorthand():
    from pygoslin.parser.Parser import GoslinParser

    adduct = GoslinParser().parse("PC 34:1")
    assert adduct is not None
    assert adduct.get_lipid_string() is not None
