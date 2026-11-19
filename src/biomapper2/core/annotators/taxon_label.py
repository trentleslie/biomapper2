"""TaxonLabelAnnotator: 16S classifier labels -> prokaryote NCBITaxon nodes (16S plan U5, PR1 form).

PR1 is search-based. For each label it:

1. parses the label (``core/taxon_label.py``) and abstains WITHOUT a search call when the label is empty
   or placeholder-only, a eukaryote/host label, an organelle label, or a clone code with no Latin token;
2. runs ONE bulk Kestrel hybrid search over the unique query names of the remaining rows;
3. keeps only NCBITaxon hits and selects among them with the pinned NCBI snapshot
   (``core/ncbi_taxonomy.py``), never falling back to a UMLS/EFO/CHV top-1:

   * prokaryote mode (16S-format labels, and bare names found in the snapshot): the hit must be a
     prokaryote node in the snapshot, one of its NCBI names must equal the query name, and, when the
     label states a rank (or a SILVA depth hint the snapshot confirms), the node must be at that rank.
     The snapshot names, not Kestrel's display name, decide the name match, so a legacy phylum name
     ("Firmicutes") matches Bacillota through its NCBI synonym.
   * delegated mode (bare names absent from the snapshot, e.g. "Homo sapiens"): any NCBITaxon hit except
     the non-prokaryote side of a prokaryote homonym pair (the guard checks the HIT's taxid), preferring
     a hit whose Kestrel name or synonym equals the query.

The per-row outcome travels on the existing ``annotator_source`` channel (``get_source``): a route
(``exact``, ``synonym``, ``superset``, ``delegated``) or an abstain reason (``abstain:<reason>``). A Kestrel
fault is never an abstention: the row is recorded through ``fault_tracking.record_kestrel_fault`` and its
availability and source read ``unavailable``. Per-row state lives in the cache dict the engine threads
through one annotate call, never on the instance (one Mapper serves concurrent requests).
"""

from __future__ import annotations

import logging
from typing import Any, cast

import pandas as pd

from ...config import HYBRID_SEARCH_LIMIT
from ...utils import AssignedIDsDict, text_is_not_empty
from .. import ncbi_taxonomy
from ..taxon_label import TaxonParse, parse_taxon_label
from .base import (
    AVAILABILITY_NO_MATCH,
    AVAILABILITY_NOT_QUERIED,
    AVAILABILITY_UNAVAILABLE,
    AVAILABILITY_VOTED,
    REFMET_SOURCE_NOT_QUERIED,
    REFMET_SOURCE_UNAVAILABLE,
    BaseAnnotator,
    stable_result_order,
)
from .kestrel_hybrid import KestrelHybridSearchAnnotator

TAXON_CATEGORY = "biolink:OrganismTaxon"
NCBITAXON_PREFIX = "NCBITaxon"

ROUTE_EXACT = "exact"
ROUTE_SYNONYM = "synonym"
ROUTE_SUPERSET = "superset"
ROUTE_DELEGATED = "delegated"
ROUTES = frozenset({ROUTE_EXACT, ROUTE_SYNONYM, ROUTE_SUPERSET, ROUTE_DELEGATED})

ABSTAIN_EMPTY = "abstain:empty"
ABSTAIN_EUKARYOTE = "abstain:eukaryote"
ABSTAIN_HOST_OR_ORGANELLE = "abstain:host_or_organelle"
ABSTAIN_CLONE_CODE = "abstain:clone_code"
ABSTAIN_NO_MATCH = "abstain:no_match"
ABSTAIN_REASONS = frozenset(
    {ABSTAIN_EMPTY, ABSTAIN_EUKARYOTE, ABSTAIN_HOST_OR_ORGANELLE, ABSTAIN_CLONE_CODE, ABSTAIN_NO_MATCH}
)

# Abstentions decided from the label alone (no search call is made for these rows).
_PRE_SEARCH_ABSTAIN = {"empty": ABSTAIN_EMPTY, "eukaryote": ABSTAIN_EUKARYOTE, "organelle": ABSTAIN_HOST_OR_ORGANELLE}


class TaxonLabelAnnotator(BaseAnnotator):

    slug = "taxon-label"

    # The bulk hybrid search. A class attribute so tests can patch it; reuses the generic annotator's
    # batched request (same >= 0.5 score filter).
    _kestrel_hybrid_search = staticmethod(KestrelHybridSearchAnnotator._kestrel_hybrid_search)

    # --------------------------------------------------------------------------------- planning

    @staticmethod
    def _plan(label: Any) -> dict[str, Any]:
        """Decide, from the label alone, whether to abstain or what to search (needs the snapshot)."""
        parse: TaxonParse = parse_taxon_label(label if text_is_not_empty(label) else None)
        plan: dict[str, Any] = {"parse": parse, "abstain": None, "query": None, "rank": None, "mode": None}
        if parse.is_16s_format:
            reason = _PRE_SEARCH_ABSTAIN.get(parse.label_class)
            if reason is None and parse.label_class == "informal" and not parse.has_latin_token:
                reason = ABSTAIN_CLONE_CODE
        else:
            reason = ABSTAIN_EMPTY if parse.label_class == "empty" else None
        if reason is not None or parse.query_name is None:
            plan["abstain"] = reason or ABSTAIN_EMPTY
            return plan

        query = parse.query_name
        rank = parse.query_rank
        if rank is not None and parse.rank_is_hint and not ncbi_taxonomy.lookup(query, rank=rank):
            # A SILVA depth is only a hint: unconfirmed at that rank in the snapshot -> do not enforce it.
            rank = None
        in_snapshot = bool(ncbi_taxonomy.lookup(query))
        plan.update(
            query=query,
            rank=rank,
            mode="prokaryote" if (parse.is_16s_format or in_snapshot) else "delegated",
        )
        return plan

    def build_availability_cache(
        self, items: dict | pd.Series | pd.DataFrame, name_field: str
    ) -> dict[str, Any] | None:
        """Parse every label once (no I/O beyond the packaged snapshot); searches happen on first vote."""
        if isinstance(items, pd.DataFrame):
            labels = items[name_field].tolist() if name_field in items else []
        else:
            labels = [items.get(name_field)]
        plans = {self._key(label): self._plan(label) for label in labels}
        return {"plans": plans, "results": {}, "faulted": set(), "searched": False}

    @staticmethod
    def _key(label: Any) -> str:
        return "" if not text_is_not_empty(label) else str(label)

    # ---------------------------------------------------------------------------------- search

    def _ensure_search(self, cache: dict[str, Any], prefixes: list[str] | None, limit: int, fault_targets) -> None:
        if cache["searched"]:
            return
        cache["searched"] = True
        queries = sorted({p["query"] for p in cache["plans"].values() if p["abstain"] is None})
        if not queries:
            return
        try:
            cache["results"] = self._kestrel_hybrid_search(queries, TAXON_CATEGORY, prefixes, limit=limit)
        except Exception as exc:
            from ..fault_tracking import record_kestrel_fault

            logging.warning("taxon-label hybrid search failed for %d names: %s", len(queries), exc)
            cache["faulted"] = set(queries)
            for target, label in fault_targets:
                plan = cache["plans"].get(self._key(label))
                if plan is not None and plan["abstain"] is None:
                    record_kestrel_fault(target, f"taxon-label hybrid-search: {exc}")

    # ------------------------------------------------------------------------------- selection

    @staticmethod
    def _ncbi_taxid(row: dict) -> int | None:
        node_id = str(row.get("id") or "")
        prefix, _, local = node_id.partition(":")
        if prefix != NCBITAXON_PREFIX or not local.isdigit():
            return None
        return int(local)

    @classmethod
    def _select(cls, plan: dict[str, Any], rows: list[dict]) -> tuple[dict | None, str]:
        """Pick one NCBITaxon row for a searched plan, or none. Returns (row, route-or-abstain-reason)."""
        rows = stable_result_order(rows)
        query = plan["query"]
        query_cf = query.casefold()
        if plan["mode"] == "prokaryote":
            eligible: list[tuple[dict, str]] = []
            for row in rows:
                taxid = cls._ncbi_taxid(row)
                if taxid is None or not ncbi_taxonomy.is_prokaryote(taxid):
                    continue
                if plan["rank"] is not None and ncbi_taxonomy.rank_of(taxid) != plan["rank"]:
                    continue
                names = {n.casefold() for n in ncbi_taxonomy.names_of(taxid)}
                if query_cf not in names:
                    continue
                exact = (ncbi_taxonomy.scientific_name(taxid) or "").casefold() == query_cf
                eligible.append((row, ROUTE_EXACT if exact else ROUTE_SYNONYM))
            if not eligible:
                return None, ABSTAIN_NO_MATCH
            row, route = eligible[0]  # stable_result_order: highest score, ties by id
            if plan["parse"].label_class == "superset":
                route = ROUTE_SUPERSET
            return row, route

        pool = [
            r
            for r in rows
            if (taxid := cls._ncbi_taxid(r)) is not None and not ncbi_taxonomy.is_homonym_nonprokaryote_side(taxid)
        ]
        if not pool:
            return None, ABSTAIN_NO_MATCH
        named = [r for r in pool if KestrelHybridSearchAnnotator._symbol_matches(r, query)]
        return (named or pool)[0], ROUTE_DELEGATED

    def _decide(self, label: Any, cache: dict[str, Any]) -> tuple[dict | None, str, str]:
        """(chosen row, source value, availability) for one label, from the cache only."""
        plan = cache["plans"].get(self._key(label)) or self._plan(label)
        if plan["abstain"] is not None:
            return None, plan["abstain"], AVAILABILITY_NOT_QUERIED
        if not cache["searched"]:
            return None, REFMET_SOURCE_NOT_QUERIED, AVAILABILITY_NOT_QUERIED
        if plan["query"] in cache["faulted"]:
            return None, REFMET_SOURCE_UNAVAILABLE, AVAILABILITY_UNAVAILABLE
        row, outcome = self._select(plan, cache["results"].get(plan["query"]) or [])
        return row, outcome, (AVAILABILITY_VOTED if row is not None else AVAILABILITY_NO_MATCH)

    def _votes(self, label: Any, cache: dict[str, Any]) -> AssignedIDsDict:
        row, outcome, _ = self._decide(label, cache)
        if row is None:
            return {self.slug: {}}
        taxid = self._ncbi_taxid(row)
        metadata = {"score": row.get("score"), "resolved_via": f"taxon_label:{outcome}"}
        return {self.slug: {NCBITAXON_PREFIX: {str(taxid): metadata}}}

    # ------------------------------------------------------------------------------ annotator API

    def get_annotations(
        self,
        entity: dict | pd.Series,
        name_field: str,
        category: str,
        prefixes: list[str] | None = None,
        prefer_human: bool = True,
        preferred_prefixes: set[str] | None = None,
        accepted_categories: set[str] | None = None,
        candidate_limit: int | None = None,
        cache: dict | None = None,
    ) -> AssignedIDsDict:
        """Implements BaseAnnotator.get_annotations (single path). ``preferred_prefixes`` is accepted and
        ignored: selection is NCBITaxon-only by construction."""
        label = entity.get(name_field)
        if cache is None:
            cache = cast(dict[str, Any], self.build_availability_cache(entity, name_field))
        limit = candidate_limit if candidate_limit is not None else HYBRID_SEARCH_LIMIT
        self._ensure_search(cache, prefixes, limit, [(entity, label)])
        return self._votes(label, cache)

    def get_annotations_bulk(
        self,
        entities: pd.DataFrame,
        name_field: str,
        category: str,
        prefixes: list[str] | None = None,
        prefer_human: bool = True,
        preferred_prefixes: set[str] | None = None,
        accepted_categories: set[str] | None = None,
        candidate_limit: int | None = None,
        cache: dict | None = None,
    ) -> pd.Series:
        """Implements BaseAnnotator.get_annotations_bulk: one search for all unique query names."""
        if cache is None:
            cache = cast(dict[str, Any], self.build_availability_cache(entities, name_field))
        limit = candidate_limit if candidate_limit is not None else HYBRID_SEARCH_LIMIT
        self._ensure_search(cache, prefixes, limit, [(row, row.get(name_field)) for _, row in entities.iterrows()])
        return pd.Series([self._votes(label, cache) for label in entities[name_field]], index=entities.index)

    def get_availability(self, entity: dict | pd.Series, name_field: str, cache: dict | None = None) -> dict[str, str]:
        if cache is None:
            return {self.slug: AVAILABILITY_NOT_QUERIED}
        return {self.slug: self._decide(entity.get(name_field), cache)[2]}

    def get_source(self, entity: dict | pd.Series, name_field: str, cache: dict | None = None) -> dict[str, str]:
        """The row's route (exact/synonym/superset/delegated) or abstain reason (``abstain:<reason>``).

        ``unavailable`` marks a Kestrel fault, ``not_queried`` a row this annotator did not run for.
        PR2 (U9) maps those two to a null ``taxon_route``.
        """
        if cache is None:
            return {self.slug: REFMET_SOURCE_NOT_QUERIED}
        return {self.slug: self._decide(entity.get(name_field), cache)[1]}

    def kestrel_searched(self, entity: dict | pd.Series, name_field: str, cache: dict | None = None) -> bool | None:
        """True only for rows whose query name was in the bulk search (abstentions made no call)."""
        if cache is None:
            return False
        plan = cache["plans"].get(self._key(entity.get(name_field)))
        return bool(plan is not None and plan["abstain"] is None and cache["searched"])

    def kestrel_search_request(
        self, entity: dict | pd.Series, name_field: str, cache: dict | None = None
    ) -> dict[str, str] | None:
        """The cleaned query name and taxon category the bulk search sent for this row (None if none)."""
        if not self.kestrel_searched(entity, name_field, cache=cache):
            return None
        plan = cast(dict[str, Any], cache)["plans"][self._key(entity.get(name_field))]
        return {"search_text": plan["query"], "category": TAXON_CATEGORY}
