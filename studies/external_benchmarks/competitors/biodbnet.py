"""bioDBnet db2db client (REST API).

``GET https://biodbnet-abcc.ncifcrf.gov/webServices/rest.php/biodbnetRestApi.json`` with
``method=db2db&input=<db>&outputs=<db1,db2>&inputValues=<id1,id2>&taxonId=9606`` maps a batch from
one input db to several output dbs at once. Response is a JSON array of row objects keyed by the
db display names, e.g. ``[{"InputValue": "BRCA1", "Ensembl Gene ID": "ENSG...", "Gene ID": "672"}]``.
Multi-valued fields are ``//``-separated (bioDBnet's list delimiter, e.g. a symbol -> many UniProt
accessions ``P04637//Q8J016//...``); an unmapped field is ``"-"`` (an honest miss). Splitting on the
wrong delimiter silently collapses a whole list into one bogus id, so a real mapping (the canonical
accession IS in the list) scores as a miss — see ``_MULTI_SEP``.

Unlike g:Convert, db2db returns every requested output db in one call, so ``map_batch`` maps a
chunk to ONE target namespace (the base fan-out asks per namespace) but reads that namespace's
column out of the row. The taxon is fixed to human (9606), matching the backbone gold.
"""

from __future__ import annotations

from .base import CompetitorClient, HttpResponse
from .namespaces import BIODBNET_DB, to_curie

BIODBNET_URL = "https://biodbnet-abcc.ncifcrf.gov/webServices/rest.php/biodbnetRestApi.json"
TAXON_HUMAN = "9606"
# bioDBnet db2db returns multi-valued output fields as a ``//``-delimited list (verified live:
# ``Gene Symbol`` -> ``UniProt Accession`` yields e.g. ``P04637//Q8J016//...`` for TP53). An earlier
# ``"; "`` guess never matched, collapsing every multi-accession list into one bogus id — the reason
# symbol->UniProtKB scored ~0% for a mapping the tool actually returns correctly.
_MULTI_SEP = "//"
_NO_MAPPING = {"-", "", "null", "none", "nan"}


class BioDBnetClient(CompetitorClient):
    name = "biodbnet"
    batch_size = 200  # bioDBnet recommends modest batch sizes

    def source_code(self, source_ns: str) -> str | None:
        return BIODBNET_DB.get(source_ns)

    def target_code(self, target_ns: str) -> str | None:
        return BIODBNET_DB.get(target_ns)

    def map_batch(self, ids: list[str], source_ns: str, target_ns: str) -> dict[str, set[str]]:
        input_db = self.source_code(source_ns)
        output_db = self.target_code(target_ns)
        assert input_db is not None and output_db is not None  # supported by construction
        resp = self._request_with_retries(
            "GET",
            BIODBNET_URL,
            params={
                "method": "db2db",
                "format": "row",
                "input": input_db,
                "outputs": output_db,
                "inputValues": ",".join(ids),
                "taxonId": TAXON_HUMAN,
            },
        )
        return self._parse(resp, ids, output_db, target_ns)

    @staticmethod
    def _parse(resp: HttpResponse, ids: list[str], output_db: str, target_ns: str) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {i: set() for i in ids}
        if not resp.ok:
            return out  # reachable error => no mappings this batch (outages already raised)
        body = resp.json()
        rows = body if isinstance(body, list) else (body or {}).get("results", [])
        for row in rows or []:
            incoming = str(row.get("InputValue", "")).strip()
            if not incoming:
                continue
            raw = str(row.get(output_db, "")).strip()
            for part in raw.split(_MULTI_SEP):
                p = part.strip()
                if not p or p.lower() in _NO_MAPPING:
                    continue
                curie = to_curie(target_ns, p)
                if curie:
                    out.setdefault(incoming, set()).add(curie)
        return out
