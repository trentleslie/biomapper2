"""Shared gold-structure predicate (Unit 7), with the positive control that pins the prior bug."""

from __future__ import annotations

from studies.external_benchmarks.scorers.gold_structure import has_gold_structure

_LEGACY_2BLOCK = "ATHGHQPFGPMSJY-UHFFFAOYAK"
_STANDARD_3BLOCK = "ATHGHQPFGPMSJY-UHFFFAOYSA-N"


def test_accepts_both_vintage_forms():
    assert has_gold_structure(_LEGACY_2BLOCK) is True
    assert has_gold_structure(_STANDARD_3BLOCK) is True


def test_rejects_corrupt_and_blank():
    assert has_gold_structure("4000") is False
    assert has_gold_structure("") is False
    assert has_gold_structure(None) is False
    assert has_gold_structure("NOTAKEY") is False


def test_positive_control_old_predicate_would_reject_three_block():
    """The prior predicate (two-block only) is detectably degenerate on repaired (three-block) keys.
    This is the bug Unit 7 fixes: assert the OLD logic rejects what the new one accepts, so a
    regression to the old form cannot pass silently."""
    def _old_predicate(v: str) -> bool:  # the recovered scripts' original necs_has_structure
        parts = (v or "").strip().split("-")
        return len(parts) == 2 and len(parts[0]) == 14

    assert _old_predicate(_STANDARD_3BLOCK) is False  # old rejects repaired keys...
    assert has_gold_structure(_STANDARD_3BLOCK) is True  # ...new accepts them
