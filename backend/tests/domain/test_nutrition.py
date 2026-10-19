"""Test vectors of algorithms.md section 2 (FR-P4, FR-P5)."""

from decimal import Decimal as D

import pytest

from app.domain.constants import Goal, Sex
from app.domain.nutrition import calculate_targets

# fmt: off
VECTORS = [
    # sex, kg, cm, age, PAL, goal -> bmr, tdee, target, protein, fat, carbs
    (Sex.MALE, "80", "180", 25, "1.55", Goal.MUSCLE_GAIN, "1805.0", 2798, 3078, "144.0", "85.5", "433.1"),
    (Sex.FEMALE, "60", "165", 30, "1.375", Goal.WEIGHT_LOSS, "1320.3", 1815, 1452, "120.0", "48.4", "134.1"),
    # kcal floor applies
    (Sex.FEMALE, "55", "155", 60, "1.2", Goal.WEIGHT_LOSS, "1057.8", 1269, 1200, "105.0", "40.0", "105.0"),
    # 35 % protein cap applies
    (Sex.MALE, "120", "185", 35, "1.375", Goal.WEIGHT_LOSS, "2186.3", 3006, 2405, "210.4", "80.2", "210.4"),
]
# fmt: on


@pytest.mark.parametrize(
    ("sex", "kg", "cm", "age", "pal", "goal", "bmr", "tdee", "target", "protein", "fat", "carbs"),
    VECTORS,
)
def test_targets_match_algorithms_vectors(
    sex, kg, cm, age, pal, goal, bmr, tdee, target, protein, fat, carbs
):
    result = calculate_targets(sex, D(kg), D(cm), age, D(pal), goal)

    assert result.bmr == D(bmr)
    assert result.tdee == tdee
    assert result.target_kcal == target
    assert result.protein_g == D(protein)
    assert result.fat_g == D(fat)
    assert result.carbs_g == D(carbs)


def test_other_sex_uses_average_constant():
    # 10*70 + 6.25*170 - 5*30 - 78 = 1534.5
    result = calculate_targets(Sex.OTHER, D("70"), D("170"), 30, D("1.2"), Goal.MAINTENANCE)
    assert result.bmr == D("1534.5")
    assert result.tdee == 1841  # 1841.4


def test_male_floor_is_1500():
    # BMR 10*40 + 6.25*150 - 5*90 + 5 = 892.5, TDEE 1071, 0.8 * 1071 = 857 -> floor 1500
    result = calculate_targets(Sex.MALE, D("40"), D("150"), 90, D("1.2"), Goal.WEIGHT_LOSS)
    assert result.target_kcal == 1500
