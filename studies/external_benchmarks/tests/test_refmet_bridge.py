"""The certificate-gated RefMet bridge adds only structure-certified links, never an un-verified one."""

from __future__ import annotations

from studies.external_benchmarks.scorers.refmet_bridge import certified_bridge_links

_A = "FHQVHHIBKUMWTI-OTMQOFQ-N"  # structure block A
_B = "AAAAAAAAAAAAAA-BBBBBBBB-N"  # structure block B (different connectivity)


def _run(a_cur, b_cur, a_rm, b_rm, a_blk, b_blk):
    return certified_bridge_links(a_cur, b_cur, a_rm, b_rm, a_blk, b_blk)


def test_certified_bridge_is_adopted():
    r = _run({"na": frozenset()}, {"nb": frozenset()}, {"na": "Glucose"}, {"nb": "Glucose"}, {"na": _A}, {"nb": _A})
    assert [(lk.a_name, lk.b_name) for lk in r.bridge_certified] == [("na", "nb")]
    assert r.combined_links == r.bridge_certified  # no curie links here


def test_refuted_bridge_is_rejected_not_added():
    r = _run({"na": frozenset()}, {"nb": frozenset()}, {"na": "X"}, {"nb": "X"}, {"na": _A}, {"nb": _B})
    assert r.bridge_certified == ()  # structures disagree -> NOT adopted
    assert r.bridge_refuted == (("na", "nb"),)


def test_refused_bridge_is_held():
    r = _run({"na": frozenset()}, {"nb": frozenset()}, {"na": "X"}, {"nb": "X"}, {"na": None}, {"nb": _A})
    assert r.bridge_certified == () and r.bridge_refused == (("na", "nb"),)


def test_already_curie_linked_is_not_re_added_as_bridge():
    # Shared CURIE already links them; the bridge must not double-count the same pair.
    r = _run({"na": frozenset({"CHEBI:1"})}, {"nb": frozenset({"CHEBI:1"})},
             {"na": "X"}, {"nb": "X"}, {"na": _A}, {"nb": _A})
    assert len(r.curie_links) == 1
    assert r.bridge_certified == ()  # not a bridge — already CURIE-linked


def test_no_refmet_no_bridge():
    r = _run({"na": frozenset()}, {"nb": frozenset()}, {"na": ""}, {"nb": ""}, {"na": _A}, {"nb": _A})
    assert r.bridge_certified == () and r.bridge_refuted == () and r.bridge_refused == ()


def test_combined_links_is_curie_plus_certified():
    r = _run({"na": frozenset({"CHEBI:9"}), "nc": frozenset()},
             {"nb": frozenset({"CHEBI:9"}), "nd": frozenset()},
             {"nc": "Y"}, {"nd": "Y"}, {"na": _A, "nc": _A}, {"nb": _A, "nd": _A})
    pairs = {(lk.a_name, lk.b_name) for lk in r.combined_links}
    assert pairs == {("na", "nb"), ("nc", "nd")}  # one CURIE link + one certified bridge
