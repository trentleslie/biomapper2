import pandas as pd

from studies.northstar_e2e.adapters import suhre
from studies.northstar_e2e.config import SUHRE


def test_load_from_disk_builds_input_df():
    bundle = suhre.load_suhre()
    df = bundle.input_df
    assert SUHRE.name_column in df.columns
    for col in ("gold_chebi", "gold_hmdb", "gold_kegg", "direction", "qvalue"):
        assert col in df.columns
    assert 12 <= len(df) <= 18


def test_card_pins_sha_and_doi():
    bundle = suhre.load_suhre()
    card = bundle.card
    assert card["dataset"] == "suhre-t2d"
    assert len(card["source_sha256"]) == 64
    assert card["source_doi"] == SUHRE.source_doi
    assert card["n_rows"] == len(bundle.input_df)


def test_input_df_from_dataframe_source_is_deterministic():
    raw = pd.DataFrame(
        {
            "name": ["D-glucose"],
            "hmdb": ["HMDB0000122"],
            "chebi": ["CHEBI:4167"],
            "kegg_compound": ["C00031"],
            "direction": ["up"],
            "qvalue": ["0.0001"],
        }
    )
    b1 = suhre.load_suhre(raw)
    b2 = suhre.load_suhre(raw)
    assert b1.card["source_sha256"] == b2.card["source_sha256"]
    assert b1.input_df.iloc[0]["metabolite_name"] == "D-glucose"
