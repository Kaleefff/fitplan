from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Response
from pydantic import BaseModel, Field, model_validator

from app.api.deps import (
    CurrentUser,
    get_current_user,
    get_profile_service,
    get_user_repository,
)
from app.core.errors import VALIDATION_ERROR_RESPONSE, AppError, Error, ErrorCode
from app.domain.constants import (
    AGE_MAX,
    AGE_MIN,
    HEIGHT_CM_MAX,
    HEIGHT_CM_MIN,
    WEIGHT_KG_MAX,
    WEIGHT_KG_MIN,
    DifficultyLevel,
    Equipment,
    Goal,
    InjurySeverity,
    Sex,
)
from app.domain.rounding import round_half_up
from app.services.auth import UserRepository
from app.services.profile import (
    FoodView,
    InjuryIn,
    InjuryView,
    NamedView,
    ProfileIn,
    ProfileService,
    ProfileView,
)

router = APIRouter(prefix="/users/me", tags=["account"])

INT_MAX = 2_147_483_647
Id = Annotated[int, Field(ge=1, le=INT_MAX)]
Kg = Annotated[float, Field(ge=float(WEIGHT_KG_MIN), le=float(WEIGHT_KG_MAX), description="kg")]
# algorithms.md 0: the PAL values offered
Pal = Literal[1.2, 1.375, 1.55, 1.725, 1.9]


def _kg(value: float) -> Decimal:
    return round_half_up(Decimal(str(value)), 2)  # NUMERIC(5, 2)


class ProfileBody(BaseModel):
    age: Annotated[int, Field(ge=AGE_MIN, le=AGE_MAX)]
    sex: Sex
    current_weight: Kg
    height: Annotated[int, Field(ge=HEIGHT_CM_MIN, le=HEIGHT_CM_MAX, description="cm")]
    activity_level_pal: Pal
    goal: Goal
    experience_level: DifficultyLevel
    equipment: Equipment
    target_value: Kg | None = Field(None, description="Target body weight in kg (FR-R4)")

    def to_input(self) -> ProfileIn:
        return ProfileIn(
            age=self.age,
            sex=self.sex,
            current_weight=_kg(self.current_weight),
            height=self.height,
            activity_level_pal=Decimal(str(self.activity_level_pal)),
            goal=self.goal,
            experience_level=self.experience_level,
            equipment=self.equipment,
            target_value=None if self.target_value is None else _kg(self.target_value),
        )


class ProfileOut(BaseModel):
    age: int
    sex: Sex
    current_weight: float
    height: int
    activity_level_pal: Pal
    goal: Goal
    experience_level: DifficultyLevel
    equipment: Equipment
    target_value: float | None
    tdee: int
    profile_update: datetime

    @classmethod
    def of(cls, p: ProfileView) -> "ProfileOut":
        return cls(
            age=p.age,
            sex=p.sex,
            current_weight=float(p.current_weight),
            height=p.height,
            activity_level_pal=float(p.activity_level_pal),
            goal=p.goal,
            experience_level=p.experience_level,
            equipment=p.equipment,
            target_value=None if p.target_value is None else float(p.target_value),
            tdee=p.tdee,
            profile_update=p.profile_update,
        )


class InjuryBody(BaseModel):
    injury_type_id: Id
    affected_muscle_group_id: Id
    severity: InjurySeverity
    start_date: date
    is_active: bool = True


class InjuryPatchBody(BaseModel):
    """At least one field; a field that is sent may not be null."""

    # not Optional: an absent field stays None, a null is a type error on that field
    injury_type_id: Id = Field(default=None)
    affected_muscle_group_id: Id = Field(default=None)
    severity: InjurySeverity = Field(default=None)
    start_date: date = Field(default=None)
    is_active: bool = Field(default=None)

    @model_validator(mode="after")
    def _some_field(self) -> "InjuryPatchBody":
        if not self.model_fields_set:
            raise ValueError("Send at least one field")
        return self


class InjuryOut(BaseModel):
    id: int
    injury_type_id: int
    affected_muscle_group_id: int
    severity: InjurySeverity
    start_date: date
    is_active: bool

    @classmethod
    def of(cls, i: InjuryView) -> "InjuryOut":
        return cls(
            id=i.id,
            injury_type_id=i.injury_type_id,
            affected_muscle_group_id=i.affected_muscle_group_id,
            severity=i.severity,
            start_date=i.start_date,
            is_active=i.is_active,
        )


class AllergyBody(BaseModel):
    allergen_ids: list[Id] = Field(description="Duplicates are dropped")


class AllergenOut(BaseModel):
    id: int
    name: str
    description: str

    @classmethod
    def of(cls, a: NamedView) -> "AllergenOut":
        return cls(id=a.id, name=a.name, description=a.description)


class ExcludedFoodsBody(BaseModel):
    food_item_ids: list[Id] = Field(description="Duplicates are dropped")


class FoodItemOut(BaseModel):
    id: int
    name: str
    cals_per_100g: float
    protein_per_100g: float
    fat_per_100g: float
    carbs_per_100g: float
    category_ids: list[int]

    @classmethod
    def of(cls, f: FoodView) -> "FoodItemOut":
        return cls(
            id=f.id,
            name=f.name,
            cals_per_100g=float(f.cals_per_100g),
            protein_per_100g=float(f.protein_per_100g),
            fat_per_100g=float(f.fat_per_100g),
            carbs_per_100g=float(f.carbs_per_100g),
            category_ids=list(f.category_ids),
        )


def _error(description: str) -> dict:
    return {"model": Error, "description": description}


User = Annotated[CurrentUser, Depends(get_current_user)]
Service = Annotated[ProfileService, Depends(get_profile_service)]
Users = Annotated[UserRepository, Depends(get_user_repository)]
InjuryId = Annotated[int, Path(ge=1, le=INT_MAX)]
UNAUTHORIZED = _error("Missing, expired or invalid token")
NOT_FOUND = _error("No such injury of the user")


async def _timezone(users: UserRepository, user_id: int) -> str:
    account = await users.get_by_id(user_id)
    if account is None:  # deleted while the access token is still valid
        raise AppError(401, ErrorCode.UNAUTHORIZED, "Unknown user")
    return account.timezone


# ---------------------------------------------------------------- profile


@router.get(
    "/profile",
    operation_id="getProfile",
    summary="Biometric profile (FR-U6)",
    responses={401: UNAUTHORIZED, 404: _error("No profile yet")},
)
async def get_profile(user: User, service: Service) -> ProfileOut:
    return ProfileOut.of(await service.get_profile(user.id))


@router.put(
    "/profile",
    operation_id="putProfile",
    summary="Create or replace the biometric profile (FR-U6, FR-U7)",
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED},
)
async def put_profile(body: ProfileBody, user: User, service: Service) -> ProfileOut:
    return ProfileOut.of(await service.put_profile(user.id, body.to_input()))


# ---------------------------------------------------------------- injuries


@router.get(
    "/injuries",
    operation_id="listInjuries",
    summary="The user's injuries, active first, then newest (FR-U6)",
    responses={401: UNAUTHORIZED},
)
async def list_injuries(user: User, service: Service) -> list[InjuryOut]:
    return [InjuryOut.of(i) for i in await service.list_injuries(user.id)]


@router.post(
    "/injuries",
    operation_id="createInjury",
    summary="Add an injury",
    status_code=201,
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED},
)
async def create_injury(body: InjuryBody, user: User, service: Service, users: Users) -> InjuryOut:
    injury = InjuryIn(
        body.injury_type_id,
        body.affected_muscle_group_id,
        body.severity,
        body.start_date,
        body.is_active,
    )
    timezone = await _timezone(users, user.id)
    return InjuryOut.of(await service.add_injury(user.id, injury, timezone, datetime.now(UTC)))


@router.patch(
    "/injuries/{injury_id}",
    operation_id="updateInjury",
    summary="Edit an injury (for example mark it healed)",
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED, 404: NOT_FOUND},
)
async def update_injury(
    injury_id: InjuryId, body: InjuryPatchBody, user: User, service: Service, users: Users
) -> InjuryOut:
    changes = {field: getattr(body, field) for field in body.model_fields_set}
    timezone = await _timezone(users, user.id)
    injury = await service.update_injury(user.id, injury_id, changes, timezone, datetime.now(UTC))
    return InjuryOut.of(injury)


@router.delete(
    "/injuries/{injury_id}",
    operation_id="deleteInjury",
    summary="Delete an injury",
    status_code=204,
    response_class=Response,
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED, 404: NOT_FOUND},
)
async def delete_injury(injury_id: InjuryId, user: User, service: Service) -> Response:
    await service.delete_injury(user.id, injury_id)
    return Response(status_code=204)


# ---------------------------------------------------------------- allergies, excluded foods


@router.get(
    "/allergies",
    operation_id="getAllergies",
    summary="The user's allergens (FR-P6, FR-N3)",
    responses={401: UNAUTHORIZED},
)
async def get_allergies(user: User, service: Service) -> list[AllergenOut]:
    return [AllergenOut.of(a) for a in await service.get_allergens(user.id)]


@router.put(
    "/allergies",
    operation_id="putAllergies",
    summary="Replace the user's allergen list",
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED},
)
async def put_allergies(body: AllergyBody, user: User, service: Service) -> list[AllergenOut]:
    return [AllergenOut.of(a) for a in await service.put_allergens(user.id, body.allergen_ids)]


@router.get(
    "/excluded-foods",
    operation_id="getExcludedFoods",
    summary="Foods the user never wants in a diet plan (FR-P6)",
    responses={401: UNAUTHORIZED},
)
async def get_excluded_foods(user: User, service: Service) -> list[FoodItemOut]:
    return [FoodItemOut.of(f) for f in await service.get_excluded_foods(user.id)]


@router.put(
    "/excluded-foods",
    operation_id="putExcludedFoods",
    summary="Replace the excluded food list",
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED},
)
async def put_excluded_foods(
    body: ExcludedFoodsBody, user: User, service: Service
) -> list[FoodItemOut]:
    foods = await service.put_excluded_foods(user.id, body.food_item_ids)
    return [FoodItemOut.of(f) for f in foods]
