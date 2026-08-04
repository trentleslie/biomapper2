from biomapper2.core.annotators.lipidmaps_rest import LipidMapsRestEnricher


class _FakeResp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _FakeSession:
    def __init__(self, resp):
        self._resp = resp
        self.calls = 0

    def get(self, url, timeout=None):
        self.calls += 1
        return self._resp


def test_enrich_extracts_lm_id_and_inchikey():
    session = _FakeSession(_FakeResp(200, {"lm_id": "LMGP01010001", "inchi_key": "KILNVBDSWZSGLL-KXQOOQHDSA-N"}))
    enr = LipidMapsRestEnricher(session=session)
    out = enr.enrich("PC 16:0/16:0")
    assert out["LIPIDMAPS"] == "LMGP01010001"
    assert out["INCHIKEY"] == "KILNVBDSWZSGLL-KXQOOQHDSA-N"


def test_enrich_is_fail_soft_on_http_error():
    enr = LipidMapsRestEnricher(session=_FakeSession(_FakeResp(500)))
    assert enr.enrich("PC 16:0/16:0") == {}


def test_enrich_is_fail_soft_on_unparseable_body():
    enr = LipidMapsRestEnricher(session=_FakeSession(_FakeResp(200, None)))
    assert enr.enrich("PC 16:0/16:0") == {}


def test_enrich_blank_name_makes_no_call():
    session = _FakeSession(_FakeResp(200, {}))
    enr = LipidMapsRestEnricher(session=session)
    assert enr.enrich("") == {}
    assert session.calls == 0
