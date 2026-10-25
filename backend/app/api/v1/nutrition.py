from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import CurrentUser, get_current_user, get_profile_reader
from app.core.errors import Error
from app.domain.constants import Goal
from app.services.nutrition import ProfileReader, get_nutrition_targets

router = APIRouter(tags=["diet"])


class NutritionTargetsOut(BaseModel):
    # float, not Decimal: the contract has JSON numbers, Pydantic writes Decimal as a string
    goal: Goal
    bmr: float
    tdee: int
    target_kcal: int
    protein_g: float
    fat_g: float
    carbs_g: float


@router.get(
    "/nutrition/targets",
    operation_id="getNutritionTargets",
    summary="BMR, TDEE, calorie target and macros for the profile goal (FR-P4, FR-P5)",
    response_model=NutritionTargetsOut,
    responses={
        401: {"model": Error, "description": "Missing, expired or invalid token"},
        404: {"model": Error, "description": "The user has no profile yet"},
    },
)
async def get_targets(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    reader: Annotated[ProfileReader, Depends(get_profile_reader)],
) -> NutritionTargetsOut:
    goal, targets = await get_nutrition_targets(reader, user.id)
    return NutritionTargetsOut(
        goal=goal,
        bmr=float(targets.bmr),
        tdee=targets.tdee,
        target_kcal=targets.target_kcal,
        protein_g=float(targets.protein_g),
        fat_g=float(targets.fat_g),
        carbs_g=float(targets.carbs_g),
    )
