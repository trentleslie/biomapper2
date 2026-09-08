"""structure_but_unlinked requires BOTH sides to carry a structure block (Greptile #66)."""

from __future__ import annotations

from studies.external_benchmarks.monti_biomapper_three_groups import _both_sides_have_structure


def test_both_sides_needed():
    assert _both_sides_have_structure("AAAA", True) is True           # both -> adjudicable
    assert _both_sides_have_structure("AAAA", False) is False         # NECS only -> not adjudicable
    assert _both_sides_have_structure(None, True) is False            # partner only -> not adjudicable
    assert _both_sides_have_structure(None, False) is False           # neither
