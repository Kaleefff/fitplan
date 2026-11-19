"""Exercise and food libraries (B-08, B-09, B-29; FR-P8, FR-P10, FR-A1).

Lists are ordered by name, then id. Exercises are the library's and the user's own custom
ones (`is_custom`, D26); only the owner may change or delete a custom exercise.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Response
from pydantic import (
    BaseModel,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.api.deps import (
    CurrentUser,
    get_current_user,
    get_custom_exercise_service,
    get_library_service,
)
from app.core.errors import VALIDATION_ERROR_RESPONSE, Error
from app.db.enums import DifficultyLevel as DbLevel
from app.db.enums import EquipmentType
from app.db.repositories.custom_exercises import CustomExerciseIn, MuscleGroupsIn
from app.db.repositories.library import ExerciseRow, FoodRow
from app.domain.constants import DifficultyLevel, Equipment
from app.services.custom_exercises import CustomExerciseService
from app.services.library import LibraryService

router = APIRouter(tags=["library"])

INT_MAX = 2_147_483_647
User = Annotated[CurrentUser, Depends(get_current_user)]
Service = Annotated[LibraryService, Depends(get_library_service)]
ExerciseId = Annotated[int, Path(ge=1, le=INT_MAX)]
FoodId = Annotated[int, Path(ge=1, le=INT_MAX)]
UNAUTHORIZED = {"model": Error, "description": "Missing, expired or invalid token"}
NOT_FOUND = {"model": Error, "description": "Not found"}
Custom = Annotated[CustomExerciseService, Depends(get_custom_exercise_service)]
GroupId = Annotated[int, Field(ge=1, le=INT_MAX)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
# TODO(questions.md [B-29] custom-exercise-text): optional, stored as ""
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
MAX_SECONDARY_GROUPS = 9  # every seeded group but the primary


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
    is_custom: bool = Field(description="The user's own exercise (FR-P10)")
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
            is_custom=row.is_custom,
            muscle_groups=[
                ExerciseMuscleGroupOut(
                    muscle_group_id=g.muscle_group_id,
                    group_name=g.group_name,
                    is_primary=g.is_primary,
                )
                for g in row.muscle_groups
            ],
        )


DietRole = Literal["protein", "carb", "vegetable", "fruit", "dairy", "fat", "dish", "other"]
MealType = Literal["breakfast", "lunch", "dinner", "snack"]


class FoodItemOut(BaseModel):
    """Values per 100 g; portions in grams (algorithms.md 5.2)."""

    id: int
    name: str
    cals_per_100g: float
    protein_per_100g: float
    fat_per_100g: float
    carbs_per_100g: float
    diet_role: DietRole
    suitable_meal_types: list[MealType]
    is_vegetarian: bool
    is_vegan: bool
    default_portion_g: float
    min_portion_g: float
    max_portion_g: float
    portion_step_g: float
    category_ids: list[int]
    allergen_ids: list[int]

    @classmethod
    def of(cls, row: FoodRow) -> "FoodItemOut":
        return cls(
            id=row.id,
            name=row.name,
            cals_per_100g=float(row.cals_per_100g),
            protein_per_100g=float(row.protein_per_100g),
            fat_per_100g=float(row.fat_per_100g),
            carbs_per_100g=float(row.carbs_per_100g),
            diet_role=row.diet_role.value,
            suitable_meal_types=[m.value for m in row.suitable_meal_types],
            is_vegetarian=row.is_vegetarian,
            is_vegan=row.is_vegan,
            default_portion_g=float(row.default_portion_g),
            min_portion_g=float(row.min_portion_g),
            max_portion_g=float(row.max_portion_g),
            portion_step_g=float(row.portion_step_g),
            category_ids=list(row.category_ids),
            allergen_ids=list(row.allergen_ids),
        )


class FoodPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[FoodItemOut]


class FoodCategoryOut(BaseModel):
    id: int
    category_name: str
    description: str


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
    user: User,
    service: Service,
    custom_only: Annotated[
        bool, Query(description="Only the user's own exercises (My exercises)")
    ] = False,
    q: Annotated[str | None, Query(max_length=100)] = None,
    muscle_group_id: Annotated[int | None, Query(ge=1, le=INT_MAX)] = None,
    difficulty_level: DifficultyLevel | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=INT_MAX)] = 0,
) -> ExercisePage:
    page = await service.exercises(
        user.id,
        custom_only=custom_only,
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
async def get_exercise(exercise_id: ExerciseId, user: User, service: Service) -> ExerciseOut:
    return ExerciseOut.of(await service.exercise(user.id, exercise_id))


# ---------------------------------------------------------------- custom exercises (B-29)


def _secondary_without_primary(values: list[int], info: ValidationInfo) -> list[int]:
    if len(set(values)) != len(values):
        raise ValueError("A muscle group is listed twice")
    if info.data.get("primary_muscle_group_id") in values:
        raise ValueError("The primary muscle group cannot also be secondary")
    return values


class CustomExerciseBody(BaseModel):
    """A custom exercise has exactly one primary muscle group (api-rules.md)."""

    name: Name
    # TODO(questions.md [B-29] custom-exercise-level): required, as for library exercises
    difficulty_level: DifficultyLevel
    equipment: Equipment
    is_compound: bool = False
    is_bodyweight: bool = False
    description: Text = ""
    instruction: Text = ""
    primary_muscle_group_id: GroupId
    secondary_muscle_group_ids: Annotated[list[GroupId], Field(max_length=MAX_SECONDARY_GROUPS)] = (
        Field(default_factory=list)
    )

    _secondary = field_validator("secondary_muscle_group_ids")(_secondary_without_primary)

    def to_input(self) -> CustomExerciseIn:
        return CustomExerciseIn(
            name=self.name,
            difficulty_level=DbLevel(self.difficulty_level.value),
            equipment=EquipmentType(self.equipment.value),
            is_compound=self.is_compound,
            is_bodyweight=self.is_bodyweight,
            muscle_groups=MuscleGroupsIn(
                self.primary_muscle_group_id, tuple(self.secondary_muscle_group_ids)
            ),
            description=self.description,
            instruction=self.instruction,
        )


class CustomExercisePatchBody(BaseModel):
    """At least one field; a field that is sent may not be null. Sending either muscle
    group field replaces the groups, the other one kept as it is."""

    name: Name = Field(default=None)
    difficulty_level: DifficultyLevel = Field(default=None)
    equipment: Equipment = Field(default=None)
    is_compound: bool = Field(default=None)
    is_bodyweight: bool = Field(default=None)
    description: Text = Field(default=None)
    instruction: Text = Field(default=None)
    primary_muscle_group_id: GroupId = Field(default=None)
    secondary_muscle_group_ids: Annotated[list[GroupId], Field(max_length=MAX_SECONDARY_GROUPS)] = (
        Field(default=None)
    )

    _secondary = field_validator("secondary_muscle_group_ids")(_secondary_without_primary)

    @model_validator(mode="after")
    def _some_field(self) -> "CustomExercisePatchBody":
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        return self

    def changes(self) -> dict[str, object]:
        """The sent exercise columns, as the repository stores them."""
        values: dict[str, object] = {}
        for field in self.model_fields_set - {
            "primary_muscle_group_id",
            "secondary_muscle_group_ids",
        }:
            values[field] = getattr(self, field)
        if "difficulty_level" in values:
            values["difficulty_level"] = DbLevel(self.difficulty_level.value)
        if "equipment" in values:
            values["equipment"] = EquipmentType(self.equipment.value)
        return values


def _write_error(description: str) -> dict:
    return {"model": Error, "description": description}


@router.post(
    "/exercises",
    operation_id="createCustomExercise",
    summary="Add an own exercise (FR-P10)",
    status_code=201,
    responses={
        **VALIDATION_ERROR_RESPONSE,
        401: UNAUTHORIZED,
        409: _write_error("A custom exercise of the user has this name, or the limit is reached"),
    },
)
async def create_custom_exercise(
    body: CustomExerciseBody, user: User, service: Custom
) -> ExerciseOut:
    return ExerciseOut.of(await service.create(user.id, body.to_input()))


@router.patch(
    "/exercises/{exercise_id}",
    operation_id="updateCustomExercise",
    summary="Edit an own exercise (FR-P10)",
    responses={
        **VALIDATION_ERROR_RESPONSE,
        401: UNAUTHORIZED,
        404: _write_error("No custom exercise of the user (library exercises are read-only)"),
        409: _write_error("A custom exercise of the user has this name"),
    },
)
async def update_custom_exercise(
    exercise_id: ExerciseId, body: CustomExercisePatchBody, user: User, service: Custom
) -> ExerciseOut:
    sent = body.model_fields_set
    row = await service.update(
        user.id,
        exercise_id,
        body.changes(),
        body.primary_muscle_group_id if "primary_muscle_group_id" in sent else None,
        (tuple(body.secondary_muscle_group_ids) if "secondary_muscle_group_ids" in sent else None),
    )
    return ExerciseOut.of(row)


@router.delete(
    "/exercises/{exercise_id}",
    operation_id="deleteCustomExercise",
    summary="Delete an own exercise that no plan, workout or record uses (FR-P10)",
    status_code=204,
    response_class=Response,
    responses={
        **VALIDATION_ERROR_RESPONSE,
        401: UNAUTHORIZED,
        404: _write_error("No custom exercise of the user (library exercises are read-only)"),
        409: _write_error("Still used by a plan, a workout or a personal record"),
    },
)
async def delete_custom_exercise(exercise_id: ExerciseId, user: User, service: Custom) -> Response:
    await service.delete(user.id, exercise_id)
    return Response(status_code=204)


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


@router.get(
    "/foods",
    operation_id="listFoods",
    summary="Food database with nutrition per 100 g (FR-P8)",
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED},
)
async def list_foods(
    _: User,
    service: Service,
    q: Annotated[str | None, Query(max_length=150)] = None,
    category_id: Annotated[int | None, Query(ge=1, le=INT_MAX)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=INT_MAX)] = 0,
) -> FoodPage:
    page = await service.foods(q=q, category_id=category_id, limit=limit, offset=offset)
    return FoodPage(
        total=page.total,
        limit=page.limit,
        offset=page.offset,
        items=[FoodItemOut.of(f) for f in page.items],
    )


@router.get(
    "/foods/{food_id}",
    operation_id="getFood",
    summary="Food detail",
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED, 404: NOT_FOUND},
)
async def get_food(food_id: FoodId, _: User, service: Service) -> FoodItemOut:
    return FoodItemOut.of(await service.food(food_id))


@router.get(
    "/food-categories",
    operation_id="listFoodCategories",
    summary="Reference list of food categories",
    responses={401: UNAUTHORIZED},
)
async def list_food_categories(_: User, service: Service) -> list[FoodCategoryOut]:
    return [
        FoodCategoryOut(id=c.id, category_name=c.category_name, description=c.description)
        for c in await service.food_categories()
    ]
