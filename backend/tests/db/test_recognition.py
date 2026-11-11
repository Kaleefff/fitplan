"""Label matching and confirm of meal recognition (DB-08; FR-N2-N4; algorithms.md 11).

PostgreSQL runs on the reference seed of app.db.seed; A-01 has not filled
`recognition_label` yet, so `seeded` sets it on a few foods. MongoDB uses the throwaway
`buffer_db` of tests/db/conftest.py. Skipped without PostgreSQL or MongoDB.
"""

import asyncio
import functools
import math
import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from bson import ObjectId
from pymongo.errors import PyMongoError
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.db.enums import MealType as DbMealType
from app.db.models import NutritionLog, NutritionLogFoodItem
from app.db.repositories.meal_recognitions import (
    Candidate,
    MealRecognition,
    MongoMealRecognitionRepository,
    Nutrition,
    RecognisedItem,
    RecognitionModel,
    utc_now,
)
from app.db.repositories.nutrition_logs import (
    DuplicateFoodError,
    ItemIn,
    Macros,
    NutritionLogIn,
    SqlNutritionLogStore,
    UnknownFoodError,
    ZeroGramsError,
)
from app.db.repositories.recognition import (
    Detection,
    FoodNotAvailableError,
    NoItemsError,
    RecognitionConfirmer,
    SqlRecognitionMatcher,
    UnmatchedItemError,
    confirm_client_uuid,
)
from app.db.seed import load
from app.db.session import database_url
from app.domain.constants import RECOGNITION_LOW_CONFIDENCE, MealType
from tests.db.test_repositories import TEST_DB, migrated_db  # noqa: F401  (fixture)

pytestmark = pytest.mark.anyio

TODAY = date.today()
CRAB = "Crab, cooked"  # 97 kcal, 19.4 g protein, 1.54 g fat, 0 g carbs; default 150 g; Crustaceans
SHRIMP = "Shrimp, cooked"  # Crustaceans
YOGURT = "Greek yogurt, plain, whole milk"  # 97, 9, 5, 3.98; Milk, Lactose
OIL = "Olive oil"  # 884, 0, 100, 0; no allergens
INACTIVE = "Inactive test food"
LABELS = {
    CRAB: "crab",
    SHRIMP: "shrimp",
    YOGURT: "Greek Yogurt ",  # stored with capitals and a trailing space
    OIL: "olive oil",
    INACTIVE: "inactive food",
}
UNKNOWN = "dragon fruit"


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


def _execute(sql: str, **params) -> None:
    with _sync_engine().begin() as db:
        db.execute(text(sql), params)


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
        for name, label in LABELS.items():
            db.execute(
                text("UPDATE food_item SET recognition_label = :l WHERE name = :n"),
                {"l": label, "n": name},
            )


@pytest.fixture
async def engine(seeded) -> AsyncIterator[AsyncEngine]:
    _execute("TRUNCATE app_user RESTART IDENTITY CASCADE")
    engine = create_async_engine(database_url().set(database=TEST_DB))
    yield engine
    await engine.dispose()


@pytest.fixture
def sessions(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def matcher(sessions) -> SqlRecognitionMatcher:
    return SqlRecognitionMatcher(sessions)


class Clock:
    """The real time plus `offset`: documents expire in the real future (no TTL mid-test)."""

    def __init__(self) -> None:
        self.offset = timedelta(0)

    def __call__(self) -> datetime:
        return utc_now() + self.offset


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def buffer(buffer_db, clock) -> MongoMealRecognitionRepository:
    return MongoMealRecognitionRepository(buffer_db, clock=clock)


@pytest.fixture
def confirmer(sessions, buffer) -> RecognitionConfirmer:
    return RecognitionConfirmer(sessions, buffer)


def _user(email: str = "ann@example.com", allergens: tuple[str, ...] = ()) -> int:
    with _sync_engine().begin() as db:
        user_id = db.execute(
            text(
                "INSERT INTO app_user (email, password_hash, name, surname)"
                " VALUES (:e, 'x', 'A', 'B') RETURNING id"
            ),
            {"e": email},
        ).scalar_one()
        for name in allergens:
            db.execute(
                text(
                    "INSERT INTO user_allergen (user_id, allergen_id)"
                    " SELECT :u, id FROM allergen WHERE name = :n"
                ),
                {"u": user_id, "n": name},
            )
    return user_id


@functools.cache
def _food(name: str) -> int:
    return _rows("SELECT id FROM food_item WHERE name = :n", n=name)[0][0]


def _count(table: str) -> int:
    return _rows(f"SELECT count(*) FROM {table}")[0][0]


def _detect(label: str, confidence: float = 0.8, grams: float | None = 100.0, *alternatives):
    return Detection(label, confidence, grams, tuple(alternatives))


async def _one(matcher, user_id, detection: Detection) -> RecognisedItem:
    items, _ = await matcher.match(user_id, [detection])
    assert len(items) == 1
    return items[0]


# ================================================================ matching


async def test_an_unknown_label_gives_no_food_keeps_grams_and_zero_nutrition(matcher):
    ann = _user(allergens=("Crustaceans", "Milk"))

    items, overall = await matcher.match(ann, [_detect(UNKNOWN, 0.6, 123.45, ("crab", 0.2))])

    assert items == (
        RecognisedItem(
            name=UNKNOWN,
            food_item_id=None,
            candidates=(Candidate(UNKNOWN, 0.6, None), Candidate("crab", 0.2, _food(CRAB))),
            confidence=0.6,
            low_confidence=False,
            grams=123.5,  # the model's estimate, rounded half up to 0.1
            nutrition=Nutrition(0.0, 0.0, 0.0, 0.0),
            allergy_warning=False,
            corrected=False,
        ),
    )
    assert overall == 0.6


@pytest.mark.parametrize(
    ("label", "food"),
    [("crab", CRAB), ("  CRAB  ", CRAB), ("Crab", CRAB), ("greek yogurt", YOGURT)],
)
async def test_labels_match_after_trimming_and_lower_casing_both_sides(matcher, label, food):
    item = await _one(matcher, _user(), _detect(label))

    assert item.food_item_id == _food(food)
    assert item.name == label  # the model's label as given
    assert item.candidates[0] == Candidate(label, 0.8, _food(food))


async def test_an_inactive_food_is_not_matched(matcher):
    item = await _one(matcher, _user(), _detect("inactive food", grams=None))

    assert (item.food_item_id, item.grams, item.nutrition) == (None, 0.0, Nutrition(0, 0, 0, 0))


async def test_two_active_foods_with_one_normalised_label_the_lowest_id_wins(matcher):
    first, second = sorted([_food("Peanuts, roasted"), _food("Peanut butter")])
    _execute("UPDATE food_item SET recognition_label = 'Peanut' WHERE id = :i", i=second)
    _execute("UPDATE food_item SET recognition_label = ' peanut' WHERE id = :i", i=first)
    try:
        item = await _one(matcher, _user(), _detect("PEANUT"))
    finally:
        _execute(
            "UPDATE food_item SET recognition_label = NULL WHERE id IN (:a, :b)", a=first, b=second
        )

    assert item.food_item_id == first


@pytest.mark.parametrize("grams", [None, 0.0, -5.0, math.nan, math.inf, -math.inf])
async def test_a_missing_non_positive_or_non_finite_estimate_falls_back(matcher, grams):
    ann = _user()

    items, _ = await matcher.match(
        ann, [_detect("crab", grams=grams), _detect(UNKNOWN, grams=grams)]
    )

    crab, unknown = items
    assert crab.grams == 150.0  # default_portion_g
    assert crab.nutrition == Nutrition(145.5, 29.1, 2.31, 0.0)
    assert unknown.grams == 0.0
    assert unknown.nutrition == Nutrition(0.0, 0.0, 0.0, 0.0)


@pytest.mark.parametrize(
    ("grams", "stored"),
    [
        (12.45, 12.5),  # Decimal(12.45) would be 12.4499... and round down
        (12.35, 12.4),
        (12.44, 12.4),
        (0.05, 0.1),
        (0.04, 0.0),  # positive, so no fallback; confirm rejects it later
        (99999.9, 99999.9),
        (99999.95, 99999.9),  # half up would give 100000.0
        (1e30, 99999.9),
    ],
)
async def test_grams_round_half_up_to_0_1_and_clamp_to_99999_9(matcher, grams, stored):
    item = await _one(matcher, _user(), _detect("crab", grams=grams))

    assert item.grams == stored


async def test_nutrition_is_per_100_g_times_grams_rounded_half_up(matcher):
    item = await _one(matcher, _user(), _detect("crab", grams=12.5))

    # 12.125 kcal and 2.425 g protein: half up, not half even
    assert item.nutrition == Nutrition(12.13, 2.43, 0.19, 0.0)


async def test_detections_of_one_food_are_merged_unmatched_never(matcher):
    ann = _user()
    detections = [
        _detect("crab", 0.5, 100.04, ("shrimp", 0.3)),
        _detect("greek yogurt", 0.9, 50.0),
        _detect(UNKNOWN, 0.4, 80.0),
        _detect(" Crab", 0.8, 30.04, ("olive oil", 0.1)),  # the most confident crab
        _detect("crab", 0.8, None),  # a tie: the earlier one stays; grams fall back to 150
        _detect(UNKNOWN, 0.6, 20.0),  # same label, still its own item
    ]

    items, overall = await matcher.match(ann, detections)

    assert [(i.name, i.food_item_id, i.grams) for i in items] == [
        (" Crab", _food(CRAB), 280.1),  # 100.04 + 30.04 + 150 summed raw, then rounded once
        ("greek yogurt", _food(YOGURT), 50.0),
        (UNKNOWN, None, 80.0),
        (UNKNOWN, None, 20.0),
    ]
    crab = items[0]
    assert crab.confidence == 0.8
    assert crab.candidates == (
        Candidate(" Crab", 0.8, _food(CRAB)),
        Candidate("olive oil", 0.1, _food(OIL)),
    )
    assert crab.nutrition == Nutrition(271.70, 54.34, 4.31, 0.0)  # for 280.1 g
    assert overall == 0.9  # the highest item confidence
    assert all(not item.corrected for item in items)


async def test_merging_keeps_the_low_confidence_of_the_winning_detection(matcher):
    items, _ = await matcher.match(
        _user(), [_detect("crab", 0.1, 10.0), _detect("crab", 0.35, 10.0)]
    )

    assert [(i.confidence, i.low_confidence, i.grams) for i in items] == [(0.35, False, 20.0)]


@pytest.mark.parametrize(
    ("confidence", "low"), [(0.0, True), (0.2999, True), (0.30, False), (1.0, False)]
)
async def test_low_confidence_is_strictly_below_0_30(matcher, confidence, low):
    assert RECOGNITION_LOW_CONFIDENCE == 0.30
    ann = _user()

    items, _ = await matcher.match(ann, [_detect("crab", confidence), _detect(UNKNOWN, confidence)])

    assert [item.low_confidence for item in items] == [low, low]


async def test_allergy_warning_when_the_food_shares_an_allergen_with_the_user(matcher):
    ann = _user(allergens=("Crustaceans",))
    bob = _user("bob@example.com")
    detections = [_detect("crab"), _detect("greek yogurt"), _detect("olive oil"), _detect(UNKNOWN)]

    anns, _ = await matcher.match(ann, detections)
    bobs, _ = await matcher.match(bob, detections)

    assert [item.allergy_warning for item in anns] == [True, False, False, False]
    assert [item.allergy_warning for item in bobs] == [False, False, False, False]


async def test_no_detections_give_no_items_and_overall_confidence_0(matcher):
    assert await matcher.match(_user(), []) == ((), 0.0)


async def test_every_candidate_gets_its_own_food_and_at_most_k_are_kept(matcher):
    detection = _detect("crab", 0.7, 100.0, ("shrimp", 0.2), (UNKNOWN, 0.05), ("olive oil", 0.01))

    item = await _one(matcher, _user(), detection)

    assert item.candidates == (
        Candidate("crab", 0.7, _food(CRAB)),
        Candidate("shrimp", 0.2, _food(SHRIMP)),
        Candidate(UNKNOWN, 0.05, None),
    )  # K = 3: the fourth candidate is dropped


async def test_match_runs_two_queries_whatever_the_number_of_items(matcher, engine):
    ann = _user(allergens=("Crustaceans",))
    statements: list[str] = []
    listener = lambda *args: statements.append(args[2])  # noqa: E731
    event.listen(engine.sync_engine, "before_cursor_execute", listener)
    try:
        items, _ = await matcher.match(
            ann,
            [
                _detect("crab", 0.5, 10.0, ("shrimp", 0.4)),
                _detect("greek yogurt"),
                _detect("olive oil", 0.6, 5.0, ("crab", 0.1), ("shrimp", 0.1)),
                _detect("shrimp"),
                _detect(UNKNOWN),
                _detect("crab"),
            ],
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", listener)

    assert len(items) == 5
    assert len(statements) == 2  # foods of all labels, the user's allergens


# ---------------------------------------------------------------- price_item


async def test_price_item_rounds_clamps_and_recalculates(matcher):
    ann = _user(allergens=("Milk",))

    yogurt = await matcher.price_item(ann, _food(YOGURT), 12.45)
    crab = await matcher.price_item(ann, _food(CRAB), Decimal("99999.95"))

    assert (yogurt.food_item_id, yogurt.name, yogurt.grams) == (_food(YOGURT), YOGURT, 12.5)
    assert yogurt.nutrition == Nutrition(12.13, 1.13, 0.63, 0.5)
    assert yogurt.allergy_warning is True
    assert (crab.grams, crab.allergy_warning) == (99999.9, False)


@pytest.mark.parametrize("food", [INACTIVE, 999999])
async def test_price_item_rejects_an_inactive_or_unknown_food(matcher, food):
    food_id = food if isinstance(food, int) else _food(food)

    with pytest.raises(FoodNotAvailableError) as caught:
        await matcher.price_item(_user(), food_id, 100)

    assert caught.value.food_item_id == food_id


# ================================================================ confirm


BOGUS = Nutrition(kcal=1.0, protein=1.0, fat=1.0, carbs=1.0)  # never copied to the log


def _item(food: str | int | None, grams: float = 100.0, corrected: bool = False) -> RecognisedItem:
    food_id = food if food is None or isinstance(food, int) else _food(food)
    return RecognisedItem(
        name="label",
        food_item_id=food_id,
        candidates=(Candidate("label", 0.5, food_id),),
        confidence=0.5,
        low_confidence=False,
        grams=grams,
        nutrition=BOGUS,
        allergy_warning=False,
        corrected=corrected,
    )


async def _recognition(
    buffer, user_id: int, items, overall: float = 0.5, meal_type=DbMealType.LUNCH
) -> MealRecognition:
    return await buffer.create(
        user_id=user_id,
        meal_type=meal_type,
        photo_url=f"meals/{user_id}/{uuid.uuid4()}.jpg",
        model=RecognitionModel(name="gemini", version="test"),
        overall_confidence=overall,
        items=items,
    )


async def test_confirm_stores_the_log_and_its_items_then_deletes_the_document(
    matcher, confirmer, buffer
):
    ann = _user()
    items, overall = await matcher.match(
        ann, [_detect("crab", 0.865, 12.5), _detect("greek yogurt", 0.4, 12.5)]
    )
    doc = await _recognition(buffer, ann, items, overall)

    log = await confirmer.confirm(ann, doc.id, TODAY - timedelta(1), 3, 7)

    assert log.user_id == ann
    assert log.client_uuid == confirm_client_uuid(doc.id)
    assert (log.log_date, log.meal_type, log.planned_meal_id) == (
        TODAY - timedelta(1),
        MealType.LUNCH,
        None,
    )
    assert (log.hunger_level_before, log.hunger_level_after) == (3, 7)
    assert log.meal_photo_url == doc.photo_url  # unchanged, relative
    assert log.ai_confidence == Decimal("0.87")  # 0.865 half up (half even: 0.86)
    assert log.ai_was_edited is False
    assert {(item.food_item_id, item.grams) for item in log.items} == {
        (_food(CRAB), Decimal("12.5")),
        (_food(YOGURT), Decimal("12.5")),
    }
    # crab 12.13 / 2.43 / 0.19 / 0; yogurt 12.13 / 1.13 / 0.63 / 0.50: the sum of the items
    assert log.totals == Macros(Decimal("24.26"), Decimal("3.56"), Decimal("0.82"), Decimal("0.5"))
    stored = _rows(
        "SELECT meal_photo_url, ai_confidence, ai_was_edited, actual_cals FROM nutrition_log"
    )
    assert stored == [(doc.photo_url, Decimal("0.87"), False, Decimal("24.26"))]
    assert _count("nutrition_log_food_item") == 2
    assert await buffer.get(ann, doc.id) is None


async def test_confirm_recalculates_nutrition_from_the_food_not_the_document(confirmer, buffer):
    ann = _user()
    doc = await _recognition(buffer, ann, [_item(CRAB, 12.5)])  # the document says 1 kcal

    log = await confirmer.confirm(ann, doc.id, TODAY, None, None)

    assert log.totals == Macros(Decimal("12.13"), Decimal("2.43"), Decimal("0.19"), Decimal(0))


@pytest.mark.parametrize(
    ("corrected", "edited"),
    [((False, False), False), ((False, True), True), ((True, True), True)],
)
async def test_ai_was_edited_means_any_item_corrected(confirmer, buffer, corrected, edited):
    ann = _user()
    items = [_item(CRAB, corrected=corrected[0]), _item(OIL, 10.0, corrected=corrected[1])]
    doc = await _recognition(buffer, ann, items)

    log = await confirmer.confirm(ann, doc.id, TODAY, None, None)

    assert log.ai_was_edited is edited


async def test_a_removed_item_does_not_count_as_edited(confirmer, buffer):
    ann = _user()
    doc = await _recognition(buffer, ann, [_item(CRAB), _item(OIL, 10.0)])
    await buffer.update_items(ann, doc.id, [_item(CRAB)])  # B-20 removed the oil

    log = await confirmer.confirm(ann, doc.id, TODAY, None, None)

    assert log.ai_was_edited is False
    assert [item.food_item_id for item in log.items] == [_food(CRAB)]


@pytest.mark.parametrize(
    ("items", "error", "index"),
    [
        ((), NoItemsError, None),
        (((CRAB, 100.0), (None, 80.0)), UnmatchedItemError, 1),
        (((None, 0.0),), UnmatchedItemError, 0),
        (((CRAB, 100.0), (YOGURT, 50.0), (CRAB, 20.0)), DuplicateFoodError, 2),
        (((CRAB, 100.0), (YOGURT, 0.04)), ZeroGramsError, 1),
        (((CRAB, 100.0), (INACTIVE, 50.0)), UnknownFoodError, 1),  # inactive since recognition
    ],
)
async def test_confirm_errors_carry_the_item_index_and_change_nothing(
    confirmer, buffer, items, error, index
):
    ann = _user()
    doc = await _recognition(buffer, ann, [_item(food, grams) for food, grams in items])

    with pytest.raises(error) as caught:
        await confirmer.confirm(ann, doc.id, TODAY, None, None)

    if index is not None:
        assert caught.value.index == index
    assert _count("nutrition_log") == _count("nutrition_log_food_item") == 0
    assert await buffer.get(ann, doc.id) == doc


async def test_an_expired_missing_or_other_users_document_gives_none(confirmer, buffer, clock):
    ann, bob = _user(), _user("bob@example.com")
    anns = await _recognition(buffer, ann, [_item(CRAB)])
    expiring = await _recognition(buffer, ann, [_item(CRAB)])

    assert await confirmer.confirm(bob, anns.id, TODAY, None, None) is None
    assert await confirmer.confirm(ann, str(ObjectId()), TODAY, None, None) is None
    assert await confirmer.confirm(ann, "not an id", TODAY, None, None) is None
    clock.offset = expiring.expires_at - clock() + timedelta(seconds=1)
    assert await confirmer.confirm(ann, expiring.id, TODAY, None, None) is None

    assert _count("nutrition_log") == 0
    clock.offset = timedelta(0)
    assert await buffer.get(ann, anns.id) == anns  # bob's attempt left ann's document alone
    assert (await confirmer.confirm(ann, anns.id, TODAY, None, None)).user_id == ann


async def test_a_failure_inside_the_transaction_leaves_postgresql_and_the_document(
    confirmer, buffer, monkeypatch
):
    """Done criterion: the failure comes after the log row and its items are flushed."""
    ann = _user()
    doc = await _recognition(buffer, ann, [_item(CRAB), _item(OIL, 10.0)])
    insert_items = SqlNutritionLogStore._insert_items
    flushed: list[tuple[int, int]] = []

    async def insert_then_fail(self, log_id, grams):
        await insert_items(self, log_id, grams)
        flushed.append(
            (
                await self._session.scalar(select(func.count()).select_from(NutritionLog)),
                await self._session.scalar(select(func.count()).select_from(NutritionLogFoodItem)),
            )
        )
        raise RuntimeError("forced failure")

    monkeypatch.setattr(SqlNutritionLogStore, "_insert_items", insert_then_fail)

    with pytest.raises(RuntimeError, match="forced failure"):
        await confirmer.confirm(ann, doc.id, TODAY, None, None)

    assert flushed == [(1, 2)]  # the rows existed inside the transaction
    assert _count("nutrition_log") == _count("nutrition_log_food_item") == 0
    assert await buffer.get(ann, doc.id) == doc


async def test_a_failed_document_delete_is_retried_with_the_same_log(
    confirmer, buffer, monkeypatch
):
    ann = _user()
    doc = await _recognition(buffer, ann, [_item(CRAB)])

    async def failing_delete(user_id, recognition_id):
        raise PyMongoError("MongoDB went away")

    with monkeypatch.context() as patch:
        patch.setattr(buffer, "delete", failing_delete)
        with pytest.raises(PyMongoError):
            await confirmer.confirm(ann, doc.id, TODAY, 2, None)

    assert _count("nutrition_log") == 1  # committed before the delete
    assert await buffer.get(ann, doc.id) == doc  # and the document stays

    retried = await confirmer.confirm(ann, doc.id, TODAY + timedelta(1), 9, 9)

    assert _count("nutrition_log") == 1
    assert (retried.log_date, retried.hunger_level_before) == (TODAY, 2)  # the first log
    assert await buffer.get(ann, doc.id) is None


async def test_concurrent_confirms_store_one_log(confirmer, buffer):
    ann = _user()
    doc = await _recognition(buffer, ann, [_item(CRAB)])

    first, second = await asyncio.gather(
        confirmer.confirm(ann, doc.id, TODAY, None, None),
        confirmer.confirm(ann, doc.id, TODAY, None, None),
    )

    assert first == second
    assert _count("nutrition_log") == 1
    assert await buffer.get(ann, doc.id) is None


async def test_the_confirm_client_uuid_is_per_recognition(confirmer, buffer):
    ann = _user()
    one = await _recognition(buffer, ann, [_item(CRAB)])
    two = await _recognition(buffer, ann, [_item(CRAB)])

    first = await confirmer.confirm(ann, one.id, TODAY, None, None)
    second = await confirmer.confirm(ann, two.id, TODAY, None, None)

    assert first.id != second.id
    assert confirm_client_uuid(one.id) == confirm_client_uuid(one.id) != confirm_client_uuid(two.id)


# ================================================================ NutritionLogIn


def test_the_ai_fields_of_a_log_are_set_together():
    base = dict(
        client_uuid=None,
        log_date=TODAY,
        meal_type=MealType.LUNCH,
        planned_meal_id=None,
        hunger_level_before=None,
        hunger_level_after=None,
        items=(ItemIn(1, Decimal(100)),),
    )
    assert NutritionLogIn(**base).ai_confidence is None  # existing callers unchanged
    NutritionLogIn(**base, ai_confidence=Decimal("0.5"), ai_was_edited=False)
    with pytest.raises(ValueError):
        NutritionLogIn(**base, ai_confidence=Decimal("0.5"))
    with pytest.raises(ValueError):
        NutritionLogIn(**base, ai_was_edited=True)
