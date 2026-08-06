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
    ORACLE_INDEPENDENCE_MAX_AGREEMENT,
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


def test_the_fixture_is_actually_tracked_by_git() -> None:
    """The repo's blanket ``*.tsv`` ignore silently un-commits this fixture.

    Every test in this file would still pass on the machine that created it, and the whole audit
    would fail to run on a fresh clone. Caught once already; pinned so it cannot happen twice.
    """
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(FIXTURE_TSV.relative_to(FIXTURE_TSV.parents[3]))],
        cwd=FIXTURE_TSV.parents[3],
        capture_output=True,
        text=True,
    )
    assert tracked.returncode == 0, f"the audit fixture is not tracked by git: {tracked.stderr.strip()}"


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


def test_panel_b_is_stratified_by_source_AND_independence(tmp_path: Path) -> None:
    """L26. A verdict from the registry that supplied the committed node is not independent
    evidence, so the two populations are never averaged into one curve.

    Keyed on the PAIR, not on the source alone: keying on source alone put rows the registry also
    selected into the same curve as rows it did not, which is the averaging this docstring says
    never happens. On the pinned suite every metabolite arm is mixed, so this is the expected shape
    of the first live sweep.
    """
    strata = audit(_dependent_stratum_arm(tmp_path))["per_dataset"][0]["figure5"]["panel_b_precision_coverage"][
        "strata"
    ]
    assert "metabolomics-workbench/indep=false" in strata
    assert "metabolomics-workbench/indep=true" in strata
    assert strata["metabolomics-workbench/indep=false"]["independent_of_selection"] is False
    assert strata["metabolomics-workbench/indep=true"]["independent_of_selection"] is True
    assert strata["metabolomics-workbench/indep=false"]["independent_source"] == "metabolomics-workbench"


def test_every_operating_point_carries_sparsity_control_and_tier_b_resolution_rate(result: dict) -> None:
    figure5 = result["per_dataset"][0]["figure5"]
    assert figure5["sparsity_control"]["n_absent_oracle_could_fire"] is not None
    assert figure5["tier_b"]["n_rows_with_tier_b_outcome"] == 9
    # Two distinct rates, deliberately: the all-rows figure reports how much of the arm Tier B
    # reached, while ``resolution_rate`` is the GATE and is scoped to the population Panel B plots.
    assert figure5["tier_b"]["resolution_rate_all_rows"] == pytest.approx(5 / 9, abs=1e-4)
    n_verifiable = figure5["tier_b"]["n_verifiable"]
    assert figure5["tier_b"]["resolution_rate"] == pytest.approx(
        figure5["tier_b"]["n_tier_b_resolved_verifiable"] / n_verifiable, abs=1e-4
    )


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


# --------------------------------------------------------------------------------------------
# Input schema: the two accepted shapes, and the refusal of everything between them
# --------------------------------------------------------------------------------------------


def _arm_from(frame: pd.DataFrame, tmp_path: Path) -> Path:
    arm = tmp_path / "necs"
    arm.mkdir(parents=True, exist_ok=True)
    frame.to_csv(arm / "necs_MAPPED_chebi_d_mapped.tsv", sep="\t", index=False)
    return arm / "necs_MAPPED_chebi_d_mapped.tsv"


def test_a_partial_certificate_is_refused_rather_than_completed_with_defaults(tmp_path: Path) -> None:
    """Presence of ``certificate_state`` used to mean "this frame has a certificate".

    Every absent sibling then defaulted -- source to None, outcome to 'off' -- so a truncated or
    hand-merged TSV produced a Panel B stratified against values nothing measured, while the
    artifact printed ``certificate_source: certificate_columns`` beside it. The missing column has to
    be named in the error, because a partial frame is usually a broken join and the operator needs
    to know which side dropped.
    """
    frame = pd.read_csv(FIXTURE_TSV, sep="\t").drop(columns=["certificate_tier_b_outcome"])
    with pytest.raises(ValueError, match="certificate_tier_b_outcome"):
        audit_dataset("necs", _arm_from(frame, tmp_path))


def test_an_empty_certificate_state_is_not_read_as_an_abstention(tmp_path: Path) -> None:
    """``fillna('unavailable')`` turned a hole in the input into a declared refusal.

    That is the one number Panel A exists to report, so a partial file would have inflated the
    headline abstention rate with rows the resolver never refused -- and nothing downstream could
    tell the fabricated ones apart from the real ones.
    """
    frame = pd.read_csv(FIXTURE_TSV, sep="\t")
    frame.loc[frame.index[0], "certificate_state"] = None
    with pytest.raises(ValueError, match="certificate_state is empty"):
        audit_dataset("necs", _arm_from(frame, tmp_path))


def test_an_unknown_certificate_state_cannot_become_an_operating_point(tmp_path: Path) -> None:
    """``_figure5`` groups on the raw state string, and anything outside ABSTENTION/OUT_OF_SCOPE
    joins the verifiable population by default -- so a typo or a future enum value would be drawn as
    a curve point rather than rejected."""
    frame = pd.read_csv(FIXTURE_TSV, sep="\t")
    frame.loc[frame.index[0], "certificate_state"] = "probably_right"
    with pytest.raises(ValueError, match="probably_right"):
        audit_dataset("necs", _arm_from(frame, tmp_path))


@pytest.mark.parametrize("column", ["certificate_structure_status", "certificate_tier_b_outcome"])
def test_the_enum_check_covers_the_other_certificate_columns(column: str, tmp_path: Path) -> None:
    """Not just ``certificate_state``: ``_tier_b_stats`` counts outcomes by string equality, so an
    unrecognized outcome silently leaves the resolved count and moves the gate rate."""
    frame = pd.read_csv(FIXTURE_TSV, sep="\t")
    frame.loc[frame.index[0], column] = "nonsense"
    with pytest.raises(ValueError, match="nonsense"):
        audit_dataset("necs", _arm_from(frame, tmp_path))


def test_the_tier_b_sweep_is_referenced_by_a_fixed_committed_name() -> None:
    """Otherwise the Tier-B half of the figure has no reproducible provenance: the pinned suite
    carries no certificate columns, and a timestamped sweep path cannot be cited from a caption."""
    assert TIER_B_SWEEP_FILENAME.endswith(".json")
    assert "tier_b" in TIER_B_SWEEP_FILENAME


def test_markdown_renders_without_restating_a_figure_in_prose(result: dict) -> None:
    text = render_markdown(result)
    assert "Abstention" in text
    assert "unavailable" in text


def test_abstention_counts_uncommitted_rows(tmp_path: Path) -> None:
    """A no-commit row IS an abstention and must reach Panel A.

    The committed-only filter used to run before the state accounting, so uncommitted rows were
    dropped before ``panel_a_abstention`` and ``certificate_state_counts`` ever saw them -- Panel A
    under-reported abstention by exactly the population it exists to count. That was latent only
    because every arm in the current suite is fully committed; PR #47's category validator moves a
    large population to unmapped, so the next suite will not have that property.

    Precision is a separate question: an uncommitted row has no answer to adjudicate, so it must NOT
    enter the Panel B denominator. This pins both halves at once.
    """
    frame = pd.read_csv(FIXTURE_TSV, sep="\t")
    uncommitted = frame.head(3).copy()
    uncommitted["chosen_kg_id"] = None
    uncommitted["kg_equivalent_ids"] = "{}"
    uncommitted["certificate_state"] = "unavailable"
    uncommitted["certificate_structure_status"] = "structure_absent"
    mixed = pd.concat([frame, uncommitted], ignore_index=True)

    arm = tmp_path / "necs"
    arm.mkdir()
    path = arm / "necs_MAPPED_chebi_d_mapped.tsv"
    mixed.to_csv(path, sep="\t", index=False)

    audited = audit_dataset("necs", path)

    assert audited["n_rows"] == len(mixed)
    assert audited["n_rows_with_commit"] == len(frame)
    assert audited["n_rows_uncommitted"] == 3

    panel_a = audited["figure5"]["panel_a_abstention"]
    # The denominator is every row, and all three uncommitted rows are counted as abstentions.
    assert panel_a["n_rows"] == len(mixed)
    baseline = audit_dataset("necs", FIXTURE_TSV)["figure5"]["panel_a_abstention"]
    assert panel_a["n_unavailable"] == baseline["n_unavailable"] + 3
    assert panel_a["abstention_rate"] > baseline["abstention_rate"]

    # ...and none of them leaked into the precision side.
    assert audited["figure5"]["panel_b_precision_coverage"]["n_verifiable"] == (
        audit_dataset("necs", FIXTURE_TSV)["figure5"]["panel_b_precision_coverage"]["n_verifiable"]
    )
    assert audited["certificate_state_counts"]["unavailable"] >= 3


def test_slash_bearing_name_rate_is_emitted_and_splits_by_regime(tmp_path: Path) -> None:
    """The field two shipped docstrings NAME must actually exist, and must separate regimes.

    ``structure_resolver`` and ``tier_b`` both point a reader at ``slash_bearing_name_rate`` to
    justify ``quote(..., safe="")``. A comment naming an artifact field that does not exist is the
    same defect as a comment restating a stale number.

    The regime split is load-bearing for interpretation, not decoration: an arm can carry plenty of
    slashes while its SHORTHAND carries none, and reading the arm-level rate as a shorthand rate
    would misattribute a capability gap to an encoding bug.
    """
    frame = pd.read_csv(FIXTURE_TSV, sep="\t")
    frame["query_source"] = ["abbreviation"] * 4 + ["common_name"] * (len(frame) - 4)
    frame["name"] = ["PG 36:2"] * 4 + ["PC 16:0/18:1"] * (len(frame) - 4)
    arm = tmp_path / "lmsd"
    arm.mkdir()
    path = arm / "lmsd_MAPPED_chebi_d_mapped.tsv"
    frame.to_csv(path, sep="\t", index=False)

    field = audit_dataset("lmsd", path)["slash_bearing_name_rate"]
    assert field["query_name_column"] == "name"
    assert field["n_rows_with_slash"] == len(frame) - 4
    regimes = field["by_name_source_regime"]
    assert regimes["shorthand"]["n_with_slash"] == 0
    assert regimes["common_systematic"]["n_with_slash"] == len(frame) - 4


def test_curve_is_publishable_when_the_gate_is_satisfied(result: dict) -> None:
    """POSITIVE control for ``_curve_publishable``. The other assertions are all negative.

    Without this, any change that makes the gate return False unconditionally leaves the whole suite
    green while permanently suppressing Figure 5 -- and the operator, having run the expensive
    supervised sweep, would get ``false`` with no way to tell a correct refusal from a broken gate.
    A gate that can only ever say no is indistinguishable from a gate that is wired shut.
    """
    figure5 = result["per_dataset"][0]["figure5"]
    assert figure5["curve_publishable"] is True
    assert figure5["curve_not_publishable_reason"] is None
    assert figure5["tier_b"]["resolution_rate"] >= figure5["tier_b"]["min_resolution_rate_floor"]


def test_the_tier_b_gate_uses_the_same_population_as_the_curve_it_gates(result: dict) -> None:
    """The gate rate is over the verifiable rows -- exactly what Panel B plots.

    An all-rows rate answers a different question: on an arm dominated by ``unavailable`` rows, Tier
    B could resolve nearly every row the curve describes and still be refused by a rate dragged down
    by rows the curve never plots. The all-rows figure is still reported, but it does not gate.
    """
    for dataset in result["per_dataset"]:
        tier_b = dataset["figure5"]["tier_b"]
        assert tier_b["n_verifiable"] == dataset["figure5"]["panel_b_precision_coverage"]["n_verifiable"]
        assert "resolution_rate_all_rows" in tier_b, "the all-rows rate must still be reported"
        if tier_b["n_verifiable"]:
            expected = round(tier_b["n_tier_b_resolved_verifiable"] / tier_b["n_verifiable"], 4)
            assert tier_b["resolution_rate"] == expected


# ----------------------------------------------------------------------------------------------
# The oracle-independence control: is Tier B a second measurement, or a restatement of the gold?
# ----------------------------------------------------------------------------------------------
#
# Panel B plots ``gold_block in node_blocks`` against a state that is ``corroborated`` iff
# ``tier_b_block in node_blocks``. Those are the SAME predicate whenever Tier B's block equals the
# gold block, and then the curve's separation is an identity -- precision 1 inside ``corroborated``
# and 0 inside ``contradicted``, by construction, on every row where Tier B resolved and gold
# exists. This is a different circularity than ``independent_of_selection`` (L26) guards: that field
# asks whether the corroborating source also SELECTED the node; this asks whether it is the same
# measurement as the ORACLE.


def _circular_arm(tmp_path: Path) -> Path:
    """A fixture arm where Tier B's answer IS the gold key on every resolved row."""
    frame = pd.read_csv(FIXTURE_TSV, sep="\t")
    gold_block = frame["gold_inchikey"].map(lambda v: str(v).split("-")[0] if isinstance(v, str) else None)
    resolved = frame["certificate_tier_b_outcome"] == "resolved"
    frame["certificate_independent_inchikey_block"] = gold_block.where(resolved, "")
    arm = tmp_path / "necs"
    arm.mkdir(parents=True, exist_ok=True)
    frame.to_csv(arm / "necs_MAPPED_chebi_d_mapped.tsv", sep="\t", index=False)
    return tmp_path


def test_curve_is_refused_when_tier_b_merely_restates_the_gold_key(tmp_path: Path) -> None:
    """POSITIVE control for the oracle-independence gate: it must be able to say no.

    Without this the gate is untested in the direction that matters. The failure it prevents is not
    a crash -- it is a Figure 5 that looks like a perfect stratification and is an identity, which
    is the L21 defect ("a precision that is tautological and means nothing") arriving through a
    channel L21's own sparsity control does not watch.
    """
    figure5 = audit(_circular_arm(tmp_path))["per_dataset"][0]["figure5"]
    control = figure5["oracle_independence_control"]

    assert control["agreement_rate"] == 1.0, "the constructed arm is fully circular by design"
    assert control["n_comparable"] > 0
    assert figure5["curve_publishable"] is False
    assert "same predicate" in figure5["curve_not_publishable_reason"]


def test_curve_survives_when_tier_b_disagrees_with_the_gold_key(result: dict) -> None:
    """NEGATIVE control: a genuinely independent Tier B must NOT be refused.

    Paired with the test above so the gate is pinned in both directions -- a gate that refuses
    everything suppresses Figure 5 just as effectively as one that refuses nothing publishes a
    false one, and the operator cannot tell either apart from a correct verdict.
    """
    figure5 = result["per_dataset"][0]["figure5"]
    control = figure5["oracle_independence_control"]

    assert control["n_comparable"] > 0, "the control must actually have compared something"
    assert control["agreement_rate"] < control["max_agreement_ceiling"]
    assert figure5["curve_publishable"] is True


def test_an_unmeasurable_overlap_does_not_count_as_independence(tmp_path: Path) -> None:
    """A missing comparison is not evidence of independence, so it must not clear the gate.

    The pinned baseline predates the certificate columns entirely. Treating "no rows carried both
    keys" as a pass would let exactly the arms we cannot check publish their curve.
    """
    frame = pd.read_csv(FIXTURE_TSV, sep="\t")
    frame["certificate_independent_inchikey_block"] = ""
    arm = tmp_path / "necs"
    arm.mkdir(parents=True, exist_ok=True)
    frame.to_csv(arm / "necs_MAPPED_chebi_d_mapped.tsv", sep="\t", index=False)

    figure5 = audit(tmp_path)["per_dataset"][0]["figure5"]
    assert figure5["oracle_independence_control"]["agreement_rate"] is None
    assert figure5["curve_publishable"] is False
    assert "not evidence of independence" in figure5["curve_not_publishable_reason"]


def test_an_arm_with_no_gold_key_is_told_the_real_reason(tmp_path: Path) -> None:
    """A gold-free arm cannot have a Panel B at all; saying "Tier B coverage" misdirects.

    ``resolution_rate`` is None both when Tier B reached nothing and when there is no verifiable
    population to reach. Five of the nine arms in the pinned suite are the second case, and an
    operator reading the coverage reason would try to improve Tier B on an arm where no amount of
    coverage can ever produce a curve.
    """
    frame = pd.read_csv(FIXTURE_TSV, sep="\t")
    frame["gold_inchikey"] = ""
    arm = tmp_path / "necs"
    arm.mkdir(parents=True, exist_ok=True)
    frame.to_csv(arm / "necs_MAPPED_chebi_d_mapped.tsv", sep="\t", index=False)

    figure5 = audit(tmp_path)["per_dataset"][0]["figure5"]
    assert figure5["curve_publishable"] is False
    assert "no verifiable population" in figure5["curve_not_publishable_reason"]


def _two_stratum_arm(tmp_path: Path) -> Path:
    """One circular stratum (MW restates the gold) beside one genuinely independent stratum.

    The shape that defeats a POOLED admissibility rate: the independent stratum's disagreement
    drags the pooled figure under the ceiling while the circular stratum's own curve is a pure
    identity. Reachable whenever the Workbench knows a minority of an arm's names -- lipids
    especially, where PubChem picks up the remainder -- and the gold key is RefMet-derived for the
    names it does know.
    """
    rows = []
    for i in range(120):  # circular stratum: tier_b block == gold block on every row
        block = f"MW{i:012d}"
        hit = i % 5 != 0
        rows.append(
            {
                "name": f"mw-{i}",
                "chosen_kg_id": f"CHEBI:9{i:04d}",
                "chosen_kg_id_review": "",
                "kg_equivalent_ids": str(
                    {"INCHIKEY": [f"{block}-UHFFFAOYSA-N"]} if hit else {"INCHIKEY": ["ZZZZZZZZZZZZZZ-UHFFFAOYSA-N"]}
                ),
                "gold_inchikey": f"{block}-UHFFFAOYSA-N",
                "gold_hmdb": "",
                "certificate_state": "corroborated" if hit else "contradicted",
                "certificate_structure_status": "structure_present",
                "certificate_independent_source": "metabolomics-workbench",
                "certificate_tier_b_outcome": "resolved",
                # True on purpose: this arm isolates the ORACLE axis, so it must clear the L26
                # gate and be refused only for restating the gold key.
                "certificate_independent_of_selection": True,
                "certificate_independent_inchikey_block": block,
            }
        )
    for i in range(180):  # independent stratum: tier_b disagrees with gold on most rows
        node = f"PC{i:012d}"
        agrees = i % 4 == 0
        rows.append(
            {
                "name": f"pc-{i}",
                "chosen_kg_id": f"CHEBI:8{i:04d}",
                "chosen_kg_id_review": "",
                "kg_equivalent_ids": str({"INCHIKEY": [f"{node}-UHFFFAOYSA-N"]}),
                "gold_inchikey": f"{node}-UHFFFAOYSA-N" if agrees else f"GOLD{i:010d}-UHFFFAOYSA-N",
                "gold_hmdb": "",
                "certificate_state": "corroborated",
                "certificate_structure_status": "structure_present",
                "certificate_independent_source": "pubchem",
                "certificate_tier_b_outcome": "resolved",
                "certificate_independent_of_selection": True,
                "certificate_independent_inchikey_block": node,
            }
        )
    arm = tmp_path / "necs"
    arm.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(arm / "necs_MAPPED_chebi_d_mapped.tsv", sep="\t", index=False)
    return tmp_path


def test_a_circular_stratum_cannot_hide_behind_an_independent_one(tmp_path: Path) -> None:
    """The admissibility test must hold at the level Panel B is DRAWN at, not just pooled.

    Panel B publishes one curve per source stratum and the module refuses to average them, so a
    pooled agreement rate is the wrong unit: dilution by independent evidence must not buy
    admissibility for a stratum that is a pure identity. The perverse property of the pooled form
    is that the MORE independent evidence an arm carries, the better a circular stratum hides.
    """
    figure5 = audit(_two_stratum_arm(tmp_path))["per_dataset"][0]["figure5"]
    strata = figure5["panel_b_precision_coverage"]["strata"]

    mw = strata["metabolomics-workbench/indep=true"]["oracle_independence_control"]
    pc = strata["pubchem/indep=true"]["oracle_independence_control"]
    assert mw["agreement_rate"] == 1.0, "the MW stratum is circular by construction"
    assert pc["agreement_rate"] < 1.0, "the PubChem stratum must carry real disagreement"

    pooled = figure5["oracle_independence_control"]["agreement_rate"]
    assert pooled <= figure5["oracle_independence_control"]["max_agreement_ceiling"], (
        "the pooled rate must clear the ceiling, or this fixture would be refused for the wrong "
        "reason and would not test the per-stratum path at all"
    )

    assert figure5["curve_publishable"] is False
    assert "metabolomics-workbench/indep=true" in figure5["curve_not_publishable_reason"]
    assert (
        "above the stated ceiling" in figure5["curve_not_publishable_reason"]
    ), "must be refused on the ORACLE axis, not short-circuited by the L26 independence branch"


def test_every_stratum_reports_its_own_independence_control(result: dict) -> None:
    """The control travels with each stratum, so a reader can see how much of a curve is forced."""
    for dataset in result["per_dataset"]:
        for source, stratum in dataset["figure5"]["panel_b_precision_coverage"]["strata"].items():
            assert "oracle_independence_control" in stratum, source


def _dependent_stratum_arm(tmp_path: Path) -> Path:
    """A `metabolomics-workbench` stratum corroborated BY THE REGISTRY THAT SELECTED THE NODE.

    Oracle agreement is deliberately low, so the arm cannot be refused by the oracle gate and this
    fixture tests the L26 axis alone. Measured over the pinned suite, every metabolite arm is mixed
    this way, so the operator's first Tier B sweep produces exactly this shape.
    """
    rows = []
    for i in range(100):  # dependent: MW both selected the node and corroborates it
        node = f"DEP{i:011d}"
        rows.append(
            {
                "name": f"dep-{i}",
                "chosen_kg_id": f"CHEBI:7{i:04d}",
                "chosen_kg_id_review": "",
                "kg_equivalent_ids": str({"INCHIKEY": [f"{node}-UHFFFAOYSA-N"]}),
                # Gold from an unrelated curation, so oracle agreement stays far under the ceiling.
                "gold_inchikey": f"{node}-UHFFFAOYSA-N" if i % 5 else f"OTHER{i:09d}-UHFFFAOYSA-N",
                "gold_hmdb": "",
                "certificate_state": "corroborated",
                "certificate_structure_status": "structure_present",
                "certificate_independent_source": "metabolomics-workbench",
                "certificate_tier_b_outcome": "resolved",
                "certificate_independent_of_selection": False,
                "certificate_independent_inchikey_block": f"MWB{i:011d}",
            }
        )
    for i in range(100):  # independent rows from the SAME source, which must not be pooled in
        node = f"IND{i:011d}"
        rows.append(
            {
                "name": f"ind-{i}",
                "chosen_kg_id": f"CHEBI:6{i:04d}",
                "chosen_kg_id_review": "",
                "kg_equivalent_ids": str({"INCHIKEY": [f"{node}-UHFFFAOYSA-N"]}),
                "gold_inchikey": f"{node}-UHFFFAOYSA-N" if i % 3 else f"ELSE{i:010d}-UHFFFAOYSA-N",
                "gold_hmdb": "",
                "certificate_state": "corroborated",
                "certificate_structure_status": "structure_present",
                "certificate_independent_source": "metabolomics-workbench",
                "certificate_tier_b_outcome": "resolved",
                "certificate_independent_of_selection": True,
                "certificate_independent_inchikey_block": f"MWI{i:011d}",
            }
        )
    arm = tmp_path / "necs"
    arm.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(arm / "necs_MAPPED_chebi_d_mapped.tsv", sep="\t", index=False)
    return tmp_path


def test_a_stratum_corroborated_by_its_own_selector_is_refused(tmp_path: Path) -> None:
    """L26's actual rule: independence is claimed ONLY on the subset where it holds.

    The code named this problem and then did it anyway -- it commented that a mixed stratum is "a
    reason not to average it" and then averaged it, while the gate never read the field. A stratum
    where the corroborating registry also supplied the node is corroborated by construction, which
    is the round-4 defect one axis over.
    """
    figure5 = audit(_dependent_stratum_arm(tmp_path))["per_dataset"][0]["figure5"]
    strata = figure5["panel_b_precision_coverage"]["strata"]

    dependent = strata["metabolomics-workbench/indep=false"]
    assert (
        dependent["oracle_independence_control"]["agreement_rate"] <= ORACLE_INDEPENDENCE_MAX_AGREEMENT
    ), "the oracle gate must NOT be what refuses this arm, or the L26 axis is untested"
    assert figure5["curve_publishable"] is False
    assert "not established as independent of the selection" in figure5["curve_not_publishable_reason"]


def test_a_stratum_with_no_adjudicated_rows_does_not_veto_the_arm(result: dict) -> None:
    """An all-uncorroborated stratum has no verdict to be circular about.

    Without this the `indep=unknown` stratum -- whose independence is legitimately None because
    Tier B never resolved -- would refuse every arm, and the gate would be wired shut.
    """
    figure5 = result["per_dataset"][0]["figure5"]
    strata = figure5["panel_b_precision_coverage"]["strata"]
    unknown = strata["pubchem/indep=unknown"]
    assert unknown["independent_of_selection"] is None
    assert unknown["oracle_independence_control"]["agreement_rate"] is None
    assert figure5["curve_publishable"] is True, "a verdict-free stratum must not veto the arm"


def test_an_adjudicated_stratum_with_no_measurable_overlap_is_refused(tmp_path: Path) -> None:
    """The per-stratum gate must treat an unmeasurable overlap as the pooled gate does.

    Constructed so the POOLED rate is measurable and clears the ceiling -- otherwise the pooled
    gate refuses first and this test passes without ever reaching the per-stratum branch. (It did
    exactly that on the first attempt: deleting the branch left the suite green.)
    """
    rows = []
    for i in range(100):  # measurable stratum, low agreement -> pooled rate stays under the ceiling
        node = f"MEAS{i:010d}"
        rows.append(
            {
                "name": f"meas-{i}",
                "chosen_kg_id": f"CHEBI:5{i:04d}",
                "chosen_kg_id_review": "",
                "kg_equivalent_ids": str({"INCHIKEY": [f"{node}-UHFFFAOYSA-N"]}),
                "gold_inchikey": f"{node}-UHFFFAOYSA-N" if i % 4 else f"XX{i:012d}-UHFFFAOYSA-N",
                "gold_hmdb": "",
                "certificate_state": "corroborated",
                "certificate_structure_status": "structure_present",
                "certificate_independent_source": "pubchem",
                "certificate_tier_b_outcome": "resolved",
                "certificate_independent_of_selection": True,
                "certificate_independent_inchikey_block": node,
            }
        )
    for i in range(40):  # adjudicated, independent, but NO block to compare -> unmeasurable
        node = f"BLIND{i:09d}"
        rows.append(
            {
                "name": f"blind-{i}",
                "chosen_kg_id": f"CHEBI:4{i:04d}",
                "chosen_kg_id_review": "",
                "kg_equivalent_ids": str({"INCHIKEY": [f"{node}-UHFFFAOYSA-N"]}),
                "gold_inchikey": f"{node}-UHFFFAOYSA-N",
                "gold_hmdb": "",
                "certificate_state": "corroborated",
                "certificate_structure_status": "structure_present",
                "certificate_independent_source": "mystery-registry",
                "certificate_tier_b_outcome": "resolved",
                "certificate_independent_of_selection": True,
                "certificate_independent_inchikey_block": "",
            }
        )
    arm = tmp_path / "necs"
    arm.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(arm / "necs_MAPPED_chebi_d_mapped.tsv", sep="\t", index=False)

    figure5 = audit(tmp_path)["per_dataset"][0]["figure5"]
    pooled = figure5["oracle_independence_control"]
    assert (
        pooled["agreement_rate"] is not None and pooled["agreement_rate"] <= ORACLE_INDEPENDENCE_MAX_AGREEMENT
    ), "the pooled gate must NOT be what refuses this arm, or the per-stratum branch is untested"
    blind = figure5["panel_b_precision_coverage"]["strata"]["mystery-registry/indep=true"]
    assert blind["oracle_independence_control"]["agreement_rate"] is None

    assert figure5["curve_publishable"] is False
    assert "mystery-registry/indep=true" in figure5["curve_not_publishable_reason"]
    assert "not evidence of independence" in figure5["curve_not_publishable_reason"]


def test_the_agreement_comparison_case_folds_both_operands(tmp_path: Path) -> None:
    """Normalizing one side only would drive agreement to 0.0 -- which SILENTLY CLEARS the gate.

    `_first_block` case-folds the gold side; the certificate column is read raw. A case mismatch
    would therefore make a perfectly circular arm look maximally independent, which is the worst
    available failure direction.
    """
    frame = pd.read_csv(FIXTURE_TSV, sep="\t")
    frame["certificate_independent_inchikey_block"] = frame["certificate_independent_inchikey_block"].map(
        lambda v: str(v).lower() if isinstance(v, str) and v.strip() else v
    )
    arm = tmp_path / "necs"
    arm.mkdir(parents=True, exist_ok=True)
    frame.to_csv(arm / "necs_MAPPED_chebi_d_mapped.tsv", sep="\t", index=False)

    lowered = audit(tmp_path)["per_dataset"][0]["figure5"]["panel_b_precision_coverage"]["strata"]
    upper = audit(FIXTURE_SUITE)["per_dataset"][0]["figure5"]["panel_b_precision_coverage"]["strata"]
    key = "pubchem/indep=true"
    assert (
        lowered[key]["oracle_independence_control"]["agreement_rate"]
        == upper[key]["oracle_independence_control"]["agreement_rate"]
    ), "case must not change the measured agreement"


def test_the_gold_side_case_fold_is_reached(tmp_path: Path) -> None:
    """`_first_block`'s fold applies to the GOLD column, and no test reached it.

    The round-6 case-fold test lower-cases only `certificate_independent_inchikey_block`, so it
    exercises the independence control's fold and not this one. Dropping `.upper()` from
    `_first_block` left the whole suite green while a lower-case gold file would score every row
    incorrect and report precision 0.0.
    """
    frame = pd.read_csv(FIXTURE_TSV, sep="\t")
    frame["gold_inchikey"] = frame["gold_inchikey"].map(
        lambda v: str(v).lower() if isinstance(v, str) and v.strip() else v
    )
    arm = tmp_path / "necs"
    arm.mkdir(parents=True, exist_ok=True)
    frame.to_csv(arm / "necs_MAPPED_chebi_d_mapped.tsv", sep="\t", index=False)

    lowered = audit(tmp_path)["per_dataset"][0]
    upper = audit(FIXTURE_SUITE)["per_dataset"][0]
    assert lowered["structure_oracle"]["blended_precision"] == upper["structure_oracle"]["blended_precision"]
    assert (
        lowered["structure_oracle"]["blended_precision"] > 0
    ), "a zero here would mean the fold is absent and every row scored incorrect"


def test_a_derived_arm_is_refused_for_the_derivation_not_the_tier_b_floor(tmp_path: Path) -> None:
    """The `not has_certificate` refusal passed only because a LATER gate fired.

    Deleting that branch left the suite green: a derived arm has every `_tier_b_outcome` = 'off',
    so the resolution rate is 0.0 and the floor refuses two checks later. The branch was correct
    but unobserved -- and its message is the reason printed on all nine entries of the committed
    artifact, i.e. the only refusal reason a reader of the .md actually sees.
    """
    frame = pd.read_csv(FIXTURE_TSV, sep="\t")
    frame = frame.drop(columns=[c for c in frame.columns if c.startswith("certificate_")])
    arm = tmp_path / "necs"
    arm.mkdir(parents=True, exist_ok=True)
    frame.to_csv(arm / "necs_MAPPED_chebi_d_mapped.tsv", sep="\t", index=False)

    figure5 = audit(tmp_path)["per_dataset"][0]["figure5"]
    assert figure5["curve_publishable"] is False
    reason = figure5["curve_not_publishable_reason"]
    assert "carries no certificate_* columns" in reason
    assert "resolution rate" not in reason, "must name the derivation, not blame the Tier B floor"
