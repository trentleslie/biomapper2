import pandas as pd

from studies.northstar_e2e import arms, mess
from studies.northstar_e2e.config import SUHRE


def _small_clean_df():
    return pd.DataFrame(
        {
            "metabolite_name": ["D-glucose", "L-valine"],
            "gold_chebi": ["CHEBI:4167", "CHEBI:16414"],
            "gold_hmdb": ["HMDB0000122", "HMDB0000883"],
            "gold_kegg": ["C00031", "C00183"],
            "direction": ["up", "up"],
            "qvalue": ["0.001", "0.001"],
        }
    )


def _membership():
    return {"C00031": ("map00010",), "C00183": ("map00280",)}


def test_arm3_oracle_uses_gold_chebi_not_mapper(fake_mapper, fake_kestrel, fake_llm_fn, tmp_path):
    clean = _small_clean_df()
    m = mess.make_messy(clean, seed=1)
    # A broken mapper (empty table) must NOT affect the oracle arm.
    from studies.northstar_e2e.tests.conftest import FakeMapper

    broken = FakeMapper({})
    res = arms.run_arm(
        "arm3_oracle",
        clean_df=clean,
        messy_result=m,
        config=SUHRE,
        mapper=broken,
        kestrel=fake_kestrel,
        membership=_membership(),
        llm_fn=fake_llm_fn,
    )
    assert "map00280" in res.grounded.candidate_pathways  # via gold ChEBI -> Kestrel


def test_arm1_product_runs_messy_through_mapper(fake_mapper, fake_kestrel, fake_llm_fn):
    clean = _small_clean_df()
    m = mess.make_messy(clean, seed=1)
    res = arms.run_arm(
        "arm1_product",
        clean_df=clean,
        messy_result=m,
        config=SUHRE,
        mapper=fake_mapper,
        kestrel=fake_kestrel,
        membership=_membership(),
        llm_fn=fake_llm_fn,
    )
    assert res.arm == "arm1_product"
    assert "f1" in res.score
    assert res.interpretation.disease_label == "type 2 diabetes"


def test_arm0_clean_is_ceiling(fake_mapper, fake_kestrel, fake_llm_fn):
    clean = _small_clean_df()
    m = mess.make_messy(clean, seed=1)
    res = arms.run_arm(
        "arm0_clean",
        clean_df=clean,
        messy_result=m,
        config=SUHRE,
        mapper=fake_mapper,
        kestrel=fake_kestrel,
        membership=_membership(),
        llm_fn=fake_llm_fn,
    )
    # Clean names resolve; both candidate pathways present.
    assert set(res.grounded.candidate_pathways) == {"map00010", "map00280"}
