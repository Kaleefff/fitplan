"""The next training session of the active plan (api-rules.md "Plans": GET /sessions/next).

Each session recurs on its weekday from the plan's start to its end date; the next date
is today or later, skipping dates on which that session already has a workout; the
earliest date wins, ties by session order.
"""

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class ScheduledSession:
    id: int
    session_order: int
    day_of_week: int  # 1 = Monday (ISO)


def next_session(
    sessions: list[ScheduledSession],
    start: date,
    end: date,
    today: date,
    done: set[tuple[int, date]],
) -> tuple[ScheduledSession, date] | None:
    """`done` holds (session id, date) of the workouts already logged."""
    first_day = max(start, today)
    candidates = []
    for session in sessions:
        day = first_day + timedelta(days=(session.day_of_week - first_day.isoweekday()) % 7)
        while (session.id, day) in done:
            day += timedelta(days=7)
        if day <= end:
            candidates.append((day, session.session_order, session))
    if not candidates:
        return None
    day, _, session = min(candidates, key=lambda c: (c[0], c[1]))
    return session, day
