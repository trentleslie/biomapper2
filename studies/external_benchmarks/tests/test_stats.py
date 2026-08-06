"""Interval and paired-test primitives (offline, seed-free, no I/O).

These tests exist because the benchmark suite reported point estimates with no interval and no
significance test anywhere, while the manuscript's methods section promises both. The failure mode
that motivated each test is named in its docstring, because a statistics helper that is merely
"green" is not evidence of anything -- a suite that only ever asserts non-significance cannot
distinguish a working test from one that returns the same answer regardless of input.

Nothing here touches the network. Every expected value is either an exact arithmetic identity or a
value published in the source literature, quoted from the reference rather than from a prior run of
this code.
"""

from __future__ import annotations

import math

import pytest

from studies.external_benchmarks.stats import (
    DEGENERATE_MCNEMAR_P,
    PairingError,
    assert_paired,
    discordance,
    mcnemar,
    newcombe_difference,
    newcombe_paired_mover,
    tango_paired_difference,
    wilson_interval,
)


# --------------------------------------------------------------------------------------------
# Wilson
# --------------------------------------------------------------------------------------------
class TestWilsonInterval:
    """Wilson checked at the boundaries, where the normal approximation it replaces breaks."""

    def test_boundary_k_zero_stays_inside_unit_interval(self):
        """Wald would emit a zero-width interval at k=0; Wilson must not, and must not go negative."""
        lo, hi = wilson_interval(0, 20)
        assert lo == 0.0
        assert 0.0 < hi < 1.0

    def test_boundary_k_equals_n_stays_inside_unit_interval(self):
        lo, hi = wilson_interval(20, 20)
        assert hi == 1.0
        assert 0.0 < lo < 1.0

    def test_matches_published_reference_value(self):
        """Newcombe's published worked example, quoted from the paper rather than from this code."""
        lo, hi = wilson_interval(81, 263)
        assert lo == pytest.approx(0.2553, abs=5e-4)
        assert hi == pytest.approx(0.3662, abs=5e-4)

    def test_small_n_interval_is_wide(self):
        """A tiny denominator must produce a visibly wide interval, not a falsely precise one."""
        lo, hi = wilson_interval(1, 3)
        assert hi - lo > 0.5

    def test_interval_contains_point_estimate(self):
        for k, n in ((255, 1500), (189, 451), (66, 1049), (1319, 1500), (411, 983)):
            lo, hi = wilson_interval(k, n)
            assert lo <= k / n <= hi

    def test_zero_denominator_is_undefined_not_a_crash(self):
        lo, hi = wilson_interval(0, 0)
        assert lo is None and hi is None

    def test_rejects_k_above_n(self):
        with pytest.raises(ValueError):
            wilson_interval(5, 4)

    def test_z_is_recorded_by_the_caller_not_hidden(self):
        """A wider z must widen the interval; the parameter is real, not decorative."""
        lo95, hi95 = wilson_interval(255, 1500, z=1.959963984540054)
        lo99, hi99 = wilson_interval(255, 1500, z=2.5758293035489004)
        assert (hi99 - lo99) > (hi95 - lo95)


# --------------------------------------------------------------------------------------------
# McNemar
# --------------------------------------------------------------------------------------------
class TestMcNemar:
    def test_positive_control_returns_significant_on_a_real_difference(self):
        """THE load-bearing test.

        A suite that only asserts non-significance cannot tell a working test from a broken one.
        b=28, c=0 is the shape of the observed strict-vs-equivalence-set contrast: an all-one-way
        discordance that must come back overwhelmingly significant.
        """
        res = mcnemar(28, 0)
        assert res["p_exact"] < 1e-6
        assert res["p_midp"] < 1e-6
        assert res["b"] == 28 and res["c"] == 0

    def test_identity_arms_give_zero_discordance(self):
        """Arithmetic identity: x vs x has b=c=0. This tests only that, and is labelled as such.

        It is NOT the A-A null -- an empirical A-A calibration needs two independent live runs of
        unchanged code, which is gated and deliberately not attempted here.
        """
        arm = [True, False, True, True, False]
        b, c = discordance(arm, arm)
        assert (b, c) == (0, 0)

    def test_degenerate_zero_discordance_returns_the_documented_sentinel(self):
        """b + c == 0: the test statistic is undefined. Documented return, never a silent 1.0."""
        res = mcnemar(0, 0)
        assert res["degenerate"] is True
        assert res["p_exact"] == DEGENERATE_MCNEMAR_P
        assert res["p_midp"] == DEGENERATE_MCNEMAR_P
        assert "undefined" in res["note"].lower()

    def test_exact_binomial_is_symmetric_in_b_and_c(self):
        assert mcnemar(3, 9)["p_exact"] == pytest.approx(mcnemar(9, 3)["p_exact"])

    def test_midp_is_never_more_conservative_than_exact(self):
        for b, c in ((1, 0), (3, 9), (10, 4), (28, 0)):
            res = mcnemar(b, c)
            assert res["p_midp"] <= res["p_exact"] + 1e-12

    def test_known_two_sided_exact_value(self):
        """b=1, c=0: the exact two-sided sign test on one discordant pair is p = 1.0."""
        assert mcnemar(1, 0)["p_exact"] == pytest.approx(1.0)
        assert mcnemar(2, 0)["p_exact"] == pytest.approx(0.5)
        assert mcnemar(3, 0)["p_exact"] == pytest.approx(0.25)

    def test_rejects_negative_counts(self):
        with pytest.raises(ValueError):
            mcnemar(-1, 3)


# --------------------------------------------------------------------------------------------
# Paired difference intervals
# --------------------------------------------------------------------------------------------
class TestPairedDifferenceIntervals:
    def test_coherent_with_mcnemar_on_the_all_one_way_case(self):
        """The reason these replaced the bootstrap.

        A bootstrap CI spanning zero printed next to a McNemar p of order 1e-9 is a self-
        contradiction a reviewer will find. On b=28, c=0 the paired interval must exclude zero.
        """
        res = tango_paired_difference(b=28, c=0, n=1500)
        assert res["lower"] > 0.0
        assert mcnemar(28, 0)["p_exact"] < 1e-6

    def test_defined_at_zero_discordance(self):
        """b + c == 0 is where a bootstrap degenerates; the closed form must still return."""
        res = tango_paired_difference(b=0, c=0, n=1500)
        assert res["estimate"] == 0.0
        assert res["lower"] <= 0.0 <= res["upper"]
        assert res["degenerate"] is True

    def test_seed_free_and_deterministic(self):
        """No resampling anywhere: identical inputs give bit-identical output, run to run."""
        a = tango_paired_difference(b=28, c=0, n=1500)
        b = tango_paired_difference(b=28, c=0, n=1500)
        assert a == b

    def test_estimate_is_the_paired_difference(self):
        res = tango_paired_difference(b=40, c=10, n=1000)
        assert res["estimate"] == pytest.approx((40 - 10) / 1000)

    def test_sign_flips_with_the_arms(self):
        fwd = tango_paired_difference(b=40, c=10, n=1000)
        rev = tango_paired_difference(b=10, c=40, n=1000)
        assert fwd["estimate"] == pytest.approx(-rev["estimate"])
        assert fwd["lower"] == pytest.approx(-rev["upper"])
        assert fwd["upper"] == pytest.approx(-rev["lower"])

    def test_mover_agrees_with_tango_in_sign_and_brackets_the_estimate(self):
        """Both closed forms must agree on the same paired contrast; only their width may differ."""
        t = tango_paired_difference(b=28, c=0, n=1500)
        m = newcombe_paired_mover(k1=1347, k2=1319, b=28, c=0, n=1500)
        assert m["lower"] <= m["estimate"] <= m["upper"]
        assert m["lower"] > 0.0
        assert m["estimate"] == pytest.approx(t["estimate"])

    def test_mover_rejects_arms_inconsistent_with_the_discordance(self):
        """``k1 - k2`` must equal ``b - c``; anything else means the arms are not the same rows."""
        with pytest.raises(ValueError):
            newcombe_paired_mover(k1=1347, k2=1319, b=5, c=0, n=1500)

    def test_interval_narrows_as_n_grows(self):
        small = tango_paired_difference(b=8, c=2, n=100)
        large = tango_paired_difference(b=80, c=20, n=1000)
        assert (large["upper"] - large["lower"]) < (small["upper"] - small["lower"])

    def test_rejects_discordance_exceeding_n(self):
        with pytest.raises(ValueError):
            tango_paired_difference(b=900, c=900, n=1000)


class TestNewcombeUnpaired:
    def test_unpaired_interval_is_flagged_unpaired(self):
        res = newcombe_difference(527, 1000, 409, 1000)
        assert res["paired"] is False
        assert res["lower"] < res["estimate"] < res["upper"]

    def test_precondition_note_is_carried_in_the_result(self):
        """The unpaired form is only licensed under stated preconditions; it must carry them."""
        res = newcombe_difference(527, 1000, 409, 1000)
        assert res["preconditions"]

    def test_zero_denominator_is_undefined(self):
        res = newcombe_difference(0, 0, 1, 10)
        assert res["lower"] is None and res["upper"] is None


# --------------------------------------------------------------------------------------------
# Pairing guards -- the mutation check lives here
# --------------------------------------------------------------------------------------------
class TestPairingGuards:
    def test_raises_on_length_mismatch(self):
        with pytest.raises(PairingError):
            assert_paired(["a", "b"], ["a"], [True, False], [True])

    def test_raises_on_misaligned_row_ids(self):
        """Row identity, not position, defines the pairing."""
        with pytest.raises(PairingError):
            assert_paired(["a", "b"], ["b", "a"], [True, False], [True, False])

    def test_raises_on_duplicate_row_ids(self):
        """A join on query NAME manufactures flips wherever a name repeats.

        Equal length and equal ordering are both satisfied here; only a uniqueness assertion
        catches it. This is the mutation check's target: delete the uniqueness assertion from
        ``assert_paired`` and this test must go red.
        """
        with pytest.raises(PairingError, match="unique"):
            assert_paired(["a", "a"], ["a", "a"], [True, False], [False, True])

    def test_accepts_a_well_formed_pairing(self):
        assert_paired(["a", "b", "c"], ["a", "b", "c"], [True, False, True], [True, True, True])

    def test_discordance_requires_pairing(self):
        with pytest.raises(PairingError):
            discordance([True, False, True], [True, False])

    def test_discordance_counts_both_directions_separately(self):
        """b and c must never be collapsed into one number.

        Two nearly-equal opposing flip counts net out to a negligible accuracy delta while the
        instrument is in fact unstable on their *sum* of rows. Only the split reports the second
        fact, which is the one that matters for a determinism claim.
        """
        arm_a = [True, True, False, False]
        arm_b = [True, False, True, False]
        b, c = discordance(arm_a, arm_b)
        assert (b, c) == (1, 1)

    def test_paired_from_rows_uses_row_ids_not_position(self):
        """The mutation check, expressed as behaviour rather than as a note.

        These two arms are constructed so that id-keyed and positional pairing give *different*
        answers. Delete the id alignment and the function falls back to position, which reports no
        discordance at all -- so this test dies. If it ever passes under positional pairing, the
        pairing is untested.
        """
        from studies.external_benchmarks.stats import paired_counts_from_rows

        rows_a = [{"id": "x", "correct": True}, {"id": "y", "correct": False}]
        rows_b = [{"id": "y", "correct": True}, {"id": "x", "correct": False}]
        res = paired_counts_from_rows(rows_a, rows_b, id_key="id", flag_key="correct")
        assert res["n"] == 2
        # id-keyed truth: x moves correct->wrong, y moves wrong->correct.
        assert (res["b"], res["c"]) == (1, 1)
        # Positional pairing would pair x with y and see no movement at all.
        positional = discordance([r["correct"] for r in rows_a], [r["correct"] for r in rows_b])
        assert positional == (0, 0)

    def test_paired_from_rows_raises_on_duplicate_ids(self):
        from studies.external_benchmarks.stats import paired_counts_from_rows

        rows = [{"id": "x", "correct": True}, {"id": "x", "correct": False}]
        with pytest.raises(PairingError):
            paired_counts_from_rows(rows, rows, id_key="id", flag_key="correct")


class TestNoHiddenRandomness:
    def test_module_exposes_no_seed_or_resample_parameters(self):
        """The bootstrap was dropped along with ``seed`` and ``n_resamples``.

        It is retained only if a genuinely non-analytic target statistic is named, and none is. If
        one is added later, this test is the place that forces the header to record the parameters.
        """
        import inspect

        from studies.external_benchmarks import stats as mod

        for name, fn in vars(mod).items():
            if name.startswith("_") or not callable(fn) or not inspect.isfunction(fn):
                continue
            params = set(inspect.signature(fn).parameters)
            assert "seed" not in params, f"{name} takes a seed; statistics here are seed-free"
            assert "n_resamples" not in params, f"{name} resamples; the closed forms are the default"


class TestMathematicalSanity:
    def test_wilson_half_width_scales_as_inverse_root_n(self):
        """Half-width must shrink roughly as 1/sqrt(n).

        A table showing otherwise is arithmetic error, which is precisely how the briefed
        regime-rate-with-suite-denominator pairing went wrong: a regime rate was printed against
        the whole dataset's denominator, and the published half-width would have been off by
        about a factor of two.
        """
        lo1, hi1 = wilson_interval(170, 1000)
        lo2, hi2 = wilson_interval(680, 4000)
        ratio = (hi1 - lo1) / (hi2 - lo2)
        assert ratio == pytest.approx(2.0, rel=0.05)

    def test_the_two_lmsd_regimes_have_visibly_different_half_widths(self):
        """The corrected pairing.

        A dataset's overall rate and its ``common_systematic`` regime rate are different rows with
        different denominators and therefore different precision. Carrying one as the other is off
        by roughly a factor of two on half-width, which is why the report emits regime rows
        separately rather than one blended row.
        """
        overall = wilson_interval(255, 1500)
        systematic = wilson_interval(189, 451)
        hw_overall = (overall[1] - overall[0]) / 2
        hw_systematic = (systematic[1] - systematic[0]) / 2
        assert hw_systematic > 2 * hw_overall

    def test_no_nan_anywhere_on_the_lattice(self):
        for n in (1, 7, 100, 1500):
            for k in (0, 1, n // 2, n):
                lo, hi = wilson_interval(k, n)
                assert not math.isnan(lo) and not math.isnan(hi)
