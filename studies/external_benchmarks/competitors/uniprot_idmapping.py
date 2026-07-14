"""UniProt REST ID Mapping client (run / poll / results).

The asynchronous UniProt idmapping workflow:

  1. ``POST https://rest.uniprot.org/idmapping/run`` (form: ``from``, ``to``, ``ids``) -> ``{"jobId"}``.
  2. Poll ``GET .../idmapping/status/{jobId}`` until finished (``jobStatus == "FINISHED"`` or the
     body already carries ``results``/``failedIds``).
  3. ``GET .../idmapping/results/{jobId}`` -> ``{"results": [{"from", "to"}, ...]}``, paginated via
     the ``Link: <url>; rel="next"`` response header.

``from``/``to`` are UniProt db codes (``UniProtKB_AC-ID``, ``Gene_Name``, ``GeneID``, ``Ensembl``,
``RefSeq_Protein``). For cross-ref targets ``to`` is a bare string id; for a UniProtKB target it is
a full entry object, so ``primaryAccession`` is extracted defensively. A query absent from
``results`` (present in ``failedIds`` or simply unmapped) is an honest miss, not an error.

Protocol delta (recorded by the runner, not hidden): for the HGNC arm the source is a gene SYMBOL,
which UniProt maps via ``Gene_Name`` across ALL organisms — the taxon can't be constrained on the
run call, so symbol->UniProt via this tool is inherently noisier than its native accession-input
scope. This is exactly the kind of native-scope difference the head-to-head is meant to surface.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from .base import CompetitorClient, CompetitorOutageError, HttpResponse, HttpTransport, RateLimiter, ResponseCache
from .namespaces import UNIPROT_DB, UNIPROT_TARGET_CODES, to_curie

BASE_URL = "https://rest.uniprot.org/idmapping"
RESULT_PAGE_SIZE = 500
_DONE_STATES = {"FINISHED"}


class UniProtIdMappingClient(CompetitorClient):
    name = "uniprot_idmapping"
    batch_size = 500  # UniProt accepts large idmapping batches

    def __init__(
        self,
        transport: HttpTransport,
        *,
        rate_limiter: RateLimiter | None = None,
        cache: ResponseCache | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 4,
        poll_attempts: int = 30,
        poll_interval_s: float = 1.0,
        max_result_pages: int = 200,
    ) -> None:
        super().__init__(transport, rate_limiter=rate_limiter, cache=cache, sleep=sleep, max_attempts=max_attempts)
        self._poll_attempts = poll_attempts
        self._poll_interval_s = poll_interval_s
        self._max_result_pages = max_result_pages

    def source_code(self, source_ns: str) -> str | None:
        return UNIPROT_DB.get(source_ns)

    def target_code(self, target_ns: str) -> str | None:
        return UNIPROT_TARGET_CODES.get(target_ns)

    # --- workflow ------------------------------------------------------------------------------

    def map_batch(self, ids: list[str], source_ns: str, target_ns: str) -> dict[str, set[str]]:
        from_db = self.source_code(source_ns)
        to_db = self.target_code(target_ns)
        assert from_db is not None and to_db is not None  # supported by construction
        job_id = self._submit(from_db, to_db, ids)
        self._await_finished(job_id)
        return self._collect_results(job_id, ids, target_ns)

    def _submit(self, from_db: str, to_db: str, ids: list[str]) -> str:
        resp = self._request_with_retries(
            "POST",
            f"{BASE_URL}/run",
            data={"from": from_db, "to": to_db, "ids": ",".join(ids)},
        )
        if not resp.ok:
            raise CompetitorOutageError(
                f"{self.name}: idmapping/run returned HTTP {resp.status_code} for {from_db}->{to_db}."
            )
        job_id = (resp.json() or {}).get("jobId")
        if not job_id:
            raise CompetitorOutageError(f"{self.name}: idmapping/run returned no jobId ({resp.text[:200]!r}).")
        return str(job_id)

    def _await_finished(self, job_id: str) -> None:
        for attempt in range(self._poll_attempts):
            self.rate_limiter.acquire()
            resp = self._request_with_retries("GET", f"{BASE_URL}/status/{job_id}", allow_redirects=False)
            body = resp.json() or {}
            status = str(body.get("jobStatus") or body.get("job_status") or "").upper()
            if status in _DONE_STATES or "results" in body or "failedIds" in body:
                return
            if status and status not in {"NEW", "RUNNING", "QUEUED", ""}:
                raise CompetitorOutageError(f"{self.name}: idmapping job {job_id} reported status {status!r}.")
            if attempt < self._poll_attempts - 1:
                self._sleep(self._poll_interval_s)
        raise CompetitorOutageError(
            f"{self.name}: idmapping job {job_id} did not finish within {self._poll_attempts} polls."
        )

    def _collect_results(self, job_id: str, ids: list[str], target_ns: str) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {i: set() for i in ids}
        url: str | None = f"{BASE_URL}/results/{job_id}"
        params: dict[str, object] | None = {"format": "json", "size": RESULT_PAGE_SIZE}
        pages = 0
        while url and pages < self._max_result_pages:
            self.rate_limiter.acquire()
            resp = self._request_with_retries("GET", url, params=params)
            if not resp.ok:
                return out  # reachable error => misses this batch (outages already raised upstream)
            body = resp.json() or {}
            for pair in body.get("results", []) or []:
                self._absorb_pair(pair, target_ns, out)
            url = _next_link(resp)
            params = None  # the next-link URL already carries cursor + params
            pages += 1
        return out

    @staticmethod
    def _absorb_pair(pair: dict, target_ns: str, out: dict[str, set[str]]) -> None:
        src = str(pair.get("from", "")).strip()
        if not src:
            return
        to_val = pair.get("to")
        local = _extract_to_id(to_val)
        curie = to_curie(target_ns, local)
        if curie:
            out.setdefault(src, set()).add(curie)


def _extract_to_id(to_val: object) -> str:
    """A cross-ref target is a bare string; a UniProtKB target is an entry object -> primaryAccession."""
    if isinstance(to_val, dict):
        return str(to_val.get("primaryAccession") or to_val.get("id") or "").strip()
    return str(to_val or "").strip()


def _next_link(resp: HttpResponse) -> str | None:
    """Parse the ``Link: <url>; rel="next"`` pagination header, if present."""
    link = resp.headers.get("Link") or resp.headers.get("link")
    if not link:
        return None
    for part in link.split(","):
        segs = part.split(";")
        if len(segs) < 2:
            continue
        if 'rel="next"' in segs[1]:
            return segs[0].strip().strip("<>")
    return None
