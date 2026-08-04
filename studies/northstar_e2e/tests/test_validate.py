import pandas as pd
import pytest

from studies.northstar_e2e import mess, validate
from studies.northstar_e2e.config import SUHRE


def _df():
    return pd.DataFrame(
        {
            "metabolite_name": ["D-glucose", "L-valine", "glycine"],
            "gold_chebi": ["CHEBI:4167", "CHEBI:16414", "CHEBI:15428"],
            "gold_hmdb": ["HMDB0000122", "HMDB0000883", "HMDB0000123"],
            "gold_kegg": ["C00031", "C00183", "C00037"],
            "direction": ["up", "up", "down"],
            "qvalue": ["0.001", "0.001", "0.005"],
        }
    )


def test_shuffle_permutes_directions_only():
    m = mess.make_messy(_df(), seed=1)
    s = validate.shuffle_measurements(m, SUHRE, seed=7)
    # Names and gold are untouched; the multiset of directions is preserved.
    assert list(s.messy_df[SUHRE.name_column]) == list(m.messy_df[SUHRE.name_column])
    assert sorted(s.messy_df[SUHRE.direction_column]) == sorted(m.messy_df[SUHRE.direction_column])


def test_shuffle_is_seeded():
    m = mess.make_messy(_df(), seed=1)
    a = validate.shuffle_measurements(m, SUHRE, seed=7)
    b = validate.shuffle_measurements(m, SUHRE, seed=7)
    assert list(a.messy_df[SUHRE.direction_column]) == list(b.messy_df[SUHRE.direction_column])


def test_validity_gate_passes_on_large_gap():
    r = validate.validity_gate(0.8, 0.2)
    assert r.gap == pytest.approx(0.6)
    assert r.passed is True


def test_validity_gate_fails_on_small_gap():
    r = validate.validity_gate(0.5, 0.45)
    assert r.passed is False
