"""No sequential scan on a large table in the reviewed reads (DB-12; NFR-PERF, NFR-SCALE).

Runs every method of `app.db.query_review.REVIEWS` through its capture with enable_seqscan
off and fails when a plan has a Seq Scan on a `LARGE_TABLES` table: with sequential scans
off the planner takes any index that fits, so a Seq Scan left means no index serves the
query. At this volume the planner would otherwise prefer Seq Scans on small tables, which
says nothing about the indexes (questions.md [DB-12] seqscan-criterion).

The fixture gives two users rows in every large table the reviewed methods read, so the
user filter matters; it is written and rolled back in one transaction. Skipped without
PostgreSQL.
"""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.db.query_review import (
    INDEX_SCANS,
    LARGE_TABLES,
    REVIEWS,
    Context,
    MethodPlans,
    large_seq_scans,
    load_context,
    report,
    review,
)
from app.db.session import database_url
from tests.db.test_repositories import TEST_DB, migrated_db  # noqa: F401  (fixture)

pytestmark = pytest.mark.anyio

ANN, BOB = 1, 2
TIMEZONE = ZoneInfo("Europe/Warsaw")  # app_user.timezone default

# Large tables the reviewed methods read (refresh_token is not read by any of them).
FILLED = LARGE_TABLES - {"refresh_token"}

REFERENCE = """
INSERT INTO muscle_group (id, group_name, region, description)
VALUES (1, 'Chest', 'upper', ''), (2, 'Quadriceps', 'lower', '');
INSERT INTO exercise (id, name, difficulty_level, equipment, is_compound, is_bodyweight,
                      description, instruction)
VALUES (1, 'Bench press', 'intermediate', 'gym', true, false, '', ''),
       (2, 'Back squat', 'intermediate', 'gym', true, false, '', ''),
       (3, 'Push-up', 'beginner', 'none', true, true, '', '');
INSERT INTO exercise_muscle_group (exercise_id, muscle_group_id, is_primary)
VALUES (1, 1, true), (2, 2, true), (3, 1, true), (3, 2, false);
INSERT INTO injury_type (id, type_name, description, avg_healing_time_days)
VALUES (1, 'Shoulder strain', '', 21);
INSERT INTO injury_type_excluded_exercise (injury_type_id, exercise_id) VALUES (1, 1);
INSERT INTO allergen (id, name, description) VALUES (1, 'Milk', '');
INSERT INTO food_category (id, category_name, description) VALUES (1, 'Basics', '');
INSERT INTO food_item (id, name, cals_per_100g, protein_per_100g, fat_per_100g,
                       carbs_per_100g, diet_role, suitable_meal_types, default_portion_g,
                       min_portion_g, max_portion_g, portion_step_g)
VALUES (1, 'Chicken breast', 165, 31, 3.6, 0, 'protein', '{lunch,dinner}', 150, 50, 300, 10),
       (2, 'Rice', 130, 2.7, 0.3, 28, 'carb', '{lunch,dinner}', 150, 50, 300, 10),
       (3, 'Yogurt', 60, 3.5, 3.3, 4.7, 'dairy', '{breakfast,snack}', 150, 50, 300, 10);
INSERT INTO food_item_category (food_item_id, food_category_id) VALUES (1, 1), (2, 1), (3, 1);
INSERT INTO food_item_allergen (food_item_id, allergen_id) VALUES (3, 1);
"""

# Per user :u, ids built from :u so the two users' rows interleave in every table. The synced
# tables get updated_at from their day (soft-deleted meal logs: now()), so a sync cursor can
# fall mid-history (DB-13).
# Plans: <u>1 archived (days 120..57 ago), <u>2 active (56 days ago .. 27 days ahead).
# Workouts every 3 days over 120 days, each with 2 exercises of 3 sets; every 5th adapts the
# plan; personal records on the newest ones; 3 meal logs a day for 60 days with 2 items;
# a weigh-in every 3 days; 2 notifications a day for 60 days; 8 weekly reports.
USER = """
INSERT INTO app_user (id, email, name, surname)
VALUES (:u, 'user' || :u || '@example.com', 'U', 'N');
INSERT INTO user_profile (user_id, age, sex, current_weight, height, activity_level_pal, goal,
                          experience_level, equipment, target_value, tdee)
VALUES (:u, 30, 'male', 80, 180, 1.55, 'weight_loss', 'intermediate', 'gym', 75, 2700);
INSERT INTO user_allergen (user_id, allergen_id) VALUES (:u, 1);
INSERT INTO user_excluded_food (user_id, food_item_id) VALUES (:u, 2);
INSERT INTO injury (user_id, injury_type_id, affected_muscle_group_id, severity, start_date)
VALUES (:u, 1, 1, 'mild', CAST(:today AS date) - 10);

INSERT INTO training_plan (id, user_id, plan_name, goal, num_training_days, experience_level,
                           equipment, start_date, end_date, status)
VALUES (:u * 10 + 1, :u, 'Old', 'weight_loss', 3, 'intermediate', 'gym',
        CAST(:today AS date) - 120, CAST(:today AS date) - 57, 'archived'),
       (:u * 10 + 2, :u, 'Current', 'weight_loss', 3, 'intermediate', 'gym',
        CAST(:today AS date) - 56, CAST(:today AS date) + 27, 'active');
INSERT INTO training_session (id, training_plan_id, session_order, session_name, day_of_week,
                              estimated_duration)
SELECT p * 10 + k, p, k, 'Day ' || k, 2 * k - 1, 60
FROM unnest(ARRAY[:u * 10 + 1, :u * 10 + 2]) p, generate_series(1, 3) k;
INSERT INTO session_exercise (id, training_session_id, exercise_id, sort_order, planned_sets,
                              planned_reps, planned_weight, rest_seconds)
SELECT s.id * 10 + j, s.id, j, j, 3, 8, 50, 90
FROM training_session s
JOIN training_plan p ON p.id = s.training_plan_id AND p.user_id = :u, generate_series(1, 2) j;

INSERT INTO workout_log (id, user_id, training_session_id, log_date, rpe_rating, updated_at)
SELECT :u * 1000 + n, :u,
       (CASE WHEN 3 * (n - 1) <= 56 THEN :u * 10 + 2 ELSE :u * 10 + 1 END) * 10 + (n - 1) % 3 + 1,
       CAST(:today AS date) - 3 * (n - 1), 7, CAST(:today AS date) - 3 * (n - 1) + TIME '19:00'
FROM generate_series(1, 40) n;
INSERT INTO workout_log_exercise (id, workout_log_id, exercise_id, session_exercise_id,
                                  sort_order)
SELECT w.id * 10 + j, w.id, j, w.training_session_id * 10 + j, j
FROM workout_log w, generate_series(1, 2) j WHERE w.user_id = :u;
INSERT INTO workout_set (id, workout_log_exercise_id, set_number, reps, weight, completed)
SELECT e.id * 10 + k, e.id, k, 8, 40 + e.workout_log_id % 1000, k < 3 OR e.id % 7 <> 0
FROM workout_log_exercise e
JOIN workout_log w ON w.id = e.workout_log_id AND w.user_id = :u, generate_series(1, 3) k;
INSERT INTO plan_adjustment (session_exercise_id, workout_log_id, reason, old_sets, new_sets,
                             old_reps, new_reps, old_weight, new_weight)
SELECT w.training_session_id * 10 + 1, w.id, 'progression', 3, 3, 8, 8, 50, 52.5
FROM workout_log w WHERE w.user_id = :u AND (w.id % 1000) % 5 IN (0, 1);
INSERT INTO personal_record (user_id, exercise_id, workout_log_id, max_weight, max_reps, e1rm,
                             achieved_date, is_current)
SELECT :u, 1 + (n - 1) % 2, w.id, 40 + 50 - n, 8, 60, w.log_date, n <= 2
FROM generate_series(1, 12) n JOIN workout_log w ON w.id = :u * 1000 + n;

INSERT INTO diet_plan (id, user_id, name, goal, meals_per_day, daily_cal_goal, protein_goal,
                       fat_goal, carbs_goal, start_date, end_date, status)
VALUES (:u * 10 + 1, :u, 'Old', 'weight_loss', 3, 2300, 150, 70, 250,
        CAST(:today AS date) - 120, CAST(:today AS date) - 57, 'archived'),
       (:u * 10 + 2, :u, 'Current', 'weight_loss', 3, 2200, 150, 70, 240,
        CAST(:today AS date) - 56, CAST(:today AS date) + 27, 'active');
INSERT INTO meal (id, diet_plan_id, day_index, meal_type, meal_order, planned_time,
                  planned_cals, planned_protein, planned_fat, planned_carbs)
SELECT p * 100 + d * 10 + k, p, d, (ARRAY['breakfast', 'lunch', 'dinner'])[k]::meal_type, k,
       make_time(4 + 4 * k, 0, 0), 700, 50, 20, 80
FROM unnest(ARRAY[:u * 10 + 1, :u * 10 + 2]) p, generate_series(1, 7) d,
     generate_series(1, 3) k;
INSERT INTO meal_food_item (meal_id, food_item_id, grams)
SELECT m.id, f, 150
FROM meal m JOIN diet_plan p ON p.id = m.diet_plan_id AND p.user_id = :u,
     generate_series(1, 2) f;

INSERT INTO nutrition_log (id, user_id, log_date, meal_type, planned_meal_id, actual_cals,
                           actual_protein, actual_fat, actual_carbs, hunger_level_before,
                           deleted_at, updated_at)
SELECT :u * 10000 + d * 10 + k, :u, CAST(:today AS date) - d,
       (ARRAY['breakfast', 'lunch', 'dinner'])[k]::meal_type,
       CASE WHEN d <= 56 THEN (:u * 10 + 2) * 100 + 10 + k END, 442.5, 52.55, 5.85, 42,
       4, CASE WHEN d % 10 = 5 AND k = 3 THEN now() END,
       CASE WHEN d % 10 = 5 AND k = 3 THEN now()
            ELSE CAST(:today AS date) - d + make_time(4 + 4 * k, 30, 0) END
FROM generate_series(0, 59) d, generate_series(1, 3) k;
INSERT INTO nutrition_log_food_item (nutrition_log_id, food_item_id, grams)
SELECT l.id, f, 150 FROM nutrition_log l, generate_series(1, 2) f WHERE l.user_id = :u;

INSERT INTO body_metrics (user_id, measured_on, weight, waist, updated_at)
SELECT :u, CAST(:today AS date) - d, 80 + d / 30.0, 85, CAST(:today AS date) - d + TIME '07:00'
FROM generate_series(0, 119, 3) d;

INSERT INTO notification (user_id, message_type, scheduled_at, message, is_sent, sent_at)
SELECT :u, 'meal_reminder', CAST(:now AS timestamptz) - make_interval(hours => 12 * i), 'Meal',
       i > 0, CASE WHEN i > 0 THEN CAST(:now AS timestamptz) - make_interval(hours => 12 * i) END
FROM generate_series(0, 119) i;

INSERT INTO progress_report (user_id, report_type, report_period_start, report_period_end,
                             training_volume, training_sessions_completed,
                             training_sessions_planned)
SELECT :u, 'weekly', CAST(:today AS date) - 7 * w, CAST(:today AS date) - 7 * w + 6, 9000, 3, 3
FROM generate_series(1, 8) w;
"""


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _run_script(conn: AsyncConnection, script: str, **params) -> None:
    for statement in script.split(";"):
        if statement.strip():
            await conn.execute(text(statement), params)


@pytest.fixture
async def seeded(migrated_db) -> AsyncIterator[tuple[AsyncConnection, Context]]:  # noqa: F811
    """Ann's context over the fixture; everything is rolled back afterwards."""
    engine = create_async_engine(database_url().set(database=TEST_DB))
    try:
        async with engine.connect() as conn:
            await conn.begin()
            now = datetime.now(UTC)
            today: date = now.astimezone(TIMEZONE).date()
            await _run_script(conn, REFERENCE)
            for user in (ANN, BOB):
                await _run_script(conn, USER, u=user, today=today, now=now)
            await conn.exec_driver_sql("ANALYZE")
            yield conn, await load_context(conn, ANN, now)
            await conn.rollback()
    finally:
        await engine.dispose()


def _scanned_tables(results: list[MethodPlans]) -> set[str]:
    return {scan.table for m in results for s in m.statements for scan in s.scans}


async def test_every_review_runs_on_a_fixture_that_fills_every_large_table(seeded):
    """Not vacuous: every method runs, sends SQL and reads rows of every filled table."""
    conn, context = seeded
    assert context.active_session_ids and context.workout_id and context.exercise_id
    assert context.nutrition_log_id and context.level and context.equipment
    assert context.workout_uuid and context.nutrition_log_uuid and context.body_metrics_uuid
    # the middle change of 260 (180 meal logs in the last 60 days) is weeks back, not at an end
    middle = context.sync_cursor.updated_at
    assert context.now - timedelta(days=60) < middle < context.now - timedelta(days=7)

    results = await review(conn, context, no_seqscan=True)

    assert [m.method for m in results] == [r.name for r in REVIEWS]
    assert [m.method for m in results if m.skipped or not m.statements] == []
    assert _scanned_tables(results) >= FILLED
    read = {scan.table for m in results for s in m.statements for scan in s.scans if scan.rows}
    assert read >= FILLED, f"no rows read from {sorted(FILLED - read)}"


async def test_no_sequential_scan_on_a_large_table(seeded):
    conn, context = seeded

    results = await review(conn, context, no_seqscan=True)

    offenders = large_seq_scans(results)
    assert offenders == [], report(context, results, no_seqscan=True)


SYNCED = {
    "body_metrics": "body_metrics",
    "nutrition_log": "nutrition_log",
    "workout": "workout_log",
}


# At fixture volume (80 rows a table) a bitmap scan of any index that leads with user_id costs
# about the same as the index meant, and the planner flips between them as the rolled-back
# fixtures of earlier tests bloat the heap; with bitmap and sequential scans off, an Index
# Scan on the index meant shows that it is the one that fits. Only the two sync tests below
# assert an index by name: the "no Seq Scan" criterion of DB-12 holds without this setting.
NO_BITMAPSCAN = "SET LOCAL enable_bitmapscan = off"


def _reviews(prefix: str) -> tuple:
    return tuple(r for r in REVIEWS if r.name.startswith(prefix))


async def test_each_sync_pull_branch_is_a_range_of_its_sync_index(seeded):
    """DB-13: in the page query every table is read through ix_<table>_user_updated with an
    Index Cond on user_id and, after a cursor, on updated_at: a range, already in order.
    Bitmap scans off: see NO_BITMAPSCAN."""
    conn, context = seeded
    await conn.exec_driver_sql(NO_BITMAPSCAN)  # rolled back with the fixture

    results = await review(conn, context, no_seqscan=True, reviews=_reviews("sync.changes_since"))

    assert [m.method for m in results] == ["sync.changes_since(start)", "sync.changes_since(mid)"]
    for m in results:
        page = m.statements[0]  # then the data of the live rows of the page
        assert "UNION ALL" in page.sql
        assert sorted(scan.table for scan in page.scans) == sorted(SYNCED.values())
        for scan in page.scans:
            assert scan.node in INDEX_SCANS, (m.method, scan)  # so cond is the Index Cond
            assert scan.index == f"ix_{scan.table}_user_updated", (m.method, scan)
            assert "user_id" in scan.cond, (m.method, scan)
            if m.method.endswith("(mid)"):  # without a cursor there is no updated_at to search
                assert "updated_at" in scan.cond, (m.method, scan)
            assert scan.rows > 0  # the page reads rows of every kind


async def test_the_push_lookup_locks_through_the_client_uuid_unique_index(seeded):
    """DB-13: lookup's SELECT ... FOR UPDATE finds the row through UNIQUE (user_id,
    client_uuid) of migration 0003, on each synced table, both columns in the Index Cond.
    Bitmap scans off: see NO_BITMAPSCAN."""
    conn, context = seeded
    await conn.exec_driver_sql(NO_BITMAPSCAN)  # rolled back with the fixture

    results = await review(conn, context, no_seqscan=True, reviews=_reviews("sync.lookup"))

    assert sorted(m.method for m in results) == [f"sync.lookup({kind})" for kind in SYNCED]
    for m in results:
        table = SYNCED[m.method.removeprefix("sync.lookup(").removesuffix(")")]
        (statement,) = m.statements
        assert "FOR UPDATE" in statement.sql
        (scan,) = statement.scans
        assert scan.node in INDEX_SCANS, (m.method, scan)  # so cond is the Index Cond
        assert scan.index == f"{table}_user_id_client_uuid_key", (m.method, scan)
        assert "user_id" in scan.cond and "client_uuid" in scan.cond, (m.method, scan)
        assert scan.rows == 1


async def test_a_missing_index_shows_as_a_sequential_scan(seeded):
    """The guard sees a missing index. Every workout_log index that leads with user_id goes:
    without ix_workout_log_user_date alone the planner takes the UNIQUE (user_id,
    client_uuid) of migration 0003 or the sync index (user_id, updated_at, id) of 0007,
    and no Seq Scan appears."""
    conn, context = seeded
    await conn.exec_driver_sql("DROP INDEX ix_workout_log_user_date")
    await conn.exec_driver_sql("DROP INDEX ix_workout_log_user_updated")
    await conn.exec_driver_sql(
        "ALTER TABLE workout_log DROP CONSTRAINT workout_log_user_id_client_uuid_key"
    )

    results = await review(conn, context, no_seqscan=True)

    offenders = {(method, scan.table) for method, _, scan in large_seq_scans(results)}
    assert offenders == {
        ("analytics.record_days", "workout_log"),
        ("analytics.data(T-27..T)", "workout_log"),
        ("analytics.data(T-89..T)", "workout_log"),
        ("workouts.list_workouts(all)", "workout_log"),
        ("workouts.list_workouts(T-29..T)", "workout_log"),
        ("sync.changes_since(start)", "workout_log"),
        ("sync.changes_since(mid)", "workout_log"),
        ("sync.lookup(workout)", "workout_log"),
    }
