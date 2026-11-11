"""Nutrition logs and the daily summary on PostgreSQL (DB-09; FR-A3, FR-R2 data).

The repository runs on the reference seed of app.db.seed; the expected values are
worked out from its values per 100 g. Skipped without PostgreSQL.
"""

import asyncio
import functools
import uuid
from collections.abc import AsyncIterator
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.repositories.nutrition_logs import (
    ClientUuidDeletedError,
    DuplicateFoodError,
    ItemIn,
    LogTooLargeError,
    Macros,
    NutritionLogIn,
    SqlNutritionLogUnitOfWork,
    UnknownFoodError,
    UnknownPlannedMealError,
    ZeroGramsError,
)
from app.db.seed import load
from app.db.session import database_url
from app.domain.constants import MealType
from tests.clock import today
from tests.db.test_repositories import TEST_DB, migrated_db  # noqa: F401  (fixture)

pytestmark = pytest.mark.anyio

TODAY = today()
CRAB = "Crab, cooked"  # 97 kcal, 19.4 g protein, 1.54 g fat, 0 g carbs per 100 g
YOGURT = "Greek yogurt, plain, whole milk"  # 97, 9, 5, 3.98
OIL = "Olive oil"  # 884, 0, 100, 0
INACTIVE = "Inactive test food"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@functools.cache
def _sync_engine():
    return create_engine(database_url().set(database=TEST_DB))


@pytest.fixture(scope="module", autouse=True)
def _close_sync_engine():
    yield
    if _sync_engine.cache_info().currsize:
        _sync_engine().dispose()
        _sync_engine.cache_clear()


def _rows(sql: str, **params) -> list:
    with _sync_engine().connect() as db:
        return db.execute(text(sql), params).all()


@pytest.fixture(scope="module")
def seeded(migrated_db):  # noqa: F811
    with _sync_engine().begin() as db:
        db.execute(
            text(
                "TRUNCATE app_user, muscle_group, injury_type, allergen, food_category, food_item"
                " RESTART IDENTITY CASCADE"
            )
        )
        load(db)
        db.execute(
            text(
                "INSERT INTO food_item (name, cals_per_100g, protein_per_100g, fat_per_100g,"
                " carbs_per_100g, diet_role, suitable_meal_types, default_portion_g,"
                " min_portion_g, max_portion_g, portion_step_g, is_active)"
                " VALUES (:n, 100, 10, 1, 10, 'other', '{snack}', 100, 10, 200, 10, false)"
            ),
            {"n": INACTIVE},
        )


@pytest.fixture
async def logs(seeded) -> AsyncIterator[SqlNutritionLogUnitOfWork]:
    with _sync_engine().begin() as db:
        db.execute(text("TRUNCATE app_user RESTART IDENTITY CASCADE"))
    engine = create_async_engine(database_url().set(database=TEST_DB))
    yield SqlNutritionLogUnitOfWork(async_sessionmaker(engine, expire_on_commit=False))
    await engine.dispose()


def _user(email: str = "ann@example.com") -> int:
    with _sync_engine().begin() as db:
        return db.execute(
            text(
                "INSERT INTO app_user (email, password_hash, name, surname)"
                " VALUES (:e, 'x', 'A', 'B') RETURNING id"
            ),
            {"e": email},
        ).scalar_one()


@functools.cache
def _food(name: str) -> int:
    return _rows("SELECT id FROM food_item WHERE name = :n", n=name)[0][0]


def _plan(user_id: int, status: str = "active", kcal: int = 2000) -> int:
    """A diet plan (2000 kcal, 150 g protein, 70 g fat, 200 g carbs by default) with one
    breakfast; returns the meal id."""
    with _sync_engine().begin() as db:
        plan_id = db.execute(
            text(
                "INSERT INTO diet_plan (user_id, name, goal, meals_per_day, start_date, end_date,"
                " daily_cal_goal, protein_goal, fat_goal, carbs_goal, status)"
                " VALUES (:u, 'Diet', 'maintenance', 3, :d, :d + 56, :k, 150, 70, 200,"
                " CAST(:s AS plan_status)) RETURNING id"
            ),
            {"u": user_id, "d": TODAY, "k": kcal, "s": status},
        ).scalar_one()
        return db.execute(
            text(
                "INSERT INTO meal (diet_plan_id, day_index, meal_type, meal_order, planned_time,"
                " planned_cals, planned_protein, planned_fat, planned_carbs)"
                " VALUES (:p, 1, 'breakfast', 1, '08:00', 500, 30, 15, 60) RETURNING id"
            ),
            {"p": plan_id},
        ).scalar_one()


def _items(*items: tuple[str | int, str]) -> tuple[ItemIn, ...]:
    return tuple(
        ItemIn(food if isinstance(food, int) else _food(food), Decimal(grams))
        for food, grams in items
    )


def _log(*items, client_uuid=None, day=TODAY, planned_meal_id=None, hunger=(None, None)):
    return NutritionLogIn(
        client_uuid=client_uuid,
        log_date=day,
        meal_type=MealType.BREAKFAST,
        planned_meal_id=planned_meal_id,
        hunger_level_before=hunger[0],
        hunger_level_after=hunger[1],
        items=_items(*items),
    )


async def _create(logs, user_id, log):
    async with logs() as store:
        return await store.create(user_id, log)


def _count(table: str) -> int:
    return _rows(f"SELECT count(*) FROM {table}")[0][0]


# ---------------------------------------------------------------- totals and rounding


async def test_totals_are_the_sum_of_the_rounded_items(logs):
    ann = _user()

    saved = await _create(logs, ann, _log((CRAB, "12.5"), (YOGURT, "12.5")))

    # items: crab 12.13 kcal, 2.43 / 0.19 / 0.00 g; yogurt 12.13 kcal, 1.13 / 0.63 / 0.50 g;
    # the unrounded sums would give 24.25 kcal and 3.55 g protein
    assert saved.totals == Macros(
        Decimal("24.26"), Decimal("3.56"), Decimal("0.82"), Decimal("0.5")
    )
    stored = _rows(
        "SELECT actual_cals, actual_protein, actual_fat, actual_carbs FROM nutrition_log"
    )
    assert stored == [(Decimal("24.26"), Decimal("3.56"), Decimal("0.82"), Decimal("0.50"))]
    assert {(item.name, item.grams) for item in saved.items} == {
        (CRAB, Decimal("12.5")),
        (YOGURT, Decimal("12.5")),
    }


@pytest.mark.parametrize(
    ("food", "grams", "stored_grams", "kcal", "protein"),
    [
        (CRAB, "12.45", "12.5", "12.13", "2.43"),  # half even: 12.4 g, 12.03 kcal
        (CRAB, "12.5", "12.5", "12.13", "2.43"),  # 12.125 and 2.425: half even 12.12, 2.42
        (YOGURT, "12.5", "12.5", "12.13", "1.13"),  # 12.125 and 1.125
        (CRAB, "0.05", "0.1", "0.1", "0.02"),  # half even: 0.0 g
    ],
)
async def test_grams_and_item_values_round_half_up(logs, food, grams, stored_grams, kcal, protein):
    saved = await _create(logs, _user(), _log((food, grams)))

    assert saved.items[0].grams == Decimal(stored_grams)
    assert (saved.actual_cals, saved.actual_protein) == (Decimal(kcal), Decimal(protein))


async def test_up_to_9999_99_kcal_is_stored_and_above_is_too_large(logs):
    ann = _user()

    saved = await _create(logs, ann, _log((OIL, "1131.2")))  # 9999.808 kcal
    assert saved.actual_cals == Decimal("9999.81")

    with pytest.raises(LogTooLargeError):
        await _create(logs, ann, _log((OIL, "1131.3")))  # 10000.692 kcal
    assert _count("nutrition_log") == 1


@pytest.mark.parametrize(
    ("items", "error", "index"),
    [
        (((CRAB, "10"), (YOGURT, "10"), (CRAB, "20")), DuplicateFoodError, 2),
        (((CRAB, "10"), (999999, "10")), UnknownFoodError, 1),
        (((INACTIVE, "10"),), UnknownFoodError, 0),
        (((YOGURT, "10"), (CRAB, "0.04")), ZeroGramsError, 1),
    ],
)
async def test_invalid_items_raise_with_their_index_and_store_nothing(logs, items, error, index):
    with pytest.raises(error) as caught:
        await _create(logs, _user(), _log(*items))

    assert caught.value.index == index
    assert _count("nutrition_log") == 0


# ---------------------------------------------------------------- client_uuid


async def test_a_repeated_client_uuid_stores_one_log_per_user(logs):
    ann, bob = _user(), _user("bob@example.com")
    client_uuid = uuid.uuid4()

    first = await _create(logs, ann, _log((CRAB, "100"), client_uuid=client_uuid))
    again = await _create(logs, ann, _log((YOGURT, "200"), client_uuid=client_uuid))
    bobs = await _create(logs, bob, _log((YOGURT, "200"), client_uuid=client_uuid))

    assert again == first  # the first answer, nothing applied twice
    assert bobs.id != first.id
    assert (bobs.user_id, bobs.client_uuid, bobs.items[0].name) == (bob, client_uuid, YOGURT)
    assert _count("nutrition_log") == 2
    assert _count("nutrition_log_food_item") == 2


async def test_concurrent_creates_with_one_client_uuid_store_one_log(logs):
    ann = _user()
    client_uuid = uuid.uuid4()

    first, second = await asyncio.gather(
        _create(logs, ann, _log((CRAB, "100"), client_uuid=client_uuid)),
        _create(logs, ann, _log((CRAB, "100"), client_uuid=client_uuid)),
    )

    assert first == second
    assert _count("nutrition_log") == 1


async def test_the_client_uuid_of_a_deleted_log_is_a_conflict(logs):
    ann = _user()
    client_uuid = uuid.uuid4()
    saved = await _create(logs, ann, _log((CRAB, "100"), client_uuid=client_uuid))
    async with logs() as store:
        assert await store.soft_delete(ann, saved.id)

    with pytest.raises(ClientUuidDeletedError):
        await _create(logs, ann, _log((CRAB, "100"), client_uuid=client_uuid))
    assert _count("nutrition_log") == 1


# ---------------------------------------------------------------- planned meal and ownership


async def test_the_planned_meal_must_belong_to_one_of_the_users_diet_plans(logs):
    ann, bob = _user(), _user("bob@example.com")
    archived_meal = _plan(ann, status="archived")
    bobs_meal = _plan(bob)

    saved = await _create(logs, ann, _log((CRAB, "100"), planned_meal_id=archived_meal))
    assert saved.planned_meal_id == archived_meal

    for meal_id in (bobs_meal, 999999):
        with pytest.raises(UnknownPlannedMealError):
            await _create(logs, ann, _log((CRAB, "100"), planned_meal_id=meal_id))
        with pytest.raises(UnknownPlannedMealError):
            async with logs() as store:
                await store.update(ann, saved.id, {"planned_meal_id": meal_id}, None)
    async with logs() as store:
        assert (await store.get(ann, saved.id)).planned_meal_id == archived_meal


async def test_another_users_log_is_never_read_or_written(logs):
    ann, bob = _user(), _user("bob@example.com")
    anns = await _create(logs, ann, _log((CRAB, "100")))

    async with logs() as store:
        assert await store.get(bob, anns.id) is None
        assert await store.list_logs(bob, None, None, 20, 0) == (0, [])
        assert await store.update(bob, anns.id, {"hunger_level_after": 9}, None) is None
        assert await store.update(bob, anns.id, {}, _items((OIL, "50"))) is None
        assert not await store.soft_delete(bob, anns.id)
        assert (await store.daily_summary(bob, TODAY)).logs == ()

    async with logs() as store:
        assert await store.get(ann, anns.id) == anns


async def test_a_deleted_log_is_never_returned(logs):
    ann = _user()
    saved = await _create(logs, ann, _log((CRAB, "100")))

    async with logs() as store:
        assert await store.soft_delete(ann, saved.id)
    async with logs() as store:
        assert await store.get(ann, saved.id) is None
        assert await store.list_logs(ann, None, None, 20, 0) == (0, [])
        assert await store.update(ann, saved.id, {"hunger_level_after": 9}, None) is None
        assert not await store.soft_delete(ann, saved.id)
        assert (await store.daily_summary(ann, TODAY)).logs == ()


# ---------------------------------------------------------------- update and list


async def test_patch_with_items_replaces_them_and_recomputes_the_totals(logs):
    ann = _user()
    meal = _plan(ann)
    saved = await _create(logs, ann, _log((CRAB, "100"), (OIL, "10"), planned_meal_id=meal))

    async with logs() as store:
        patched = await store.update(ann, saved.id, {}, _items((YOGURT, "12.5")))
    assert [(item.name, item.grams) for item in patched.items] == [(YOGURT, Decimal("12.5"))]
    assert patched.totals == Macros(
        Decimal("12.13"), Decimal("1.13"), Decimal("0.63"), Decimal("0.5")
    )
    assert _count("nutrition_log_food_item") == 1

    changes = {"meal_type": MealType.SNACK, "hunger_level_after": 3, "planned_meal_id": None}
    async with logs() as store:
        fields_only = await store.update(ann, saved.id, changes, None)
    assert (fields_only.meal_type, fields_only.hunger_level_after) == (MealType.SNACK, 3)
    assert fields_only.planned_meal_id is None
    assert (fields_only.items, fields_only.totals) == (patched.items, patched.totals)

    with pytest.raises(DuplicateFoodError):
        async with logs() as store:
            await store.update(ann, saved.id, {}, _items((CRAB, "10"), (CRAB, "20")))
    async with logs() as store:
        assert await store.get(ann, saved.id) == fields_only  # nothing of the failed patch


async def test_history_is_newest_first_filtered_and_paginated(logs):
    ann = _user()
    for days_ago in (3, 1, 2, 1):
        await _create(logs, ann, _log((CRAB, "100"), day=TODAY - timedelta(days_ago)))

    async with logs() as store:
        total, page = await store.list_logs(ann, None, None, 3, 0)
        _, rest = await store.list_logs(ann, None, None, 3, 3)
        ranged_total, ranged = await store.list_logs(
            ann, TODAY - timedelta(2), TODAY - timedelta(2), 20, 0
        )

    assert total == 4
    assert [(TODAY - log.log_date).days for log in page] == [1, 1, 2]
    assert page[0].id > page[1].id  # same day: newest id first
    assert [(TODAY - log.log_date).days for log in rest] == [3]
    assert (ranged_total, [(TODAY - log.log_date).days for log in ranged]) == (1, [2])


# ---------------------------------------------------------------- daily summary


async def test_daily_summary_against_the_active_plan_ignores_empty_hunger(logs):
    ann, bob = _user(), _user("bob@example.com")
    _plan(ann)  # 2000 kcal, 150 / 70 / 200 g
    _plan(ann, status="draft", kcal=3000)
    crab = await _create(logs, ann, _log((CRAB, "12.5"), hunger=(4, None)))
    yogurt = await _create(logs, ann, _log((YOGURT, "12.5")))
    oil = await _create(logs, ann, _log((OIL, "10"), hunger=(7, 5)))
    deleted = await _create(logs, ann, _log((OIL, "100"), hunger=(1, 1)))
    await _create(logs, ann, _log((OIL, "100"), day=TODAY - timedelta(1), hunger=(1, 1)))
    await _create(logs, bob, _log((OIL, "100"), hunger=(1, 1)))
    async with logs() as store:
        await store.soft_delete(ann, deleted.id)

    async with logs() as store:
        summary = await store.daily_summary(ann, TODAY)

    assert summary.date == TODAY
    assert [log.id for log in summary.logs] == [crab.id, yogurt.id, oil.id]
    # 12.13 + 12.13 + 88.40 kcal; 2.43 + 1.13 + 0; 0.19 + 0.63 + 10.00; 0 + 0.50 + 0
    totals = Macros(Decimal("112.66"), Decimal("3.56"), Decimal("10.82"), Decimal("0.5"))
    assert summary.totals == totals
    assert summary.targets == Macros(Decimal(2000), Decimal(150), Decimal(70), Decimal(200))
    assert summary.remaining == Macros(
        Decimal("1887.34"), Decimal("146.44"), Decimal("59.18"), Decimal("199.5")
    )
    assert (summary.avg_hunger_before, summary.avg_hunger_after) == (Decimal("5.5"), Decimal(5))


async def test_daily_summary_without_an_active_plan_or_logs(logs):
    ann = _user()
    _plan(ann, status="archived")

    async with logs() as store:
        empty = await store.daily_summary(ann, TODAY)

    assert (empty.targets, empty.remaining, empty.logs) == (None, None, ())
    assert empty.totals == Macros(Decimal(0), Decimal(0), Decimal(0), Decimal(0))
    assert (empty.avg_hunger_before, empty.avg_hunger_after) == (None, None)


async def test_remaining_goes_negative_above_the_target(logs):
    ann = _user()
    _plan(ann, kcal=50)
    await _create(logs, ann, _log((OIL, "10")))  # 88.40 kcal, 10 g fat

    async with logs() as store:
        summary = await store.daily_summary(ann, TODAY)

    assert summary.remaining == Macros(Decimal("-38.4"), Decimal(150), Decimal(60), Decimal(200))
    assert (summary.avg_hunger_before, summary.avg_hunger_after) == (None, None)
