"""Sync change queries on PostgreSQL (DB-13; NFR-OFF, api-rules.md "Sync").

Pull by cursor in (updated_at, kind, id) order with tombstones, the overlap of the last
page, the data of live rows, the cursor format and the row lookup of push. Each pull runs
in its own transaction, as a request does. Rows written with an explicit updated_at are
plain INSERTs: the set_updated_at trigger fires on UPDATE only. Skipped without
PostgreSQL.
"""

import base64
import functools
import itertools
import json
import re
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.repositories.body_metrics import SqlBodyMetricsUnitOfWork
from app.db.repositories.nutrition_logs import ItemIn, NutritionLogIn, SqlNutritionLogUnitOfWork
from app.db.repositories.sync import (
    KINDS,
    InvalidCursorError,
    SqlSyncUnitOfWork,
    SyncCursor,
    SyncPage,
    SyncRowState,
    decode_cursor,
    encode_cursor,
)
from app.db.repositories.workouts import SqlWorkoutUnitOfWork
from app.db.session import database_url
from app.domain.constants import MealType
from app.services.body_metrics import MetricsIn
from app.services.workouts import ExerciseIn, SetIn, WorkoutIn
from tests.db.conftest import delete_users
from tests.db.test_repositories import TEST_DB, migrated_db  # noqa: F401  (fixture)

pytestmark = pytest.mark.anyio

BODY, NUTRITION, WORKOUT = KINDS  # "body_metrics" < "nutrition_log" < "workout"
BENCH, SQUAT = 1, 2  # exercise ids of REFERENCE
RICE, YOGURT = 1, 2  # food ids of REFERENCE
PAST = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)  # long before every cursor of a last page
OVERLAP = timedelta(seconds=60)

REFERENCE = """
INSERT INTO muscle_group (id, group_name, region, description)
VALUES (1, 'Chest', 'upper', ''), (2, 'Quadriceps', 'lower', '');
INSERT INTO exercise (id, name, difficulty_level, equipment, is_compound, is_bodyweight,
                      description, instruction)
VALUES (1, 'Bench press', 'beginner', 'gym', true, false, '', ''),
       (2, 'Back squat', 'beginner', 'gym', true, false, '', '');
INSERT INTO exercise_muscle_group (exercise_id, muscle_group_id, is_primary)
VALUES (1, 1, true), (2, 2, true);
INSERT INTO food_item (id, name, cals_per_100g, protein_per_100g, fat_per_100g,
                       carbs_per_100g, diet_role, suitable_meal_types, default_portion_g,
                       min_portion_g, max_portion_g, portion_step_g)
VALUES (1, 'Rice', 130, 2.7, 0.3, 28, 'carb', '{lunch,dinner}', 150, 50, 300, 10),
       (2, 'Yogurt', 60, 3.5, 3.3, 4.7, 'dairy', '{breakfast,snack}', 150, 50, 300, 10)
"""

# one row of each kind; :t and :x are updated_at and deleted_at, :d a day unique per row
INSERT = {
    WORKOUT: "INSERT INTO workout_log (id, user_id, log_date, rpe_rating, updated_at, deleted_at)"
    " VALUES (COALESCE(:id, nextval(pg_get_serial_sequence('workout_log', 'id'))),"
    " :u, :d, 7, :t, :x) RETURNING id, client_uuid",
    NUTRITION: "INSERT INTO nutrition_log (id, user_id, log_date, meal_type, actual_cals,"
    " actual_protein, actual_fat, actual_carbs, updated_at, deleted_at)"
    " VALUES (COALESCE(:id, nextval(pg_get_serial_sequence('nutrition_log', 'id'))),"
    " :u, :d, 'snack', 100, 10, 1, 10, :t, :x) RETURNING id, client_uuid",
    BODY: "INSERT INTO body_metrics (id, user_id, measured_on, weight, updated_at, deleted_at)"
    " VALUES (COALESCE(:id, nextval(pg_get_serial_sequence('body_metrics', 'id'))),"
    " :u, :d, 80, :t, :x) RETURNING id, client_uuid",
}
_days = itertools.count()


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


@pytest.fixture(scope="module")
def reference(migrated_db):  # noqa: F811
    with _sync_engine().begin() as db:
        for statement in REFERENCE.split(";"):
            db.execute(text(statement))


@pytest.fixture
async def factory(reference) -> AsyncIterator[async_sessionmaker]:
    with _sync_engine().begin() as db:
        delete_users(db)
    engine = create_async_engine(database_url().set(database=TEST_DB))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def sync(factory) -> SqlSyncUnitOfWork:
    return SqlSyncUnitOfWork(factory)


def _user(email: str = "ann@example.com") -> int:
    with _sync_engine().begin() as db:
        return db.execute(
            text(
                "INSERT INTO app_user (email, password_hash, name, surname)"
                " VALUES (:e, 'x', 'A', 'B') RETURNING id"
            ),
            {"e": email},
        ).scalar_one()


def _insert(kind, user_id, updated_at, *, deleted=False, row_id=None) -> tuple[str, int, uuid.UUID]:
    """A row with this updated_at (deleted: deleted_at = updated_at); (kind, id, uuid)."""
    day = date(2025, 1, 1) + timedelta(days=next(_days))
    with _sync_engine().begin() as db:
        row = db.execute(
            text(INSERT[kind]),
            {
                "id": row_id,
                "u": user_id,
                "d": day,
                "t": updated_at,
                "x": updated_at if deleted else None,
            },
        ).one()
    return kind, row.id, row.client_uuid


def _db_now() -> datetime:
    with _sync_engine().connect() as db:
        return db.execute(text("SELECT now()")).scalar_one()


async def _pull(sync, user_id, cursor=None, limit=100) -> SyncPage:
    async with sync() as store:
        return await store.changes_since(user_id, cursor, limit)


async def _pull_all(sync, user_id, cursor=None, limit=100) -> tuple[list[SyncPage], SyncCursor]:
    """Every page to the end; each next_cursor goes through the string form, as via the API."""
    pages = []
    while True:
        page = await _pull(sync, user_id, cursor, limit)
        pages.append(page)
        cursor = decode_cursor(encode_cursor(page.next_cursor))
        if not page.has_more:
            return pages, cursor


def _changes(pages: list[SyncPage]) -> list:
    return [change for page in pages for change in page.changes]


def _after_last(pages: list[SyncPage]) -> SyncCursor:
    """The cursor right after the newest change pulled (a page boundary), without the
    overlap of a last page: only what changes later comes after it."""
    last = _changes(pages)[-1]
    return SyncCursor(last.updated_at, last.entity, last.id)


# ---------------------------------------------------------------- stored through the repos


def _workout(sets=((60, 10), (60, 10)), client_uuid=None) -> WorkoutIn:
    return WorkoutIn(
        client_uuid=client_uuid,
        training_session_id=None,
        log_date=date(2026, 11, 20),
        rpe_rating=7,
        exercises=(
            ExerciseIn(
                BENCH,
                None,
                1,
                tuple(
                    SetIn(n, reps, Decimal(weight), True, None)
                    for n, (weight, reps) in enumerate(sets, 1)
                ),
            ),
            ExerciseIn(SQUAT, None, 2, (SetIn(1, 5, Decimal(100), True, 8),)),
        ),
    )


async def _store_workout(factory, user_id, workout=None) -> int:
    workout = workout or _workout(client_uuid=uuid.uuid4())
    async with SqlWorkoutUnitOfWork(factory)() as store:
        return await store.insert_workout(user_id, workout, [None] * len(workout.exercises))


async def _store_nutrition(factory, user_id) -> int:
    log = NutritionLogIn(
        client_uuid=uuid.uuid4(),
        log_date=date(2026, 11, 20),
        meal_type=MealType.LUNCH,
        planned_meal_id=None,
        hunger_level_before=4,
        hunger_level_after=None,
        items=(ItemIn(RICE, Decimal(150)), ItemIn(YOGURT, Decimal("80.5"))),
    )
    async with SqlNutritionLogUnitOfWork(factory)() as store:
        return (await store.create(user_id, log)).id


async def _store_metrics(factory, user_id, weight="80.5") -> int:
    values = MetricsIn(date(2026, 11, 20), Decimal(weight), waist=Decimal(85))
    async with SqlBodyMetricsUnitOfWork(factory)() as store:
        return await store.insert(user_id, values, uuid.uuid4())


# ---------------------------------------------------------------- order and paging


@pytest.mark.parametrize("limit", [1, 2, 100])
async def test_pages_return_every_change_once_in_updated_at_kind_id_order(sync, limit):
    ann, bob = _user(), _user("bob@example.com")
    t0, t1, t2 = PAST, PAST + timedelta(microseconds=1), PAST + timedelta(days=1)
    # At t0 the ids run against the kind order (workout lowest), so an order by
    # (updated_at, id) alone differs from (updated_at, kind, id).
    rows = [
        _insert(WORKOUT, ann, t0, row_id=900001),
        _insert(NUTRITION, ann, t0, row_id=900002),
        _insert(BODY, ann, t0, row_id=900003),
        _insert(WORKOUT, ann, t0, row_id=900004),
        _insert(NUTRITION, ann, t1, deleted=True),
        _insert(BODY, ann, t1),
        _insert(WORKOUT, ann, t1),
        _insert(BODY, ann, t2, deleted=True),
        _insert(NUTRITION, ann, t2),
        _insert(WORKOUT, ann, t2, deleted=True),
    ]
    for kind in KINDS:  # Bob's rows at the same times are never Ann's changes
        _insert(kind, bob, t0)
        _insert(kind, bob, t1)
    times = {row: t for row, t in zip(rows, [t0] * 4 + [t1] * 3 + [t2] * 3, strict=True)}
    expected = sorted((times[row], row[0], row[1]) for row in rows)

    pages, cursor = await _pull_all(sync, ann, limit=limit)

    changes = _changes(pages)
    assert [(c.updated_at, c.entity, c.id) for c in changes] == expected
    assert [p.has_more for p in pages] == [True] * (len(pages) - 1) + [False]
    assert all(len(p.changes) == limit for p in pages[:-1])
    assert len(pages) == -(-len(rows) // limit)
    uuids = {(kind, row_id): client_uuid for kind, row_id, client_uuid in rows}
    assert all(c.client_uuid == uuids[c.entity, c.id] for c in changes)
    tombstones = {(c.entity, c.id) for c in changes if c.deleted_at is not None}
    assert tombstones == {(NUTRITION, rows[4][1]), (BODY, rows[7][1]), (WORKOUT, rows[9][1])}
    assert all((c.data is None) == (c.deleted_at is not None) for c in changes)
    assert (await _pull(sync, ann, cursor)).changes == ()  # nothing new after the last page


# ---------------------------------------------------------------- tombstones and edits


async def test_soft_deletes_come_back_once_as_tombstones(factory, sync):
    ann = _user()
    workout_id = await _store_workout(factory, ann)
    log_id = await _store_nutrition(factory, ann)
    metrics_id = await _store_metrics(factory, ann)
    pages, _ = await _pull_all(sync, ann)
    assert {(c.entity, c.id, c.deleted_at) for c in _changes(pages)} == {
        (WORKOUT, workout_id, None),
        (NUTRITION, log_id, None),
        (BODY, metrics_id, None),
    }
    before_delete = _after_last(pages)
    assert (await _pull(sync, ann, before_delete)).changes == ()

    async with SqlWorkoutUnitOfWork(factory)() as store:
        assert await store.soft_delete(ann, workout_id)
    async with SqlNutritionLogUnitOfWork(factory)() as store:
        assert await store.soft_delete(ann, log_id)
    async with SqlBodyMetricsUnitOfWork(factory)() as store:
        await store.soft_delete(ann, metrics_id)
    page = await _pull(sync, ann, before_delete)

    assert sorted((c.entity, c.id) for c in page.changes) == [
        (BODY, metrics_id),
        (NUTRITION, log_id),
        (WORKOUT, workout_id),
    ]  # each once, as a tombstone only
    for change in page.changes:
        assert change.data is None
        assert change.deleted_at is not None
        assert change.updated_at == change.deleted_at  # the delete's UPDATE moved it


async def test_edits_come_back_after_the_previous_cursor(factory, sync):
    ann = _user()
    workout = _workout(client_uuid=uuid.uuid4())
    workout_id = await _store_workout(factory, ann, workout)
    metrics_id = await _store_metrics(factory, ann, weight="80.5")
    pages, _ = await _pull_all(sync, ann)
    before_edit = _after_last(pages)
    assert (await _pull(sync, ann, before_edit)).changes == ()

    # PUT with the same date, session and RPE: only the sets change (Step 2 of DB-13)
    edited = _workout(sets=((62.5, 8),), client_uuid=workout.client_uuid)
    async with SqlWorkoutUnitOfWork(factory)() as store:
        assert await store.replace_workout(ann, workout_id, edited, [None, None])
    async with SqlBodyMetricsUnitOfWork(factory)() as store:
        await store.replace(ann, metrics_id, MetricsIn(date(2026, 11, 20), Decimal(79)), None)
    page = await _pull(sync, ann, before_edit)

    changed = {c.entity: c for c in page.changes}
    assert sorted(changed) == [BODY, WORKOUT]
    assert changed[BODY].id == metrics_id
    assert changed[BODY].data.weight == Decimal(79)
    assert changed[WORKOUT].id == workout_id
    sets = changed[WORKOUT].data.exercises[0].sets
    assert [(s.weight, s.reps) for s in sets] == [(Decimal("62.5"), 8)]


# ---------------------------------------------------------------- overlap of the last page


async def test_the_last_page_cursor_overlaps_a_minute_of_the_database_clock(sync):
    ann = _user()
    _insert(WORKOUT, ann, PAST)
    before = _db_now()
    _, cursor = await _pull_all(sync, ann)
    after = _db_now()

    assert (cursor.kind, cursor.id) == ("", 0)
    assert before - OVERLAP <= cursor.updated_at <= after - OVERLAP

    # a transaction that started 30 s ago commits only now: its updated_at is before the
    # time of the pull above, yet after the cursor
    late = _insert(NUTRITION, ann, _db_now() - timedelta(seconds=30))
    page = await _pull(sync, ann, cursor)

    assert [(c.entity, c.id) for c in page.changes] == [late[:2]]


# ---------------------------------------------------------------- isolation


async def test_another_users_rows_never_appear_and_are_not_looked_up(sync):
    ann, bob = _user(), _user("bob@example.com")
    anns, bobs = [], []
    for i, kind in enumerate(KINDS * 2):
        moment = PAST + timedelta(minutes=i)
        deleted = i >= len(KINDS)  # the second round are tombstones
        anns.append(_insert(kind, ann, moment, deleted=deleted))
        bobs.append(_insert(kind, bob, moment, deleted=deleted))

    for limit in (1, 100):
        pages, _ = await _pull_all(sync, ann, limit=limit)
        assert sorted((c.entity, c.id) for c in _changes(pages)) == sorted(r[:2] for r in anns)

    async with sync() as store:
        for kind, _, client_uuid in bobs:
            assert await store.lookup(ann, kind, client_uuid) is None
            assert await store.lookup(bob, kind, client_uuid) is not None


# ---------------------------------------------------------------- data of live rows


async def test_data_is_what_the_get_endpoints_return(factory, sync):
    ann = _user()
    workout_id = await _store_workout(factory, ann)
    log_id = await _store_nutrition(factory, ann)
    metrics_id = await _store_metrics(factory, ann)

    changes = {c.entity: c for c in (await _pull(sync, ann)).changes}

    async with SqlWorkoutUnitOfWork(factory)() as store:
        workout = await store.find_by_client_uuid(ann, changes[WORKOUT].client_uuid)
    async with SqlNutritionLogUnitOfWork(factory)() as store:
        log = await store.get(ann, log_id)
    async with SqlBodyMetricsUnitOfWork(factory)() as store:
        metrics = await store.by_client_uuid(ann, changes[BODY].client_uuid)
    assert (workout.id, log.id, metrics.id) == (workout_id, log_id, metrics_id)
    assert len(workout.exercises) == 2 and len(log.items) == 2  # children are compared too
    assert changes[WORKOUT].data == workout
    assert changes[NUTRITION].data == log
    assert changes[BODY].data == metrics


# ---------------------------------------------------------------- cursor format


def _raw(payload) -> str:
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def test_cursor_round_trip_keeps_microseconds_and_is_utc():
    moment = datetime(2026, 11, 25, 10, 0, 0, 1, tzinfo=UTC)
    for cursor in (
        SyncCursor(moment, WORKOUT, 42),
        SyncCursor(moment, "", 0),  # a last page's cursor
        SyncCursor(moment.astimezone(ZoneInfo("Europe/Warsaw")), BODY, 2**31 - 1),
    ):
        encoded = encode_cursor(cursor)
        decoded = decode_cursor(encoded)

        assert re.fullmatch(r"[A-Za-z0-9_-]+", encoded)  # base64url, no padding
        assert decoded == cursor
        assert decoded.updated_at.utcoffset() == timedelta(0)
        assert decoded.updated_at.microsecond == 1
    assert json.loads(base64.urlsafe_b64decode(encode_cursor(cursor) + "==")) == {
        "t": "2026-11-25T10:00:00.000001+00:00",
        "k": BODY,
        "i": 2**31 - 1,
    }


def test_a_cursor_time_without_a_time_zone_is_not_encoded():
    with pytest.raises(ValueError):
        encode_cursor(SyncCursor(datetime(2026, 11, 25, 10, 0), WORKOUT, 1))


GOOD = {"t": "2026-11-25T10:00:00.000001+00:00", "k": WORKOUT, "i": 1}


@pytest.mark.parametrize(
    "cursor",
    [
        pytest.param("", id="empty"),
        pytest.param("not a cursor!", id="not base64url"),
        pytest.param(_raw(GOOD).replace("e", "+"), id="base64 alphabet"),
        pytest.param(_raw(GOOD) + "=", id="padding"),
        pytest.param(_raw(GOOD)[:-1] + "@", id="bad character"),
        pytest.param("a", id="bad length"),
        pytest.param(_raw(b'{"\x80": 1}'), id="not utf-8"),
        pytest.param(_raw(b"not json"), id="not json"),
        pytest.param(_raw([1, 2, 3]), id="not an object"),
        pytest.param(_raw({"t": GOOD["t"], "k": WORKOUT}), id="missing key"),
        pytest.param(_raw({**GOOD, "x": 1}), id="extra key"),
        pytest.param(_raw({**GOOD, "k": "training_plan"}), id="unknown kind"),
        pytest.param(_raw({**GOOD, "k": None}), id="kind null"),
        pytest.param(_raw({**GOOD, "t": "2026-11-25T10:00:00.000001"}), id="naive time"),
        pytest.param(_raw({**GOOD, "t": "2026-11-25"}), id="date only"),
        pytest.param(_raw({**GOOD, "t": "yesterday"}), id="not a time"),
        pytest.param(_raw({**GOOD, "t": 1764064800}), id="time not a string"),
        pytest.param(_raw({**GOOD, "i": -1}), id="negative id"),
        pytest.param(_raw({**GOOD, "i": 2**31}), id="id above integer"),
        pytest.param(_raw({**GOOD, "i": True}), id="id boolean"),
        pytest.param(_raw({**GOOD, "i": "1"}), id="id string"),
        pytest.param(_raw({**GOOD, "i": 1.0}), id="id float"),
    ],
)
def test_a_malformed_cursor_is_invalid(cursor):
    assert decode_cursor(_raw(GOOD)) == SyncCursor(
        datetime(2026, 11, 25, 10, 0, 0, 1, tzinfo=UTC), WORKOUT, 1
    )  # the cases differ from a valid cursor in one point only

    with pytest.raises(InvalidCursorError):
        decode_cursor(cursor)


# ---------------------------------------------------------------- statements per page


def _fill(user_id: int, n: int) -> None:
    """n live rows of each kind, with children: a workout has an exercise with two sets,
    a meal log two items."""
    with _sync_engine().begin() as db:
        params = {"u": user_id, "n": n}
        db.execute(
            text(
                "WITH w AS (INSERT INTO workout_log (user_id, log_date, rpe_rating)"
                " SELECT :u, DATE '2026-01-01' + i, 7 FROM generate_series(1, :n) i"
                " RETURNING id),"
                " e AS (INSERT INTO workout_log_exercise (workout_log_id, exercise_id, sort_order)"
                " SELECT id, 1, 1 FROM w RETURNING id)"
                " INSERT INTO workout_set (workout_log_exercise_id, set_number, reps, weight)"
                " SELECT e.id, k, 10, 60 FROM e, generate_series(1, 2) k"
            ),
            params,
        )
        db.execute(
            text(
                "WITH l AS (INSERT INTO nutrition_log (user_id, log_date, meal_type, actual_cals,"
                " actual_protein, actual_fat, actual_carbs)"
                " SELECT :u, DATE '2026-01-01' + i, 'snack', 100, 10, 1, 10"
                " FROM generate_series(1, :n) i RETURNING id)"
                " INSERT INTO nutrition_log_food_item (nutrition_log_id, food_item_id, grams)"
                " SELECT l.id, f, 100 FROM l, generate_series(1, 2) f"
            ),
            params,
        )
        db.execute(
            text(
                "INSERT INTO body_metrics (user_id, measured_on, weight)"
                " SELECT :u, DATE '2026-01-01' + i, 80 FROM generate_series(1, :n) i"
            ),
            params,
        )


async def test_the_statements_of_a_page_do_not_grow_with_its_size(factory, sync):
    small, large = _user(), _user("bob@example.com")
    _fill(small, 1)
    _fill(large, 20)
    engine = factory.kw["bind"].sync_engine
    statements: list[str] = []

    def capture(conn, cursor, statement, *rest):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        counts = {}
        for user_id, rows in ((small, 3), (large, 60)):
            async with sync() as store:
                statements.clear()
                page = await store.changes_since(user_id, None, 100)
                counts[rows] = len(statements)
            assert len(page.changes) == rows and not page.has_more
            assert all(c.data is not None for c in page.changes)
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    # the page; workout rows, exercises, sets; meal log rows, items; body rows; the clock
    assert counts == {3: 8, 60: 8}


# ---------------------------------------------------------------- a row gone mid-page


async def test_a_row_gone_before_its_data_is_loaded_is_skipped_without_moving_the_cursor(
    factory, sync
):
    ann = _user()
    workout = _insert(WORKOUT, ann, PAST)
    _insert(NUTRITION, ann, PAST + timedelta(minutes=1))
    engine = factory.kw["bind"].sync_engine

    def delete_ann_after_the_page_query(conn, cursor, statement, *rest):
        if "UNION ALL" in statement:  # committed by another connection, as a request would
            with _sync_engine().begin() as db:
                db.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": ann})

    event.listen(engine, "after_cursor_execute", delete_ann_after_the_page_query)
    try:
        page = await _pull(sync, ann, limit=1)
    finally:
        event.remove(engine, "after_cursor_execute", delete_ann_after_the_page_query)

    assert page.changes == ()
    assert page.has_more
    assert page.next_cursor == SyncCursor(PAST, WORKOUT, workout[1])


# ---------------------------------------------------------------- lookup for push


async def test_lookup_returns_live_rows_and_tombstones_and_locks_them(sync):
    ann = _user()
    live = _insert(WORKOUT, ann, PAST)
    tombstone = _insert(NUTRITION, ann, PAST + timedelta(minutes=1), deleted=True)
    metrics = _insert(BODY, ann, PAST + timedelta(minutes=2))

    async with sync() as store:
        assert await store.lookup(ann, WORKOUT, live[2]) == SyncRowState(live[1], PAST, None)
        assert await store.lookup(ann, NUTRITION, tombstone[2]) == SyncRowState(
            tombstone[1], PAST + timedelta(minutes=1), PAST + timedelta(minutes=1)
        )
        assert await store.lookup(ann, BODY, metrics[2]) == SyncRowState(
            metrics[1], PAST + timedelta(minutes=2), None
        )
        assert await store.lookup(ann, WORKOUT, uuid.uuid4()) is None
        assert await store.lookup(ann, WORKOUT, tombstone[2]) is None  # uuid of another kind
        with pytest.raises(ValueError):
            await store.lookup(ann, "training_plan", live[2])

        # FOR UPDATE until the end of the transaction: another writer cannot take the row
        with (
            pytest.raises(OperationalError, match="could not obtain lock"),
            _sync_engine().connect() as db,
        ):
            db.execute(
                text("SELECT 1 FROM workout_log WHERE id = :id FOR UPDATE NOWAIT"),
                {"id": live[1]},
            )
    with _sync_engine().connect() as db:  # free again after the commit
        db.execute(
            text("SELECT 1 FROM workout_log WHERE id = :id FOR UPDATE NOWAIT"), {"id": live[1]}
        )
