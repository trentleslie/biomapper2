from studies.annotation_reranking.dataset import (
    load_eval_cases, independent_cases, dataset_sha256,
    TRUE_BIOMAPPER_ERRORS, REFMET_ERRORS,
)

CSV = "/home/trentleslie/Documents/Trent's Vault/Active 🎯/Work/Projects/biomapper2 - refmet ChEBI analysis/chebi_disagreements_cat.csv"

def test_loads_all_172_rows():
    cases = load_eval_cases(CSV)
    assert len(cases) == 172

def test_error_case_counts():
    assert len(TRUE_BIOMAPPER_ERRORS) == 11
    assert len(REFMET_ERRORS) == 2

def test_independent_label_partition():
    cases = load_eval_cases(CSV)
    indep = independent_cases(cases)
    # 11 biomapper-error + 2 refmet-error == 13 independently-labeled cases
    assert len(indep) == 13
    bm = [c for c in indep if c.label_source == "independent_biomapper_error"]
    rm = [c for c in indep if c.label_source == "independent_refmet_error"]
    assert len(bm) == 11 and len(rm) == 2
    # every independent case has a concrete correct CURIE
    assert all(c.correct_id and c.correct_id.startswith("CHEBI:") for c in indep)

def test_biomapper_error_correct_id_is_refmet_node():
    # the n=2 insight: on the 11 BM-errors, correct == RefMet's node,
    # so rm_anchor (picks RM-bearing == RefMet node) is right by construction.
    cases = {c.name: c for c in load_eval_cases(CSV)}
    for name in TRUE_BIOMAPPER_ERRORS:
        c = cases[name]
        assert c.correct_id == f"CHEBI:{c.refmet_id}"

def test_dataset_hash_is_stable_hex():
    h = dataset_sha256(CSV)
    assert len(h) == 64 and all(ch in "0123456789abcdef" for ch in h)
