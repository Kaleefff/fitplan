"""GET /sessions/next date rule (api-rules.md "Plans")."""

from datetime import date

from app.domain.schedule import ScheduledSession, next_session

MON, WED, FRI = (ScheduledSession(i, i, d) for i, d in ((1, 1), (2, 3), (3, 5)))
START, END = date(2026, 11, 2), date(2026, 12, 28)  # Monday, plan of 56 days


def test_today_counts_and_the_earliest_session_wins():
    assert next_session([MON, WED, FRI], START, END, date(2026, 11, 4), set()) == (
        WED,
        date(2026, 11, 4),
    )
    assert next_session([MON, WED, FRI], START, END, date(2026, 11, 5), set()) == (
        FRI,
        date(2026, 11, 6),
    )


def test_before_the_start_the_first_session_of_the_plan():
    assert next_session([WED, MON], START, END, date(2026, 10, 30), set()) == (
        MON,
        date(2026, 11, 2),
    )


def test_a_done_session_moves_to_its_next_week():
    done = {(WED.id, date(2026, 11, 4))}
    assert next_session([WED], START, END, date(2026, 11, 4), done) == (WED, date(2026, 11, 11))
    # with another session the same week, that one is earlier
    assert next_session([WED, FRI], START, END, date(2026, 11, 4), done)[0] == FRI


def test_ties_go_to_the_lower_session_order():
    a, b = ScheduledSession(7, 2, 3), ScheduledSession(8, 1, 3)
    assert next_session([a, b], START, END, START, set())[0] == b


def test_nothing_after_the_end_date():
    assert next_session([MON], START, END, date(2026, 12, 29), set()) is None
    assert next_session([MON], START, END, END, {(MON.id, END)}) is None
