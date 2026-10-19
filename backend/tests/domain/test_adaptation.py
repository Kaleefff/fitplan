"""Test vectors A-J of algorithms.md section 6 (FR-A4, FR-A5); planned 3 sets x 10 reps."""

from decimal import Decimal as D

from app.domain.adaptation import (
    Adjustment,
    AdjustmentReason,
    LoggedSet,
    PlannedExercise,
    adapt,
)
from app.domain.constants import BodyRegion


def planned(weight=None, region=BodyRegion.UPPER, bodyweight=False, sets=3, reps=10):
    w = None if weight is None else D(weight)
    return PlannedExercise(
        sets=sets, reps=reps, weight_kg=w, is_bodyweight=bodyweight, region=region
    )


def done(weight="0", reps=10, completed=True, rpe=None):
    return LoggedSet(reps=reps, weight_kg=D(weight), completed=completed, rpe=rpe)


def test_a_upper_progression():
    result = adapt(planned("60"), [done("60")] * 3, overall_rpe=6)
    assert result == Adjustment(AdjustmentReason.PROGRESSION, 3, 10, D("62.5"))


def test_b_lower_progression():
    result = adapt(planned("100", BodyRegion.LOWER), [done("100")] * 3, overall_rpe=7)
    assert result == Adjustment(AdjustmentReason.PROGRESSION, 3, 10, D("105"))


def test_c_high_rpe_reduces_load():
    result = adapt(planned("60"), [done("60")] * 3, overall_rpe=9)
    assert result == Adjustment(AdjustmentReason.REDUCE_HIGH_RPE, 3, 10, D("55"))


def test_d_incomplete_set_reduces_load():
    sets = [done("60"), done("60"), done("60", reps=6, completed=False)]
    result = adapt(planned("60"), sets, overall_rpe=8)
    assert result == Adjustment(AdjustmentReason.REDUCE_INCOMPLETE_SET, 3, 10, D("55"))


def test_e_rpe_8_changes_nothing():
    assert adapt(planned("60"), [done("60")] * 3, overall_rpe=8) is None


def test_f_no_rpe_changes_nothing():
    assert adapt(planned("60"), [done("60")] * 3, overall_rpe=None) is None


def test_g_baseline_from_first_log():
    sets = [done("40"), done("42.5"), done("42.5")]
    result = adapt(planned(None), sets, overall_rpe=None)
    assert result == Adjustment(AdjustmentReason.BASELINE, 3, 10, D("42.5"))


def test_h_bodyweight_progression_adds_a_rep():
    result = adapt(planned(bodyweight=True), [done()] * 3, overall_rpe=6)
    assert result == Adjustment(AdjustmentReason.PROGRESSION, 3, 11, None)


def test_i_bodyweight_high_rpe_removes_a_set():
    result = adapt(planned(bodyweight=True), [done()] * 3, overall_rpe=9)
    assert result == Adjustment(AdjustmentReason.REDUCE_HIGH_RPE, 2, 10, None)


def test_j_one_rep_short_changes_nothing():
    sets = [done("60"), done("60"), done("60", reps=9)]
    assert adapt(planned("60"), sets, overall_rpe=6) is None


# --- rules around the vectors ------------------------------------------------


def test_set_rpe_wins_over_overall_rpe():
    sets = [done("60", rpe=6), done("60", rpe=8), done("60", rpe=7)]
    assert adapt(planned("60"), sets, overall_rpe=5) is None


def test_baseline_with_reduce_signal_takes_90_percent():
    sets = [done("50"), done("50"), done("50", reps=5, completed=False)]
    result = adapt(planned(None), sets, overall_rpe=None)
    # 50 * 0.9 = 45
    assert result == Adjustment(AdjustmentReason.BASELINE, 3, 10, D("45"))


def test_reduction_is_at_least_one_step():
    # 20 * 0.9 = 18 -> 17.5 by rounding; 20 - 2.5 = 17.5
    result = adapt(planned("20"), [done("20")] * 3, overall_rpe=10)
    assert result.weight_kg == D("17.5")
    # 10 * 0.9 = 9 -> 10 by rounding, so the 2.5 kg step wins: 7.5
    result = adapt(planned("10"), [done("10")] * 3, overall_rpe=10)
    assert result.weight_kg == D("7.5")


def test_bodyweight_reduction_stops_at_two_sets():
    assert adapt(planned(bodyweight=True, sets=2), [done()] * 2, overall_rpe=9) is None


def test_bodyweight_reps_capped_at_20():
    assert adapt(planned(bodyweight=True, reps=20), [done(reps=20)] * 3, overall_rpe=5) is None


def test_progression_uses_lowest_completed_weight():
    sets = [done("60"), done("62.5"), done("57.5")]
    # 57.5 + 2.5 = 60 equals the plan: no change
    assert adapt(planned("60"), sets, overall_rpe=6) is None
    assert adapt(planned("57.5"), sets, overall_rpe=6).weight_kg == D("60")


def test_core_uses_upper_step():
    result = adapt(planned("20", BodyRegion.CORE), [done("20")] * 3, overall_rpe=6)
    assert result.weight_kg == D("22.5")


def test_fewer_sets_than_planned_is_no_reserve():
    assert adapt(planned("60"), [done("60")] * 2, overall_rpe=6) is None
