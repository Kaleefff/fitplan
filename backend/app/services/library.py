"""Exercise library and alternatives (B-08; FR-P8, FR-A1).

Lists and details come from DB-06's library queries. Alternatives follow
algorithms.md 4.9: eligible exercises (4.2, 4.3) with the same primary group, not
the current one and not already in the session. With a session exercise the plan's
level and equipment snapshot applies (the same check as the swap of B-13); without
one the profile, and without a profile no level or equipment limit. The user's
active injuries always apply.
"""

from collections.abc import Collection
from typing import Protocol

from app.core.errors import AppError, ErrorCode
from app.db.enums import DifficultyLevel as DbLevel
from app.db.enums import EquipmentType
from app.db.repositories.library import ExerciseRow, Page
from app.services.training_plans import TrainingPlanUnitOfWork


class LibraryReader(Protocol):
    async def list_exercises(
        self,
        *,
        q: str | None = None,
        muscle_group_id: int | None = None,
        difficulty_level: DbLevel | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Page[ExerciseRow]: ...

    async def get_exercise(self, exercise_id: int) -> ExerciseRow | None: ...

    async def eligible_exercises(
        self,
        user_id: int,
        *,
        level: DbLevel | None = None,
        equipment: EquipmentType | None = None,
        primary_group_id: int | None = None,
        exclude_ids: Collection[int] = (),
    ) -> list[ExerciseRow]: ...


def _not_found() -> AppError:
    return AppError(404, ErrorCode.NOT_FOUND, "Not found")


class LibraryService:
    def __init__(self, library: LibraryReader, plans: TrainingPlanUnitOfWork) -> None:
        self._library = library
        self._plans = plans

    async def exercises(
        self,
        *,
        q: str | None,
        muscle_group_id: int | None,
        difficulty_level: DbLevel | None,
        limit: int,
        offset: int,
    ) -> Page[ExerciseRow]:
        return await self._library.list_exercises(
            q=q,
            muscle_group_id=muscle_group_id,
            difficulty_level=difficulty_level,
            limit=limit,
            offset=offset,
        )

    async def exercise(self, exercise_id: int) -> ExerciseRow:
        exercise = await self._library.get_exercise(exercise_id)
        if exercise is None:
            raise _not_found()
        return exercise

    async def alternatives(
        self, user_id: int, exercise_id: int, session_exercise_id: int | None
    ) -> list[ExerciseRow]:
        """404 for an unknown exercise, for another user's session exercise and for a
        session exercise that does not hold this exercise (questions.md, B-08)."""
        exercise = await self.exercise(exercise_id)
        primary = next((g.muscle_group_id for g in exercise.muscle_groups if g.is_primary), None)

        async with self._plans() as store:
            if session_exercise_id is None:
                limits = await store.profile_limits(user_id)
                level, equipment = limits if limits else (None, None)
                exclude = {exercise_id}
            else:
                context = await store.swap_context(user_id, session_exercise_id)
                if context is None or context.exercise_id != exercise_id:
                    raise _not_found()
                level, equipment = context.experience_level, context.equipment
                exclude = context.session_exercise_ids | {exercise_id}

        if primary is None:  # every seeded exercise has one (DB-01 #4)
            return []
        return await self._library.eligible_exercises(
            user_id,
            level=None if level is None else DbLevel(level.value),
            equipment=None if equipment is None else EquipmentType(equipment.value),
            primary_group_id=primary,
            exclude_ids=exclude,
        )
