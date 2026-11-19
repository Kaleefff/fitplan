"""Custom exercises: create, edit and delete the user's own (B-29; FR-P10, D26).

`api-rules.md` "Custom exercises": only the owner may change or delete one; a library
exercise or another user's custom exercise answers 404, like a missing row. Reads go
through `LibraryService` (library and own exercises mixed, `is_custom` marks own ones).
"""

from collections.abc import Mapping
from typing import Protocol

from app.core.errors import AppError, ErrorCode
from app.db.repositories.custom_exercises import CustomExerciseIn, MuscleGroupsIn, WriteError
from app.db.repositories.library import ExerciseRow, MuscleGroupRow


class CustomExerciseWriter(Protocol):
    async def create(
        self, user_id: int, exercise: CustomExerciseIn
    ) -> ExerciseRow | WriteError: ...

    async def update(
        self,
        user_id: int,
        exercise_id: int,
        changes: Mapping[str, object],
        muscle_groups: MuscleGroupsIn | None = None,
    ) -> ExerciseRow | WriteError: ...

    async def delete(self, user_id: int, exercise_id: int) -> WriteError | None: ...


class ExerciseReader(Protocol):
    async def muscle_groups(self) -> list[MuscleGroupRow]: ...

    async def get_exercise(self, user_id: int, exercise_id: int) -> ExerciseRow | None: ...


def _detail(field: str, code: str, message: str) -> dict:
    return {"field": field, "code": code, "message": message}


def _error(error: WriteError) -> AppError:
    if error == WriteError.NAME_TAKEN:
        # TODO(questions.md [DB-16] custom-exercise-name): unique per user, any case
        return AppError(
            409,
            ErrorCode.CONFLICT,
            "You already have an exercise with this name",
            [_detail("body.name", "duplicate", "Name already used by your exercise")],
        )
    if error == WriteError.LIMIT_REACHED:
        # TODO(questions.md [B-29] custom-exercise-limit): proposed default, 200 per user
        return AppError(
            409,
            ErrorCode.CONFLICT,
            "Custom exercise limit reached",
            [{"code": "limit_reached", "message": "Delete an exercise to add a new one"}],
        )
    if error == WriteError.IN_USE:
        # TODO(questions.md [B-29] custom-exercise-delete): proposed default, 409
        return AppError(
            409,
            ErrorCode.CONFLICT,
            "The exercise is used by a plan, a workout or a personal record",
            [{"code": "in_use", "message": "The exercise is still in use"}],
        )
    if error == WriteError.INVALID_MUSCLE_GROUPS:  # checked before; only a race
        return AppError(
            422,
            ErrorCode.VALIDATION_ERROR,
            "Invalid muscle groups",
            [_detail("body.primary_muscle_group_id", "invalid_value", "Invalid muscle groups")],
        )
    # NOT_FOUND: missing, another user's custom exercise or a library exercise
    # TODO(questions.md [B-29] custom-exercise-library-write): proposed default, 404
    return AppError(404, ErrorCode.NOT_FOUND, "Not found")


class CustomExerciseService:
    def __init__(self, writer: CustomExerciseWriter, reader: ExerciseReader) -> None:
        self._writer = writer
        self._reader = reader

    async def _check_groups(self, groups: MuscleGroupsIn) -> None:
        """Unknown ids are 422 `not_found` with their field (the body model already
        rejects repeated ids and the primary among the secondary groups)."""
        known = {g.id for g in await self._reader.muscle_groups()}
        details = []
        if groups.primary_id not in known:
            details.append(
                _detail("body.primary_muscle_group_id", "not_found", "Unknown muscle group")
            )
        details += [
            _detail(f"body.secondary_muscle_group_ids.{i}", "not_found", "Unknown muscle group")
            for i, group_id in enumerate(groups.secondary_ids)
            if group_id not in known
        ]
        if details:
            raise AppError(422, ErrorCode.VALIDATION_ERROR, "Unknown muscle group", details)

    async def create(self, user_id: int, exercise: CustomExerciseIn) -> ExerciseRow:
        await self._check_groups(exercise.muscle_groups)
        result = await self._writer.create(user_id, exercise)
        if result == WriteError.NOT_FOUND:  # the account itself is gone
            raise AppError(401, ErrorCode.UNAUTHORIZED, "Unknown user")
        if isinstance(result, WriteError):
            raise _error(result)
        return result

    async def update(
        self,
        user_id: int,
        exercise_id: int,
        changes: Mapping[str, object],
        primary_id: int | None = None,
        secondary_ids: tuple[int, ...] | None = None,
    ) -> ExerciseRow:
        """PATCH: the sent fields; sending either group field replaces all groups, the
        other one kept from the exercise."""
        groups = None
        if primary_id is not None or secondary_ids is not None:
            current = await self._reader.get_exercise(user_id, exercise_id)
            if current is None or not current.is_custom:
                raise _error(WriteError.NOT_FOUND)
            if primary_id is None:
                primary_id = next(g.muscle_group_id for g in current.muscle_groups if g.is_primary)
            if secondary_ids is None:
                secondary_ids = tuple(
                    g.muscle_group_id for g in current.muscle_groups if not g.is_primary
                )
            if primary_id in secondary_ids:
                raise AppError(
                    422,
                    ErrorCode.VALIDATION_ERROR,
                    "The primary muscle group cannot also be secondary",
                    [
                        _detail(
                            "body.secondary_muscle_group_ids",
                            "invalid_value",
                            "The primary muscle group cannot also be secondary",
                        )
                    ],
                )
            groups = MuscleGroupsIn(primary_id, secondary_ids)
            await self._check_groups(groups)
        result = await self._writer.update(user_id, exercise_id, changes, groups)
        if isinstance(result, WriteError):
            raise _error(result)
        return result

    async def delete(self, user_id: int, exercise_id: int) -> None:
        error = await self._writer.delete(user_id, exercise_id)
        if error is not None:
            raise _error(error)
