"""Reference lists, ordered by name, then id (api-rules.md Conventions)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import CurrentUser, get_current_user, get_profile_service
from app.api.v1.profile import AllergenOut
from app.core.errors import Error
from app.services.profile import ProfileService

router = APIRouter()

User = Annotated[CurrentUser, Depends(get_current_user)]
Service = Annotated[ProfileService, Depends(get_profile_service)]
UNAUTHORIZED = {401: {"model": Error, "description": "Missing, expired or invalid token"}}


class InjuryTypeOut(BaseModel):
    id: int
    type_name: str
    description: str
    avg_healing_time_days: int


class MuscleGroupOut(BaseModel):
    id: int
    group_name: str
    description: str
    image_url: str | None


@router.get(
    "/injury-types",
    operation_id="listInjuryTypes",
    summary="Reference list of injury types",
    tags=["account"],
    responses=UNAUTHORIZED,
)
async def list_injury_types(_: User, service: Service) -> list[InjuryTypeOut]:
    return [
        InjuryTypeOut(
            id=t.id,
            type_name=t.name,
            description=t.description,
            avg_healing_time_days=t.extra["avg_healing_time_days"],
        )
        for t in await service.reference("injury_types")
    ]


@router.get(
    "/allergens",
    operation_id="listAllergens",
    summary="Reference list of allergens",
    tags=["account"],
    responses=UNAUTHORIZED,
)
async def list_allergens(_: User, service: Service) -> list[AllergenOut]:
    return [AllergenOut.of(a) for a in await service.reference("allergens")]


@router.get(
    "/muscle-groups",
    operation_id="listMuscleGroups",
    summary="Reference list of muscle groups",
    tags=["library"],
    responses=UNAUTHORIZED,
)
async def list_muscle_groups(_: User, service: Service) -> list[MuscleGroupOut]:
    return [
        MuscleGroupOut(
            id=g.id, group_name=g.name, description=g.description, image_url=g.extra["image_url"]
        )
        for g in await service.reference("muscle_groups")
    ]
