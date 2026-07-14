"""Tests for Fig-4 assembly (distinct-answer distribution + dispersion band)."""

from studies.tier3_determinism import fig4
from studies.tier3_determinism.models import ArmACall, ArmBCall


def _a(
    query_id: str,
    temp: float | None,
    repeat: int,
    parsed: str | None,
    correct: bool | None,
    model_label: str = "opus",
    provider: str = "anthropic",
) -> ArmACall:
    return ArmACall(
        query_id=query_id,
        model_label=model_label,
        model_id="claude-x",
        provider=provider,
        temperature=temp,
        top_p=1.0,
        max_tokens=64,
        seed=None,
        repeat_index=repeat,
        raw_text="",
        parsed_curie=parsed,
        is_correct=correct,
    )


def _build():
    # query A: unstable (X,X,Y); query B: stable (Z,Z,Z). temp 0.0 only.
    arm_a = [
        _a("A", 0.0, 0, "X", True),
        _a("A", 0.0, 1, "X", True),
        _a("A", 0.0, 2, "Y", False),
        _a("B", 0.0, 0, "Z", True),
        _a("B", 0.0, 1, "Z", True),
        _a("B", 0.0, 2, "Z", True),
    ]
    arm_b = [
        ArmBCall(query_id="A", repeat_index=0, chosen_kg_id="X", is_correct=True),
        ArmBCall(query_id="A", repeat_index=1, chosen_kg_id="X", is_correct=True),
        ArmBCall(query_id="B", repeat_index=0, chosen_kg_id="Z", is_correct=True),
        ArmBCall(query_id="B", repeat_index=1, chosen_kg_id="Z", is_correct=True),
    ]
    return fig4.build_fig4(arm_a, arm_b)


def test_arm_a_panel_has_distinct_histogram_and_dispersion() -> None:
    data = _build()
    assert len(data.arm_a) == 1
    panel = data.arm_a[0]
    assert panel.model_label == "opus" and panel.temperature == 0.0
    # 1 query with 2 distinct answers, 1 query with 1 distinct -> {1: 1, 2: 1}
    assert panel.distinct_count_histogram == {1: 1, 2: 1}
    assert panel.dispersion.n_runs == 3  # 3 repeats -> 3 runs
    assert panel.dispersion.min <= panel.dispersion.max


def test_biomapper_panel_is_flat_and_byte_identical() -> None:
    data = _build()
    assert data.biomapper.byte_identical is True
    assert set(data.biomapper.per_query_distinct.values()) == {1}  # every query flat at 1
    assert data.biomapper.accuracy == 1.0


def test_contrast_present_when_gold_exists() -> None:
    data = _build()
    assert data.arm_a[0].contrast is not None
    assert data.arm_a[0].contrast.biomapper_accuracy == 1.0


def test_fig4_is_json_serializable() -> None:
    data = _build()
    dumped = data.model_dump(mode="json")
    assert "arm_a" in dumped and "biomapper" in dumped
    # int histogram keys survive as JSON string keys
    assert dumped["arm_a"][0]["distinct_count_histogram"]


def test_native_temperature_panel_labeled_none_not_zero() -> None:
    """A temperature-unsupported model's calls (temperature=None) form a native panel
    whose temperature is None -- never coerced into a 0.0 bucket."""
    arm_a = [
        _a("A", None, 0, "X", True),
        _a("A", None, 1, "X", True),
        _a("B", None, 0, "Z", True),
    ]
    data = fig4.build_fig4(arm_a, [])
    assert len(data.arm_a) == 1
    assert data.arm_a[0].temperature is None  # native, not 0.0


def test_mixed_native_and_numeric_temps_sort_without_error() -> None:
    """Grouping/sorting must handle a None (native) panel alongside numeric-temp panels
    for another model -- a plain sorted() over (label, temp) would raise on None vs float."""
    arm_a = [
        _a("A", None, 0, "X", True, model_label="opus-4.8"),  # native
        _a("A", 0.0, 0, "X", True, model_label="gpt-4o", provider="openai"),
        _a("A", 0.7, 0, "Y", False, model_label="gpt-4o", provider="openai"),
    ]
    data = fig4.build_fig4(arm_a, [])  # must not raise
    temps = {(p.model_label, p.temperature) for p in data.arm_a}
    assert ("opus-4.8", None) in temps
    assert ("gpt-4o", 0.0) in temps and ("gpt-4o", 0.7) in temps


def test_absent_arm_b_is_not_reported_as_byte_identical() -> None:
    """Arm B skipped (--no-arm-b) must NOT claim determinism for an arm that never ran."""
    arm_a = [_a("A", 0.0, 0, "X", True)]
    data = fig4.build_fig4(arm_a, [])
    # No BioMapper calls were compared -> determinism is unknown, not vacuously True.
    assert data.biomapper.byte_identical is None
    assert data.biomapper.n_queries == 0
