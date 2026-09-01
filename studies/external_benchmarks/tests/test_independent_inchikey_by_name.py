"""Unit E prerequisite — the by-name independent resolver (unblocks name-only panels like Xu).

The PubChem name index is KG-independent (a different service than the linking KG node). Fetch is
faked — no live call. Connectivity-only (block 1) return matches the id lookups; an ambiguous/absent
name yields None so the link is later REFUSED, never certified off a guess.
"""

from __future__ import annotations

from studies.external_benchmarks.scorers.independent_inchikey import PubChemInChIKeyResolver


class _Resp:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


class _Session:
    def __init__(self, resp):
        self._resp = resp
        self.calls = 0

    def get(self, url, timeout=None):
        self.calls += 1
        return self._resp


def test_block_for_name_returns_connectivity_block():
    r = PubChemInChIKeyResolver(session=_Session(_Resp(200, "WHUUTDBJXJRKMK-VKHMYHEASA-N\n")))
    assert r.block_for_name("glutamate") == "WHUUTDBJXJRKMK"  # block 1 only


def test_block_for_name_none_on_unknown():
    r = PubChemInChIKeyResolver(session=_Session(_Resp(404, "")))
    assert r.block_for_name("not-a-real-metabolite") is None


def test_block_for_name_is_cached():
    sess = _Session(_Resp(200, "WHUUTDBJXJRKMK-VKHMYHEASA-N\n"))
    r = PubChemInChIKeyResolver(session=sess)
    r.block_for_name("glutamate")
    r.block_for_name("glutamate")
    assert sess.calls == 1  # repeated name costs one fetch
