"""Personal records and e1RM (algorithms.md section 6)."""

from decimal import Decimal as D

from app.domain.adaptation import LoggedSet
from app.domain.records import e1rm, new_personal_record
from app.domain.rounding import round_half_up


def s(weight, reps, completed=True):
    return LoggedSet(reps=reps, weight_kg=D(weight), completed=completed)


def test_e1rm_vectors():
    assert e1rm(D("100"), 1) == D("100")
    assert round_half_up(e1rm(D("100"), 5), 2) == D("116.67")
    assert e1rm(D("60"), 10) == D("80.0")


def test_first_record_is_the_best_eligible_set():
    sets = [s("60", 10), s("70", 5), s("80", 13), s("100", 3, completed=False), s("0", 12)]
    # 60x10 = 80.0, 70x5 = 81.67; 13 reps, incomplete and 0 kg do not count
    assert new_personal_record(sets, current=None) == s("70", 5)


def test_record_must_beat_current_e1rm():
    sets = [s("60", 10)]  # 80.0
    assert new_personal_record(sets, current=(D("80"), 1)) is None
    assert new_personal_record(sets, current=(D("75"), 1)) == s("60", 10)


def test_no_eligible_set_gives_no_record():
    assert new_personal_record([s("60", 15)], current=None) is None
