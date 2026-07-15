"""Competitor runner — run each incumbent tool on the SAME backbone rows BioMapper was scored on.

Consumes the identical ``input_df`` the ``curie_scorer`` arm uses (a ``CurieDatasetConfig``'s
``name_column`` query + held-out gold cross-ref columns) and, per tool, produces a scorable
``mapped_df`` with the SAME ``chosen_kg_id`` / ``kg_equivalent_ids`` shape BioMapper emits — so
``scorers.curie_scorer.score_curie`` scores every tool by the identical rule and gold.

A competitor has no single "chosen" id, so ``chosen_kg_id`` is left empty and every predicted CURIE
goes into ``kg_equivalent_ids`` (the scorer unions the two anyway). Target namespaces a tool can't
express are recorded as ``unsupported_targets`` (protocol deltas), not silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..config import CurieDatasetConfig
from .base import CompetitorClient
from .namespaces import BACKBONE_SOURCE_NAMESPACE, curies_to_equiv_cell


class UnknownBackboneSourceError(KeyError):
    """Raised when a backbone has no registered source namespace (can't tell tools what to map from)."""


@dataclass(frozen=True)
class CompetitorRun:
    """One tool's outputs on a backbone, plus the protocol deltas needed to read them honestly."""

    tool: str
    dataset: str
    source_namespace: str
    supported_targets: list[str]
    unsupported_targets: list[str]
    mapped_df: pd.DataFrame
    n_rows: int
    notes: list[str] = field(default_factory=list)


def source_namespace_for(config: CurieDatasetConfig) -> str:
    ns = BACKBONE_SOURCE_NAMESPACE.get(config.key)
    if ns is None:
        raise UnknownBackboneSourceError(
            f"no source namespace registered for backbone {config.key!r}; add it to "
            f"BACKBONE_SOURCE_NAMESPACE so competitors know what they are mapping from."
        )
    return ns


def build_competitor_mapped_df(
    input_df: pd.DataFrame, config: CurieDatasetConfig, predictions: dict[str, set[str]]
) -> pd.DataFrame:
    """Attach a tool's predictions to the held-out-gold input, in the scorer's expected shape.

    Preserves the ``name_column`` query + every gold column verbatim (so the gold and row set are
    IDENTICAL to BioMapper's), adding an empty ``chosen_kg_id`` and a ``kg_equivalent_ids`` cell
    built from the query's predicted CURIE set.
    """
    out = input_df.copy()
    queries = out[config.name_column].astype(str)
    out["chosen_kg_id"] = ""
    # object-dtype Series so each cell holds a dict (the ``kg_equivalent_ids`` shape the scorer reads).
    out["kg_equivalent_ids"] = pd.Series(
        [curies_to_equiv_cell(predictions.get(q, set())) for q in queries],
        index=out.index,
        dtype=object,
    )
    return out


def run_competitor(client: CompetitorClient, input_df: pd.DataFrame, config: CurieDatasetConfig) -> CompetitorRun:
    """Run one competitor over a backbone's rows; return a scorable run + its protocol deltas."""
    source_ns = source_namespace_for(config)
    supported, unsupported = client.supported_targets(config.target_vocabs, source_ns)
    queries = [str(q) for q in input_df[config.name_column].tolist()]
    predictions = client.map_ids(queries, source_ns, config.target_vocabs) if supported else {}
    mapped_df = build_competitor_mapped_df(input_df, config, predictions)
    notes: list[str] = []
    if unsupported:
        notes.append(
            f"{client.name} cannot express target namespace(s) {unsupported}; rows whose only gold "
            f"cross-ref is in those namespaces can never be matched by this tool (protocol delta)."
        )
    if not supported:
        notes.append(f"{client.name} expresses NONE of {list(config.target_vocabs)} — all rows are misses.")
    return CompetitorRun(
        tool=client.name,
        dataset=config.key,
        source_namespace=source_ns,
        supported_targets=supported,
        unsupported_targets=unsupported,
        mapped_df=mapped_df,
        n_rows=len(input_df),
        notes=notes,
    )


def run_all_competitors(
    clients: list[CompetitorClient], input_df: pd.DataFrame, config: CurieDatasetConfig
) -> list[CompetitorRun]:
    """Run every competitor on the same rows. Order is preserved; each run is independent."""
    return [run_competitor(client, input_df, config) for client in clients]


def score_competitor_run(run: CompetitorRun, config: CurieDatasetConfig) -> dict[str, Any]:
    """Score one competitor run with the IDENTICAL ``curie_scorer`` used for BioMapper."""
    from ..scorers.curie_scorer import score_curie

    result = score_curie(run.mapped_df, config)
    result["tool"] = run.tool
    result["supported_targets"] = run.supported_targets
    result["unsupported_targets"] = run.unsupported_targets
    result["protocol_notes"] = run.notes
    return result
