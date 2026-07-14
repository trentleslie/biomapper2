"""Unit 4 (layer b) — validation.

Where reconciliation (verify.py) proves the numbers match the artifacts, validation proves
the *artifacts reflect reality*. A self-consistent but upstream-corrupted pipeline passes
reconciliation and fails here. Checks:

  (a) gold-column spot-check   — sampled adapter gold values vs the source table.
  (b) second-source structure  — dataset InChIKey vs an RDKit derivation from SMILES.
  (c) fallback-bucket recompute — independent count of fallback-resolved predictions.
  (d) protocol-parity gate      — reproduce a known published Hajjar cell within tolerance
                                  BEFORE any BioMapper marker may be plotted beside it.
  (e) citation spot-check       — every transcribed competitor number carries DOI + table ref.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .adapters.hajjar import RAW_INCHIKEY_COL, RAW_NAME_COL
from .config import CompetitorResult, DatasetConfig
from .scorers.structure_oracle_scorer import CHOSEN_COL, StructureOracle, _has_prediction, first_block

logger = logging.getLogger(__name__)


@dataclass
class ValidationReport:
    passed: bool = True
    failures: list[dict[str, Any]] = field(default_factory=list)
    skips: list[str] = field(default_factory=list)

    def fail(self, check: str, detail: str) -> None:
        self.passed = False
        self.failures.append({"check": check, "detail": detail})

    def skip(self, reason: str) -> None:
        self.skips.append(reason)


def spot_check_gold_column(
    input_df: pd.DataFrame,
    source_df: pd.DataFrame,
    config: DatasetConfig,
    sample_indices: Iterable[int] | None = None,
    report: ValidationReport | None = None,
) -> ValidationReport:
    """(a) Confirm the adapter's gold InChIKey column equals the source table verbatim.

    A swapped/mis-joined gold column (upstream corruption) diverges here even though the
    numbers downstream are internally consistent.
    """
    report = report or ValidationReport()
    idxs = list(sample_indices) if sample_indices is not None else list(range(len(input_df)))
    for i in idxs:
        got = str(input_df.iloc[i][config.gold_inchikey_column]).strip()
        src = str(source_df.iloc[i][RAW_INCHIKEY_COL]).strip()
        if got != src:
            report.fail(
                "gold_column_spotcheck",
                f"row {i} name={source_df.iloc[i][RAW_NAME_COL]!r}: adapter gold {got!r} != source {src!r}",
            )
    return report


def second_source_structure_check(
    mapped_df: pd.DataFrame,
    config: DatasetConfig,
    sample_indices: Iterable[int] | None = None,
    report: ValidationReport | None = None,
) -> ValidationReport:
    """(b) Cross-check the dataset InChIKey against an RDKit derivation from SMILES.

    Where SMILES is present, derive the InChIKey first-block via RDKit and require it to
    agree with the gold InChIKey first-block. Rows without SMILES are skipped with a logged
    reason (not failed). A mis-resolved/corrupted gold structure fails here.
    """
    from rdkit import Chem, RDLogger

    RDLogger.DisableLog("rdApp.*")  # type: ignore[attr-defined]  # runtime API; rdkit ships no stub for it

    report = report or ValidationReport()
    smiles_col = config.gold_smiles_column
    if not smiles_col or smiles_col not in mapped_df.columns:
        report.skip("no SMILES column available for second-source structure check")
        return report

    idxs = list(sample_indices) if sample_indices is not None else list(range(len(mapped_df)))
    for i in idxs:
        row = mapped_df.iloc[i]
        smiles = str(row.get(smiles_col) or "").strip()
        gold_block = first_block(row.get(config.gold_inchikey_column))
        if not smiles:
            report.skip(f"row {i}: no SMILES; skipped structure cross-check")
            continue
        if gold_block is None:
            report.skip(f"row {i}: no gold InChIKey; skipped structure cross-check")
            continue
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            report.skip(f"row {i}: RDKit could not parse SMILES {smiles!r}; skipped")
            continue
        derived_block = first_block(Chem.MolToInchiKey(mol))
        if derived_block is not None and derived_block != gold_block:
            report.fail(
                "second_source_structure",
                f"row {i} name={row.get(config.name_column)!r}: gold block {gold_block} != "
                f"RDKit-from-SMILES block {derived_block}",
            )
    return report


def recompute_fallback_bucket(
    results: dict[str, Any],
    mapped_df: pd.DataFrame,
    config: DatasetConfig,
    oracle: StructureOracle,
    report: ValidationReport | None = None,
) -> ValidationReport:
    """(c) Independently recompute the fallback/circularity bucket count and compare."""
    report = report or ValidationReport()
    expected = results.get("structure", {}).get("fallback_bucket", {}).get("count")
    count = 0
    for _, row in mapped_df.iterrows():
        chosen = row.get(CHOSEN_COL)
        if not _has_prediction(chosen):
            continue
        cid = str(chosen).strip()
        if oracle.kg_block(cid) is None and oracle.resolved_block(cid) is not None:
            count += 1
    if expected != count:
        report.fail("fallback_bucket_recompute", f"reported {expected} != recomputed {count}")
    return report


def protocol_parity_gate(
    reproduced_value: float,
    published_value: float,
    tolerance: float,
    report: ValidationReport | None = None,
) -> ValidationReport:
    """(d) Reproduce a known published Hajjar cell within tolerance. Outside tolerance
    BLOCKS figure generation — no BioMapper marker is plotted beside an unreproduced cell.
    """
    report = report or ValidationReport()
    if abs(reproduced_value - published_value) > tolerance:
        report.fail(
            "protocol_parity_gate",
            f"reproduced {reproduced_value} vs published {published_value} exceeds tol {tolerance}",
        )
    return report


def citation_spot_check(
    competitors: Iterable[CompetitorResult],
    report: ValidationReport | None = None,
) -> ValidationReport:
    """(e) Every transcribed competitor number must carry a DOI + table ref. Transcribed
    numbers are citation-checked, not arithmetic-verified (Metabolon-96.5% scar).
    """
    report = report or ValidationReport()
    for c in competitors:
        if not (c.doi and c.doi.strip()):
            report.fail("citation_spotcheck", f"competitor {c.tool}: missing DOI")
        if not (c.table_ref and c.table_ref.strip()):
            report.fail("citation_spotcheck", f"competitor {c.tool}: missing table_ref")
    return report


def validate_all(
    *,
    input_df: pd.DataFrame,
    source_df: pd.DataFrame,
    mapped_df: pd.DataFrame,
    results: dict[str, Any],
    config: DatasetConfig,
    oracle: StructureOracle,
    competitors: Iterable[CompetitorResult],
    protocol_parity: tuple[float, float, float] | None = None,
    sample_indices: Iterable[int] | None = None,
) -> ValidationReport:
    """Run all validation layers into one report. ``protocol_parity`` is
    ``(reproduced, published, tolerance)`` for the parity gate (d)."""
    report = ValidationReport()
    spot_check_gold_column(input_df, source_df, config, sample_indices, report)
    second_source_structure_check(mapped_df, config, sample_indices, report)
    recompute_fallback_bucket(results, mapped_df, config, oracle, report)
    if protocol_parity is not None:
        protocol_parity_gate(*protocol_parity, report=report)
    citation_spot_check(competitors, report)
    return report
