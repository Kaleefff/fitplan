"""Energy needs and macro targets (algorithms.md sections 1 and 2; FR-P4, FR-P5)."""

from dataclasses import dataclass
from decimal import Decimal

from app.domain.constants import (
    BMR_SEX_CONSTANT,
    GOAL_TARGETS,
    KCAL_FLOOR,
    KCAL_PER_G_CARBS,
    KCAL_PER_G_FAT,
    KCAL_PER_G_PROTEIN,
    PROTEIN_MAX_KCAL_SHARE,
    Goal,
    Sex,
)
from app.domain.rounding import round_half_up, round_int


@dataclass(frozen=True)
class NutritionTargets:
    bmr: Decimal  # 1 decimal
    tdee: int
    target_kcal: int
    protein_g: Decimal  # 1 decimal
    fat_g: Decimal
    carbs_g: Decimal


def bmr(sex: Sex, weight_kg: Decimal, height_cm: Decimal, age: int) -> Decimal:
    """Mifflin-St Jeor, unrounded."""
    return (
        Decimal(10) * weight_kg
        + Decimal("6.25") * height_cm
        - Decimal(5) * age
        + BMR_SEX_CONSTANT[sex]
    )


def tdee(bmr_kcal: Decimal, pal: Decimal) -> int:
    return round_int(bmr_kcal * pal)


def calculate_targets(
    sex: Sex,
    weight_kg: Decimal,
    height_cm: Decimal,
    age: int,
    pal: Decimal,
    goal: Goal,
) -> NutritionTargets:
    bmr_kcal = bmr(sex, weight_kg, height_cm, age)
    tdee_kcal = tdee(bmr_kcal, pal)

    kcal_factor, protein_per_kg, fat_share = GOAL_TARGETS[goal]
    target_kcal = max(round_int(tdee_kcal * kcal_factor), KCAL_FLOOR[sex])
    target = Decimal(target_kcal)

    protein = min(protein_per_kg * weight_kg, PROTEIN_MAX_KCAL_SHARE * target / KCAL_PER_G_PROTEIN)
    fat = fat_share * target / KCAL_PER_G_FAT
    carbs = (target - KCAL_PER_G_PROTEIN * protein - KCAL_PER_G_FAT * fat) / KCAL_PER_G_CARBS

    return NutritionTargets(
        bmr=round_half_up(bmr_kcal, 1),
        tdee=tdee_kcal,
        target_kcal=target_kcal,
        protein_g=round_half_up(protein, 1),
        fat_g=round_half_up(fat, 1),
        carbs_g=round_half_up(carbs, 1),
    )
