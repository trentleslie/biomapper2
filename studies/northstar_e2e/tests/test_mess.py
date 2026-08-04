from studies.northstar_e2e import mess
from studies.northstar_e2e.adapters import suhre
from studies.northstar_e2e.config import SUHRE


def _input_df():
    return suhre.load_suhre().input_df


def test_mess_is_reproducible_under_seed():
    df = _input_df()
    a = mess.make_messy(df, seed=1)
    b = mess.make_messy(df, seed=1)
    assert list(a.messy_df[SUHRE.name_column]) == list(b.messy_df[SUHRE.name_column])


def test_mess_preserves_measurements_and_gold():
    df = _input_df()
    r = mess.make_messy(df, seed=1)
    # Measurements and gold columns are NEVER perturbed.
    assert list(r.messy_df[SUHRE.direction_column]) == list(df[SUHRE.direction_column])
    assert list(r.messy_df[SUHRE.gold_kegg_column]) == list(df[SUHRE.gold_kegg_column])


def test_hidden_mapping_recovers_canonical_names():
    df = _input_df()
    r = mess.make_messy(df, seed=1)
    for surface in r.messy_df[SUHRE.name_column]:
        assert surface in r.hidden_mapping
        assert r.hidden_mapping[surface] in set(df[SUHRE.name_column])


def test_mess_actually_degrades_some_rows():
    df = _input_df()
    r = mess.make_messy(df, seed=1)
    changed = sum(1 for m, c in zip(r.messy_df[SUHRE.name_column], df[SUHRE.name_column]) if m != c)
    assert changed >= max(3, len(df) // 3)
