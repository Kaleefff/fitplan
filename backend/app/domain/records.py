"""Personal records with estimated one-rep max (algorithms.md 6.5)."""

from decimal import Decimal

from app.domain.adaptation import LoggedSet
from app.domain.constants import PR_MAX_REPS


def e1rm(weight_kg: Decimal, reps: int) -> Decimal:
    """Epley; a single rep is the weight itself. Unrounded."""
    if reps == 1:
        return weight_kg
    # weight * (1 + reps/30), dividing last so that 60 kg x 10 is exactly 80
    return weight_kg * (30 + reps) / Decimal(30)


def _counts(s: LoggedSet) -> bool:
    return s.completed and s.weight_kg > 0 and 1 <= s.reps <= PR_MAX_REPS


def best_set(sets: list[LoggedSet]) -> LoggedSet | None:
    """The eligible set with the highest e1RM (the first one on a tie)."""
    eligible = [s for s in sets if _counts(s)]
    if not eligible:
        return None
    return max(eligible, key=lambda s: e1rm(s.weight_kg, s.reps))


def new_personal_record(
    sets: list[LoggedSet], current: tuple[Decimal, int] | None
) -> LoggedSet | None:
    """The set that beats the current record `(weight_kg, reps)`, or None."""
    candidate = best_set(sets)
    if candidate is None:
        return None
    if current is not None and e1rm(candidate.weight_kg, candidate.reps) <= e1rm(*current):
        return None
    return candidate
