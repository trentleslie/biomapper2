"""Unit 0 — pre-build de-risk probe: provided-structure-id coverage on the refused-lipid population.

The sprint headline (refused lipids become adjudicable via the provided-id oracle) only materializes
where BOTH sides of a cross-cohort link carry a resolvable structure id. This probe measures per-cohort
lipid structure-id coverage and reports the both-sides ceiling per pair, so a pair that cannot move is
re-scoped OUT before the build spends on it. Read-only; no code under test depends on it.

Result of the 2026-09-01 run (persisted to ~/external_benchmark_runs/unit0_provided_id_coverage_*):
  necs<->arivale  62-71% cohort-side  -> VIABLE
  necs<->xuetal   70% (Metabolon names join to the gold file despite an empty id_columns config) -> VIABLE
  necs<->llfs     2%   -> coverage-limited (non-Metabolon names, no ids)
  necs<->blsa     0%   -> coverage-limited (names-only)
NECS side ~80% throughout. pygoslin/LIPID MAPS name-parse path was 0/40 / 0/60 -> dropped.
"""

from __future__ import annotations

# pragma: no cover  — supervised read-only probe; see the module docstring for the recorded result.
