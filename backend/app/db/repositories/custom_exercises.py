"""Custom exercises: create, update and delete for their owner (DB-16, FR-P10, D26).

A custom exercise is an `exercise` row whose `user_id` is its owner. Reads go through
`SqlLibraryRepository` (library and own exercises mixed, `is_custom` marks own ones);
this module writes. Every write is scoped to `user_id = owner`: a library exercise
(`user_id IS NULL`) or another user's custom exercise is never changed and answers
NOT_FOUND, exactly like a missing row. `user_id` itself is never written by an update.

Muscle groups come as one primary group plus secondary ones (the primary not among
them), so a custom exercise always has exactly one primary group, like the seeded ones.

Deleting checks the four deferred foreign keys to `exercise` immediately (D26): an
exercise still referenced by a session exercise, a logged workout or a personal record
is not deleted and answers IN_USE.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.enums import DifficultyLevel, EquipmentType
from app.db.models import AppUser, Exercise, ExerciseMuscleGroup, MuscleGroup
from app.db.repositories.library import ExerciseRow, exercise_groups, exercise_row

# The NO ACTION foreign keys to exercise.id, deferred by migration 0004 (D26).
EXERCISE_REFERENCES = (
    "session_exercise_exercise_id_fkey",
    "session_exercise_original_exercise_id_fkey",
    "workout_log_exercise_exercise_id_fkey",
    "personal_record_exercise_id_fkey",
)
CUSTOM_NAME_INDEX = "ux_exercise_custom_name"
# TODO(questions.md [B-29] custom-exercise-limit): proposed default, 200 per user.
CUSTOM_EXERCISE_LIMIT = 200
# Columns an update may change; never `id` or `user_id`.
UPDATABLE = frozenset(
    {
        "name",
        "difficulty_level",
        "equipment",
        "is_compound",
        "is_bodyweight",
        "description",
        "instruction",
    }
)


class WriteError(StrEnum):
    # no custom exercise of this owner: missing, another user's, or a library exercise
    # TODO(questions.md [B-29] custom-exercise-library-write): a library exercise answers
    # like a missing row (proposed 404).
    NOT_FOUND = "not_found"
    # TODO(questions.md [DB-16] custom-exercise-name): unique per user on lower(name); a
    # library exercise's name is allowed (ux_exercise_custom_name).
    NAME_TAKEN = "name_taken"
    LIMIT_REACHED = "limit_reached"
    # unknown group id, a group listed twice, or the primary group among the secondary ones
    INVALID_MUSCLE_GROUPS = "invalid_muscle_groups"
    # TODO(questions.md [B-29] custom-exercise-delete): still referenced (proposed 409);
    # an unused exercise is deleted for real.
    IN_USE = "in_use"


@dataclass(frozen=True)
class MuscleGroupsIn:
    primary_id: int
    secondary_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class CustomExerciseIn:
    name: str
    # TODO(questions.md [B-29] custom-exercise-level): required, as for library exercises.
    difficulty_level: DifficultyLevel
    equipment: EquipmentType
    is_compound: bool
    is_bodyweight: bool
    muscle_groups: MuscleGroupsIn
    # TODO(questions.md [B-29] custom-exercise-text): optional, stored as "".
    description: str = ""
    instruction: str = ""


class _Rejected(Exception):
    """Ends a write's transaction (rolled back) with a WriteError."""

    def __init__(self, error: WriteError) -> None:
        self.error = error


class SqlCustomExerciseRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(self, user_id: int, exercise: CustomExerciseIn) -> ExerciseRow | WriteError:
        try:
            async with self._sessions.begin() as session:
                # one creating writer per user, so the limit count cannot race. FOR NO KEY
                # UPDATE: the insert's own foreign key lock on the user row (FOR KEY SHARE)
                # does not conflict with it.
                owner = await session.scalar(
                    select(AppUser.id).where(AppUser.id == user_id).with_for_update(key_share=True)
                )
                if owner is None:
                    raise _Rejected(WriteError.NOT_FOUND)
                count = await session.scalar(
                    select(func.count()).select_from(Exercise).where(Exercise.user_id == user_id)
                )
                if count >= CUSTOM_EXERCISE_LIMIT:
                    raise _Rejected(WriteError.LIMIT_REACHED)
                await _check_groups(session, exercise.muscle_groups)

                row = Exercise(
                    user_id=user_id,
                    name=exercise.name,
                    difficulty_level=exercise.difficulty_level,
                    equipment=exercise.equipment,
                    is_compound=exercise.is_compound,
                    is_bodyweight=exercise.is_bodyweight,
                    description=exercise.description,
                    instruction=exercise.instruction,
                )
                session.add(row)
                await _flush(session)
                await _replace_groups(session, row.id, exercise.muscle_groups)
                return await _row(session, row)
        except _Rejected as rejected:
            return rejected.error

    async def update(
        self,
        user_id: int,
        exercise_id: int,
        changes: Mapping[str, object],
        muscle_groups: MuscleGroupsIn | None = None,
    ) -> ExerciseRow | WriteError:
        """PATCH: the fields in `changes`; `muscle_groups` (when given) replace all groups."""
        unknown = set(changes) - UPDATABLE
        if unknown:
            raise ValueError(f"not an updatable exercise field: {sorted(unknown)}")
        try:
            async with self._sessions.begin() as session:
                # FOR NO KEY UPDATE: plans and workouts may keep referencing the exercise
                # (their FOR KEY SHARE does not conflict); a concurrent delete waits.
                row = await session.scalar(
                    select(Exercise)
                    .where(Exercise.id == exercise_id, Exercise.user_id == user_id)
                    .with_for_update(key_share=True)
                )
                if row is None:
                    raise _Rejected(WriteError.NOT_FOUND)
                if muscle_groups is not None:
                    await _check_groups(session, muscle_groups)
                for column, value in changes.items():
                    setattr(row, column, value)
                await _flush(session)
                if muscle_groups is not None:
                    await _replace_groups(session, row.id, muscle_groups)
                return await _row(session, row)
        except _Rejected as rejected:
            return rejected.error

    async def delete(self, user_id: int, exercise_id: int) -> WriteError | None:
        """None when deleted (its muscle-group links go with it)."""
        try:
            async with self._sessions.begin() as session:
                # the deferred foreign keys would only fail at commit; checked here instead
                await session.execute(
                    text(f"SET CONSTRAINTS {', '.join(EXERCISE_REFERENCES)} IMMEDIATE")
                )
                result = await session.execute(
                    delete(Exercise).where(Exercise.id == exercise_id, Exercise.user_id == user_id)
                )
                if result.rowcount == 0:
                    raise _Rejected(WriteError.NOT_FOUND)
        except _Rejected as rejected:
            return rejected.error
        except IntegrityError as exc:
            if getattr(exc.orig.diag, "constraint_name", None) in EXERCISE_REFERENCES:
                return WriteError.IN_USE
            raise
        return None


async def _check_groups(session: AsyncSession, groups: MuscleGroupsIn) -> None:
    ids = [groups.primary_id, *groups.secondary_ids]
    if len(set(ids)) != len(ids):  # also the primary among the secondary groups
        raise _Rejected(WriteError.INVALID_MUSCLE_GROUPS)
    found = set(await session.scalars(select(MuscleGroup.id).where(MuscleGroup.id.in_(ids))))
    if found != set(ids):
        raise _Rejected(WriteError.INVALID_MUSCLE_GROUPS)


async def _replace_groups(session: AsyncSession, exercise_id: int, groups: MuscleGroupsIn) -> None:
    await session.execute(
        delete(ExerciseMuscleGroup).where(ExerciseMuscleGroup.exercise_id == exercise_id)
    )
    session.add_all(
        ExerciseMuscleGroup(exercise_id=exercise_id, muscle_group_id=group_id, is_primary=primary)
        for group_id, primary in [
            (groups.primary_id, True),
            *((group_id, False) for group_id in groups.secondary_ids),
        ]
    )
    await session.flush()


async def _flush(session: AsyncSession) -> None:
    try:
        await session.flush()
    except IntegrityError as exc:
        if getattr(exc.orig.diag, "constraint_name", None) == CUSTOM_NAME_INDEX:
            raise _Rejected(WriteError.NAME_TAKEN) from None
        raise


async def _row(session: AsyncSession, exercise: Exercise) -> ExerciseRow:
    groups = await exercise_groups(session, [exercise.id])
    return exercise_row(exercise, groups[exercise.id])
