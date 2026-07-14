"""g:Convert client (g:Profiler REST API).

``POST https://biit.cs.ut.ee/gprofiler/api/convert/convert/`` with
``{"organism": "hsapiens", "target": <code>, "query": [ids...]}`` converts a batch of gene
identifiers to ONE target namespace. g:Convert auto-detects the input namespace, so the source
only needs to be a gene/protein identifier kind (no source code beyond the organism).

Response: ``{"result": [{"incoming", "converted", "name", "namespaces", ...}]}``. ``converted`` is
the string ``"None"`` when g:Convert found no mapping (an honest miss). One incoming id can yield
several result rows (several converted values) — all are collected into the query's CURIE set.
"""

from __future__ import annotations

from .base import CompetitorClient, HttpResponse
from .namespaces import GCONVERT_SOURCE, GCONVERT_TARGET, to_curie

GCONVERT_URL = "https://biit.cs.ut.ee/gprofiler/api/convert/convert/"
ORGANISM = "hsapiens"
_NO_MAPPING = {"none", "nan", "n/a", ""}


class GConvertClient(CompetitorClient):
    name = "gconvert"
    batch_size = 500  # g:Convert comfortably accepts large query lists

    def source_code(self, source_ns: str) -> str | None:
        return source_ns if source_ns in GCONVERT_SOURCE else None

    def target_code(self, target_ns: str) -> str | None:
        return GCONVERT_TARGET.get(target_ns)

    def map_batch(self, ids: list[str], source_ns: str, target_ns: str) -> dict[str, set[str]]:
        code = self.target_code(target_ns)
        assert code is not None  # supported by construction (base fan-out filters first)
        resp = self._request_with_retries(
            "POST",
            GCONVERT_URL,
            json={"organism": ORGANISM, "target": code, "query": ids},
            headers={"Content-Type": "application/json"},
        )
        return self._parse(resp, ids, target_ns)

    @staticmethod
    def _parse(resp: HttpResponse, ids: list[str], target_ns: str) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {i: set() for i in ids}
        if not resp.ok:
            # A reachable 4xx (e.g. an unknown target) is not an outage — treat as no mappings for
            # this batch (honest miss), not a crash. Outages already raised in _request_with_retries.
            return out
        body = resp.json() or {}
        for item in body.get("result", []) or []:
            incoming = str(item.get("incoming", "")).strip()
            converted = str(item.get("converted", "")).strip()
            if not incoming or converted.lower() in _NO_MAPPING:
                continue
            curie = to_curie(target_ns, converted)
            if curie:
                out.setdefault(incoming, set()).add(curie)
        return out
