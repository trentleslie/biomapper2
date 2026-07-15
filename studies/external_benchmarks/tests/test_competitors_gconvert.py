"""g:Convert client: parsing, no-mapping sentinel, multi-value, fan-out, caching."""

from __future__ import annotations

from studies.external_benchmarks.competitors.base import HttpResponse, InMemoryCache
from studies.external_benchmarks.competitors.gconvert import GConvertClient
from studies.external_benchmarks.tests.competitor_fakes import ScriptedTransport, no_sleep

# converted-value fixtures keyed by g:Convert target code.
_BY_TARGET = {
    "ENSG": {"BRCA1": "ENSG00000012048", "TP53": "ENSG00000141510", "MISSINGGENE": "None"},
    "ENTREZGENE_ACC": {"BRCA1": "672", "TP53": "7157", "MISSINGGENE": "None"},
    "UNIPROTSWISSPROT": {"BRCA1": "P38398", "TP53": "P04637", "MISSINGGENE": "None"},
}


def _handler(method, url, **kwargs):
    body = kwargs["json"]
    target = body["target"]
    table = _BY_TARGET[target]
    result = [{"incoming": q, "converted": table.get(q, "None")} for q in body["query"]]
    return HttpResponse(status_code=200, json_body={"result": result})


def _client(handler=_handler, cache=None):
    return GConvertClient(ScriptedTransport(handler), cache=cache or InMemoryCache(), sleep=no_sleep)


def test_source_and_target_codes():
    c = _client()
    assert c.target_code("ENSEMBL") == "ENSG"
    assert c.target_code("NCBIGene") == "ENTREZGENE_ACC"
    assert c.target_code("NoSuchNs") is None
    assert c.source_code("SYMBOL") == "SYMBOL"
    assert c.source_code("BOGUS") is None


def test_parse_collects_curies_and_skips_none():
    c = _client()
    preds = c.map_ids(["BRCA1", "MISSINGGENE"], "SYMBOL", ("ENSEMBL",))
    assert preds["BRCA1"] == {"ENSEMBL:ENSG00000012048"}
    assert preds["MISSINGGENE"] == set()  # "None" is an honest miss, not an error


def test_fan_out_over_multiple_target_namespaces():
    c = _client()
    preds = c.map_ids(["BRCA1"], "SYMBOL", ("ENSEMBL", "NCBIGene", "UniProtKB"))
    assert preds["BRCA1"] == {
        "ENSEMBL:ENSG00000012048",
        "NCBIGene:672",
        "UniProtKB:P38398",
    }


def test_multiple_converted_rows_for_one_incoming():
    def handler(method, url, **kwargs):
        result = [
            {"incoming": "BRCA1", "converted": "ENSG00000012048"},
            {"incoming": "BRCA1", "converted": "ENSG00000000000"},  # a second hit
        ]
        return HttpResponse(status_code=200, json_body={"result": result})

    c = _client(handler)
    preds = c.map_ids(["BRCA1"], "SYMBOL", ("ENSEMBL",))
    assert preds["BRCA1"] == {"ENSEMBL:ENSG00000012048", "ENSEMBL:ENSG00000000000"}


def test_uniprot_swissprot_version_suffix_stripped():
    """Regression: g:Convert's UNIPROTSWISSPROT target returns VERSIONED accessions (``P04637.307``)
    while the gold is unversioned (``P04637``). Without stripping, every UniProtKB hit scored as a
    miss (~0%) despite being a correct mapping — the artifact this fix corrects."""

    def handler(method, url, **kwargs):
        body = kwargs["json"]
        assert body["target"] == "UNIPROTSWISSPROT"
        result = [
            {"incoming": "TP53", "converted": "P04637.307"},
            {"incoming": "BRCA1", "converted": "P38398.277"},
        ]
        return HttpResponse(status_code=200, json_body={"result": result})

    c = _client(handler)
    preds = c.map_ids(["TP53", "BRCA1"], "SYMBOL", ("UniProtKB",))
    assert preds["TP53"] == {"UniProtKB:P04637"}  # version suffix stripped to match unversioned gold
    assert preds["BRCA1"] == {"UniProtKB:P38398"}


def test_cache_avoids_second_http_call():
    transport = ScriptedTransport(_handler)
    cache = InMemoryCache()
    c = GConvertClient(transport, cache=cache, sleep=no_sleep)
    c.map_ids(["BRCA1"], "SYMBOL", ("ENSEMBL",))
    n_after_first = transport.n_calls
    c.map_ids(["BRCA1"], "SYMBOL", ("ENSEMBL",))  # identical batch -> served from cache
    assert transport.n_calls == n_after_first
