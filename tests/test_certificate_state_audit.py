"""The offline audit instrument, and the shape L27 fixes for the published curve.

The baseline suite this script was written against lives outside the repo, so no test may read it.
Everything here runs on the committed fixture under ``tests/fixtures/certificate/suite``, which
carries all three legacy flag values and both Tier-A states.

The curve constraint being enforced (L27/L21): a precision delta plotted ACROSS the ``unavailable``
boundary is "refusing structure_absent buys +N precision" rendered as a line, in the one artifact
that travels without its caveat. So ``unavailable`` is reported as a declared abstention RATE, and
the precision-coverage curve is drawn only within the population an oracle can actually adjudicate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from studies.analysis.certificate_state_audit import (
    TIER_B_SWEEP_FILENAME,
    _identifier_oracle,
    _quarantined_id_columns,
    _structure_oracle,
    audit,
    audit_dataset,
    render_markdown,
)

FIXTURE_SUITE = Path(__file__).resolve().parent / "fixtures" / "certificate" / "suite"
FIXTURE_TSV = FIXTURE_SUITE / "necs" / "necs_MAPPED_chebi_d_mapped.tsv"


@pytest.fixture(scope="module")
def result() -> dict:
    return audit(FIXTURE_SUITE)


def test_the_fixture_covers_all_three_legacy_flag_values_and_both_tier_a_states() -> None:
    """If this fails the fixture has been narrowed and the guarantees below stopped being tested."""
    frame = pd.read_csv(FIXTURE_TSV, sep="\t")
    assert set(frame["chosen_kg_id_review"].fillna("no_flag")) == {
        "no_flag",
        "divergent_refmet",
        "conflict_no_structure",
    }
    assert set(frame["certificate_structure_status"]) == {"structure_present", "structure_absent"}


def test_audit_runs_offline_on_the_committed_fixture(result: dict) -> None:
    assert result["per_dataset"], "no dataset audited"
    assert result["provenance"]["kg_snapshot"] == "fixture-kg"


def test_audit_is_bit_identical_on_a_rerun() -> None:
    """G4. The suite directory is read-only input and the only input, so there is no cache confound
    and a rerun cannot drift."""
    first = json.dumps(audit(FIXTURE_SUITE), sort_keys=True)
    second = json.dumps(audit(FIXTURE_SUITE), sort_keys=True)
    assert first == second


def test_unscorable_rows_leave_the_denominator() -> None:
    """The pandas str-dtype trap. A gold column read as ``str`` turns a returned None into
    ``pd.NA``, and ``pd.NA is None`` is False -- so an identity guard admits every unscorable row
    into the denominator as an incorrect answer and depresses the reported precision."""
    assert _structure_oracle(pd.NA, {"AAAAAAAAAAAAAA"}) is None
    assert _structure_oracle(None, {"AAAAAAAAAAAAAA"}) is None
    assert _structure_oracle("", {"AAAAAAAAAAAAAA"}) is None
    assert _structure_oracle("AAAAAAAAAAAAAA", {"AAAAAAAAAAAAAA"}) is True

    frame = pd.read_csv(FIXTURE_TSV, sep="\t")
    scored = audit_dataset("necs", FIXTURE_TSV)["structure_oracle"]
    assert scored["n_scored"] < len(frame), "rows with no gold key must not be scored"


def test_identifier_oracle_keeps_unscorable_distinct_from_incorrect() -> None:
    row = pd.Series({"gold_hmdb": None})
    assert _identifier_oracle(row, {"HMDB": ["HMDB0000001"]}, {"gold_hmdb": "HMDB"}) is None
    row = pd.Series({"gold_hmdb": "HMDB0000009"})
    assert _identifier_oracle(row, {"HMDB": ["HMDB0000001"]}, {"gold_hmdb": "HMDB"}) is False


def test_monotonic_counter_columns_are_quarantined(tmp_path: Path) -> None:
    """A gold column that is fully unique AND strictly increasing is a row index wearing an
    accession's clothes; scoring against it reads as a catastrophic resolver failure and is a defect
    in the benchmark input."""
    frame = pd.DataFrame({"gold_hmdb": ["1", "2", "3", "4"], "gold_kegg": ["C1", "C9", "C3", "C2"]})
    quarantined = _quarantined_id_columns(frame)
    assert "gold_hmdb" in quarantined
    assert "gold_kegg" not in quarantined


# --------------------------------------------------------------------------------------------
# Figure 5 — two panels, and the boundary that must not be crossed
# --------------------------------------------------------------------------------------------


def test_panel_a_reports_abstention_as_a_rate_not_an_operating_point(result: dict) -> None:
    panel_a = result["per_dataset"][0]["figure5"]["panel_a_abstention"]
    assert panel_a["n_rows"] == 9
    assert panel_a["n_unavailable"] == 2
    assert panel_a["abstention_rate"] == pytest.approx(2 / 9, abs=1e-4)
    assert "precision" not in json.dumps(panel_a), "an abstention panel must carry no precision claim"


def test_panel_b_is_drawn_only_within_the_verifiable_population(result: dict) -> None:
    """L27. ``unavailable`` may never appear as an operating point: the delta across that boundary
    IS the L21-forbidden claim, rendered as a line."""
    panel_b = result["per_dataset"][0]["figure5"]["panel_b_precision_coverage"]
    states = {point["certificate_state"] for stratum in panel_b["strata"].values() for point in stratum["points"]}
    assert "unavailable" not in states
    assert "not_applicable" not in states


def test_panel_b_is_stratified_by_independent_source(result: dict) -> None:
    """L26. A verdict from the registry that supplied the committed node is not independent
    evidence, so the two populations are never averaged into one curve."""
    panel_b = result["per_dataset"][0]["figure5"]["panel_b_precision_coverage"]
    assert set(panel_b["strata"]) >= {"pubchem", "metabolomics-workbench"}
    mw = panel_b["strata"]["metabolomics-workbench"]
    assert mw["independent_of_selection"] is False


def test_every_operating_point_carries_sparsity_control_and_tier_b_resolution_rate(result: dict) -> None:
    figure5 = result["per_dataset"][0]["figure5"]
    assert figure5["sparsity_control"]["n_absent_oracle_could_fire"] is not None
    assert figure5["tier_b"]["n_rows_with_tier_b_outcome"] == 9
    assert figure5["tier_b"]["resolution_rate"] == pytest.approx(5 / 9, abs=1e-4)


def test_the_curve_is_refused_below_the_stated_resolution_floor(tmp_path: Path) -> None:
    """The endpoints are EXACT-name lookups while the annotator matches fuzzily, so a low
    resolution rate means the verdicts were computed on a biased easy subset."""
    frame = pd.read_csv(FIXTURE_TSV, sep="\t")
    frame.loc[frame.index[:8], "certificate_tier_b_outcome"] = "unresolvable"
    frame.loc[frame.index[:8], "certificate_independent_source"] = ""
    starved = tmp_path / "necs_MAPPED_chebi_d_mapped.tsv"
    frame.to_csv(starved, sep="\t", index=False)

    figure5 = audit_dataset("necs", starved)["figure5"]
    assert figure5["curve_publishable"] is False
    assert "resolution rate" in figure5["curve_not_publishable_reason"]


def test_a_suite_without_certificate_columns_still_audits(tmp_path: Path) -> None:
    """The pinned baseline predates the certificate and carries no ``certificate_*`` columns. The
    audit must degrade to the Tier-A derivation rather than crash, and must SAY it did."""
    frame = pd.read_csv(FIXTURE_TSV, sep="\t")
    frame = frame[[c for c in frame.columns if not c.startswith("certificate_")]]
    legacy_dir = tmp_path / "necs"
    legacy_dir.mkdir()
    frame.to_csv(legacy_dir / "necs_MAPPED_chebi_d_mapped.tsv", sep="\t", index=False)

    audited = audit_dataset("necs", legacy_dir / "necs_MAPPED_chebi_d_mapped.tsv")
    assert audited["certificate_source"] == "derived_from_kg_equivalent_ids"
    assert audited["figure5"]["curve_publishable"] is False


def test_committed_certificate_columns_are_preferred_over_the_derivation(result: dict) -> None:
    assert result["per_dataset"][0]["certificate_source"] == "certificate_columns"


def test_the_tier_b_sweep_is_referenced_by_a_fixed_committed_name() -> None:
    """Otherwise the Tier-B half of the figure has no reproducible provenance: the pinned suite
    carries no certificate columns, and a timestamped sweep path cannot be cited from a caption."""
    assert TIER_B_SWEEP_FILENAME.endswith(".json")
    assert "tier_b" in TIER_B_SWEEP_FILENAME


def test_markdown_renders_without_restating_a_figure_in_prose(result: dict) -> None:
    text = render_markdown(result)
    assert "Abstention" in text
    assert "unavailable" in text
