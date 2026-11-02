"""DB-04: the food seed passes the kcal rule of algorithms.md 0 and the portion rule, every
required meal slot has food for every diet type, the committed coverage report is current,
and the diet generator (algorithms.md 5) plans every goal, diet type and meals per day
from the seed. Needs no database."""

from functools import cache

import pytest

from app.db.food_check import (
    REPORT_NAME,
    coverage_gaps,
    food_infos,
    kcal_errors,
    portion_errors,
    read_foods,
    report,
)
from app.db.seed import SEED_DIR
from app.domain.constants import DietType, Goal
from app.domain.diet import generate_diet_plan
from tests.domain.test_diet import PROFILES, targets


@cache
def seed():
    return read_foods()


def test_committed_report_is_current():
    committed = (SEED_DIR / REPORT_NAME).read_text(encoding="utf-8")

    assert committed == report(), "run: uv run python -m app.db.food_check"


def test_every_food_passes_the_kcal_rule():
    assert kcal_errors(seed()) == []


def test_portions_are_multiples_of_the_step():
    assert portion_errors(seed()) == []


def test_every_required_slot_has_food_for_every_diet_type():
    assert coverage_gaps(seed()) == []


def test_the_checks_catch_a_wrong_row():
    row = dict(seed()[0], cals_per_100g="500", min_portion_g="55", portion_step_g="10")

    assert len(kcal_errors([row])) == 1
    assert "min_portion_g" in portion_errors([row])[0]


@pytest.mark.parametrize("profile", PROFILES, ids=["male-80kg", "female-60kg"])
@pytest.mark.parametrize("meals", [3, 4, 5])
@pytest.mark.parametrize("diet", list(DietType))
@pytest.mark.parametrize("goal", list(Goal))
def test_the_generator_plans_from_the_seed(goal, diet, meals, profile):
    plan = generate_diet_plan(
        goal, targets(profile, goal), meals, diet, frozenset(), frozenset(), food_infos(seed())
    )

    assert {m.day_index for m in plan.meals} == set(range(1, 8))
