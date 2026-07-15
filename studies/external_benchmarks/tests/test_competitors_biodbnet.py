"""bioDBnet db2db client: row parsing, multi-value split, no-mapping sentinel, unsupported target."""

from __future__ import annotations

from studies.external_benchmarks.competitors.base import HttpResponse, InMemoryCache
from studies.external_benchmarks.competitors.biodbnet import BioDBnetClient
from studies.external_benchmarks.tests.competitor_fakes import ScriptedTransport, no_sleep


def _client(handler):
    return BioDBnetClient(ScriptedTransport(handler), cache=InMemoryCache(), sleep=no_sleep)


def test_source_and_target_codes():
    c = _client(lambda *a, **k: HttpResponse(status_code=200, json_body=[]))
    assert c.source_code("SYMBOL") == "Gene Symbol"
    assert c.target_code("ENSEMBL") == "Ensembl Gene ID"
    assert c.target_code("UniProtKB") == "UniProt Accession"


def test_parse_single_and_multivalue_rows():
    def handler(method, url, **kwargs):
        # db2db returns the requested output column keyed by its display name. Multi-valued fields
        # are ``//``-delimited (bioDBnet's real list separator, verified live) — NOT ``"; "``.
        rows = [
            {"InputValue": "BRCA1", "Ensembl Gene ID": "ENSG00000012048"},
            {"InputValue": "BRCA2", "Ensembl Gene ID": "ENSG00000139618//ENSG00000000001"},
            {"InputValue": "NOPE", "Ensembl Gene ID": "-"},  # bioDBnet no-mapping sentinel
        ]
        return HttpResponse(status_code=200, json_body=rows)

    c = _client(handler)
    preds = c.map_ids(["BRCA1", "BRCA2", "NOPE"], "SYMBOL", ("ENSEMBL",))
    assert preds["BRCA1"] == {"ENSEMBL:ENSG00000012048"}
    assert preds["BRCA2"] == {"ENSEMBL:ENSG00000139618", "ENSEMBL:ENSG00000000001"}
    assert preds["NOPE"] == set()


def test_multivalue_uniprot_accessions_split_on_double_slash():
    """Regression: symbol -> UniProt Accession returns a ``//``-joined list; the canonical accession
    IS in it. Splitting on the wrong delimiter collapsed the list into one bogus id and scored a
    real mapping as ~0% (the artifact this fix corrects)."""

    def handler(method, url, **kwargs):
        # Real shape: TP53 -> many UniProt accessions incl. the canonical P04637.
        rows = [{"InputValue": "TP53", "UniProt Accession": "Q8J016//Q9UQ61//P04637//L0EQ92"}]
        return HttpResponse(status_code=200, json_body=rows)

    c = _client(handler)
    preds = c.map_ids(["TP53"], "SYMBOL", ("UniProtKB",))
    # The canonical accession is recovered (among the others), so the gold P04637 matches.
    assert "UniProtKB:P04637" in preds["TP53"]
    assert preds["TP53"] == {
        "UniProtKB:Q8J016",
        "UniProtKB:Q9UQ61",
        "UniProtKB:P04637",
        "UniProtKB:L0EQ92",
    }


def test_version_suffix_aligned_for_refseq():
    def handler(method, url, **kwargs):
        rows = [{"InputValue": "P38398", "RefSeq Protein Accession": "NP_009225.1"}]
        return HttpResponse(status_code=200, json_body=rows)

    c = _client(handler)
    preds = c.map_ids(["P38398"], "UniProtKB", ("RefSeq",))
    assert preds["P38398"] == {"RefSeq:NP_009225"}  # version stripped to match unversioned gold


def test_taxon_and_dbs_present_in_request():
    seen: dict = {}

    def handler(method, url, **kwargs):
        seen.update(kwargs.get("params", {}))
        return HttpResponse(status_code=200, json_body=[])

    c = _client(handler)
    c.map_ids(["BRCA1"], "SYMBOL", ("ENSEMBL",))
    assert seen["taxonId"] == "9606"
    assert seen["input"] == "Gene Symbol"
    assert seen["outputs"] == "Ensembl Gene ID"
