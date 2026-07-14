"""Tests for the Tier-3 metrics: answer stability, dispersion, bootstrap, variance=0."""

from studies.tier3_determinism import metrics
from studies.tier3_determinism.models import ArmACall, ArmBCall


def _a(query_id: str, repeat: int, parsed: str | None, correct: bool | None) -> ArmACall:
    return ArmACall(
        query_id=query_id,
        model_label="m",
        model_id="m-1",
        provider="openai",
        temperature=0.0,
        top_p=1.0,
        max_tokens=64,
        seed=None,
        repeat_index=repeat,
        raw_text="",
        parsed_curie=parsed,
        is_correct=correct,
    )


def test_distinct_answer_distribution_counts_per_query() -> None:
    calls = [
        _a("A", 0, "X", False),
        _a("A", 1, "X", False),
        _a("A", 2, "Y", True),
        _a("B", 0, "Z", True),
        _a("B", 1, "Z", True),
        _a("B", 2, "Z", True),
    ]
    dist = metrics.distinct_answer_distribution(calls)

    assert dist["A"].n_distinct == 2
    assert dist["A"].answer_counts == {"X": 2, "Y": 1}
    assert dist["A"].majority_answer == "X"
    assert dist["B"].n_distinct == 1  # stable query


def test_unknown_answers_are_their_own_bucket() -> None:
    calls = [_a("A", 0, "X", False), _a("A", 1, None, None), _a("A", 2, None, None)]
    dist = metrics.distinct_answer_distribution(calls)

    assert dist["A"].n_distinct == 2
    assert dist["A"].answer_counts["unknown"] == 2


def test_accuracy_per_run_groups_by_repeat_index() -> None:
    # run 0: A correct, B wrong -> 0.5 ; run 1: both correct -> 1.0
    calls = [
        _a("A", 0, "ok", True),
        _a("B", 0, "no", False),
        _a("A", 1, "ok", True),
        _a("B", 1, "ok", True),
    ]
    accs = metrics.accuracy_per_run(calls)
    assert accs == [0.5, 1.0]


def test_dispersion_reports_mean_sd_min_max() -> None:
    disp = metrics.dispersion([0.2, 0.4, 0.6])
    assert abs(disp.mean - 0.4) < 1e-9
    assert disp.min == 0.2 and disp.max == 0.6
    assert disp.sd > 0  # spread is the point


def test_bootstrap_ci_is_seeded_and_bounded() -> None:
    values = [0.1, 0.3, 0.5, 0.7, 0.9]
    lo1, hi1 = metrics.bootstrap_ci(values, n_boot=500, seed=42)
    lo2, hi2 = metrics.bootstrap_ci(values, n_boot=500, seed=42)
    assert (lo1, hi1) == (lo2, hi2)  # deterministic
    assert 0.0 <= lo1 <= hi1 <= 1.0
    assert lo1 <= sum(values) / len(values) <= hi1


def test_byte_identical_true_only_when_all_repeats_agree() -> None:
    stable = [
        ArmBCall(query_id="A", repeat_index=0, chosen_kg_id="CHEBI:1", is_correct=True),
        ArmBCall(query_id="A", repeat_index=1, chosen_kg_id="CHEBI:1", is_correct=True),
    ]
    assert metrics.is_byte_identical(stable) is True

    wobbly = stable + [ArmBCall(query_id="A", repeat_index=2, chosen_kg_id="CHEBI:9", is_correct=False)]
    assert metrics.is_byte_identical(wobbly) is False


def test_contrast_reports_worst_best_gap_vs_biomapper() -> None:
    c = metrics.contrast(arm_a_accuracies=[0.4, 0.9, 0.6], arm_b_accuracy=1.0)
    assert c.arm_a_worst == 0.4
    assert c.arm_a_best == 0.9
    assert abs(c.arm_a_spread - 0.5) < 1e-9
    assert abs(c.gap_worst_vs_biomapper - 0.6) < 1e-9
