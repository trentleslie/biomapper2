"""UniProt ID Mapping client: run/poll/results flow, pagination, entry-object target, outages."""

from __future__ import annotations

import pytest

from studies.external_benchmarks.competitors.base import CompetitorOutageError, HttpResponse, InMemoryCache
from studies.external_benchmarks.competitors.uniprot_idmapping import UniProtIdMappingClient
from studies.external_benchmarks.tests.competitor_fakes import ScriptedTransport, no_sleep


class UniProtScript:
    """Stateful fake of the run/poll/results workflow.

    ``mappings`` maps a ``to`` db code to ``{from_id: to_value}``. Each ``run`` mints a job; the
    first status poll reports RUNNING, the next FINISHED; results return the pairs (one page).
    """

    def __init__(self, mappings: dict[str, dict[str, object]], *, running_polls: int = 1):
        self.mappings = mappings
        self.running_polls = running_polls
        self._jobs: dict[str, dict] = {}
        self._n = 0

    def __call__(self, method, url, **kwargs):
        if url.endswith("/run"):
            self._n += 1
            job = f"JOB{self._n}"
            data = kwargs["data"]
            ids = data["ids"].split(",")
            self._jobs[job] = {"to": data["to"], "ids": ids, "polls": 0}
            return HttpResponse(status_code=200, json_body={"jobId": job})
        if "/status/" in url:
            job = url.rsplit("/", 1)[-1]
            st = self._jobs[job]
            st["polls"] += 1
            status = "RUNNING" if st["polls"] <= self.running_polls else "FINISHED"
            return HttpResponse(status_code=200, json_body={"jobStatus": status})
        if "/results/" in url:
            job = url.rsplit("/", 1)[-1].split("?")[0]
            st = self._jobs[job]
            table = self.mappings.get(st["to"], {})
            results = [{"from": i, "to": table[i]} for i in st["ids"] if i in table]
            return HttpResponse(status_code=200, json_body={"results": results})
        raise AssertionError(f"unexpected url {url}")


def _client(handler, **kw):
    return UniProtIdMappingClient(
        ScriptedTransport(handler), cache=InMemoryCache(), sleep=no_sleep, poll_interval_s=0.0, **kw
    )


def test_from_to_codes():
    c = _client(UniProtScript({}))
    assert c.source_code("UniProtKB") == "UniProtKB_AC-ID"
    assert c.source_code("SYMBOL") == "Gene_Name"
    assert c.target_code("NotANamespace") is None  # unknown target => unsupported
    assert c.target_code("ENSEMBL") == "Ensembl"
    assert c.target_code("RefSeq") == "RefSeq_Protein"


def test_full_flow_parses_results_and_strips_version():
    script = UniProtScript({"Ensembl": {"P38398": "ENSG00000012048.5"}})
    c = _client(script)
    preds = c.map_ids(["P38398"], "UniProtKB", ("ENSEMBL",))
    assert preds["P38398"] == {"ENSEMBL:ENSG00000012048"}  # aligned to unversioned gold


def test_unmapped_id_is_a_miss():
    script = UniProtScript({"Ensembl": {"P38398": "ENSG00000012048"}})
    c = _client(script)
    preds = c.map_ids(["P38398", "P99999"], "UniProtKB", ("ENSEMBL",))
    assert preds["P99999"] == set()


def test_entry_object_target_extracts_primary_accession():
    script = UniProtScript({"UniProtKB": {"BRCA1": {"primaryAccession": "P38398"}}})
    c = _client(script)
    preds = c.map_ids(["BRCA1"], "SYMBOL", ("UniProtKB",))
    assert preds["BRCA1"] == {"UniProtKB:P38398"}


def test_pagination_follows_next_link():
    calls = {"n": 0}

    def handler(method, url, **kwargs):
        if url.endswith("/run"):
            return HttpResponse(status_code=200, json_body={"jobId": "J"})
        if "/status/" in url:
            return HttpResponse(status_code=200, json_body={"jobStatus": "FINISHED"})
        # results: page 1 links to page 2.
        calls["n"] += 1
        if calls["n"] == 1:
            return HttpResponse(
                status_code=200,
                json_body={"results": [{"from": "P1", "to": "ENSG1"}]},
                headers={"Link": '<https://rest.uniprot.org/idmapping/results/J?cursor=x>; rel="next"'},
            )
        return HttpResponse(status_code=200, json_body={"results": [{"from": "P2", "to": "ENSG2"}]})

    c = _client(handler)
    preds = c.map_ids(["P1", "P2"], "UniProtKB", ("ENSEMBL",))
    assert preds["P1"] == {"ENSEMBL:ENSG1"}
    assert preds["P2"] == {"ENSEMBL:ENSG2"}


def test_missing_job_id_is_outage():
    def handler(method, url, **kwargs):
        return HttpResponse(status_code=200, json_body={})  # no jobId

    with pytest.raises(CompetitorOutageError):
        _client(handler).map_ids(["P1"], "UniProtKB", ("ENSEMBL",))


def test_never_finishing_job_is_outage():
    def handler(method, url, **kwargs):
        if url.endswith("/run"):
            return HttpResponse(status_code=200, json_body={"jobId": "J"})
        return HttpResponse(status_code=200, json_body={"jobStatus": "RUNNING"})  # forever

    c = _client(handler, poll_attempts=3)
    with pytest.raises(CompetitorOutageError):
        c.map_ids(["P1"], "UniProtKB", ("ENSEMBL",))
