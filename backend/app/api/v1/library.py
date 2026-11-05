"""Exercise library (B-08; FR-P8, FR-A1). Lists are ordered by name, then id."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel

from app.api.deps import CurrentUser, get_current_user, get_library_service
from app.core.errors import VALIDATION_ERROR_RESPONSE, Error
from app.db.enums import DifficultyLevel as DbLevel
from app.db.repositories.library import ExerciseRow
from app.domain.constants import DifficultyLevel, Equipment
from app.services.library import LibraryService

router = APIRouter(tags=["library"])

INT_MAX = 2_147_483_647
User = Annotated[CurrentUser, Depends(get_current_user)]
Service = Annotated[LibraryService, Depends(get_library_service)]
ExerciseId = Annotated[int, Path(ge=1, le=INT_MAX)]
UNAUTHORIZED = {"model": Error, "description": "Missing, expired or invalid token"}
NOT_FOUND = {"model": Error, "description": "Not found"}


class ExerciseMuscleGroupOut(BaseModel):
    muscle_group_id: int
    group_name: str
    is_primary: bool


class ExerciseOut(BaseModel):
    id: int
    name: str
    difficulty_level: DifficultyLevel
    equipment: Equipment
    is_compound: bool
    is_bodyweight: bool
    description: str
    instruction: str
    muscle_groups: list[ExerciseMuscleGroupOut]

    @classmethod
    def of(cls, row: ExerciseRow) -> "ExerciseOut":
        return cls(
            id=row.id,
            name=row.name,
            difficulty_level=DifficultyLevel(row.difficulty_level.value),
            equipment=Equipment(row.equipment.value),
            is_compound=row.is_compound,
            is_bodyweight=row.is_bodyweight,
            description=row.description,
            instruction=row.instruction,
            muscle_groups=[
                ExerciseMuscleGroupOut(
                    muscle_group_id=g.muscle_group_id,
                    group_name=g.group_name,
                    is_primary=g.is_primary,
                )
                for g in row.muscle_groups
            ],
        )


class ExercisePage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[ExerciseOut]


@router.get(
    "/exercises",
    operation_id="listExercises",
    summary="Exercise library with filters (FR-P8)",
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED},
)
async def list_exercises(
    _: User,
    service: Service,
    q: Annotated[str | None, Query(max_length=100)] = None,
    muscle_group_id: Annotated[int | None, Query(ge=1, le=INT_MAX)] = None,
    difficulty_level: DifficultyLevel | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=INT_MAX)] = 0,
) -> ExercisePage:
    page = await service.exercises(
        q=q,
        muscle_group_id=muscle_group_id,
        difficulty_level=None if difficulty_level is None else DbLevel(difficulty_level.value),
        limit=limit,
        offset=offset,
    )
    return ExercisePage(
        total=page.total,
        limit=page.limit,
        offset=page.offset,
        items=[ExerciseOut.of(e) for e in page.items],
    )


@router.get(
    "/exercises/{exercise_id}",
    operation_id="getExercise",
    summary="Exercise detail with text instruction (FR-P8)",
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED, 404: NOT_FOUND},
)
async def get_exercise(exercise_id: ExerciseId, _: User, service: Service) -> ExerciseOut:
    return ExerciseOut.of(await service.exercise(exercise_id))


@router.get(
    "/exercises/{exercise_id}/alternatives",
    operation_id="listExerciseAlternatives",
    summary="Alternatives with the same main muscle group (FR-A1, algorithms.md 4.9)",
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED, 404: NOT_FOUND},
)
async def list_exercise_alternatives(
    exercise_id: ExerciseId,
    user: User,
    service: Service,
    session_exercise_id: Annotated[int | None, Query(ge=1, le=INT_MAX)] = None,
) -> list[ExerciseOut]:
    rows = await service.alternatives(user.id, exercise_id, session_exercise_id)
    return [ExerciseOut.of(e) for e in rows]
