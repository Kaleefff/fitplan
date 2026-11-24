"""EXPLAIN ANALYZE of the generator, log and analytics reads of one user (DB-12; NFR-PERF,
NFR-SCALE).

Calls the real repository methods (REVIEWS) for one user inside one transaction that is
rolled back at the end, so nothing is kept. A before_cursor_execute listener on the
connection captures every SELECT the methods send, exactly as sent to the driver (SQL and
parameters, no copies of the queries), and each one runs again as
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) in the same transaction.

With --no-seqscan the transaction starts with SET LOCAL enable_seqscan = off. At a small
volume the planner prefers a Seq Scan on a small table even when an index fits; with
sequential scans off it uses any index that fits, so a Seq Scan that is still there means
that no index of the table serves the query. tests/db/test_query_plans.py runs the same
REVIEWS in that mode and fails on a Seq Scan of a LARGE_TABLES table.

With sequential scans off, a query ordered by an indexed column (ORDER BY id, a merge join)
may read a whole index instead of a missing one; that shows as an index scan without an
Index Cond, not as a Seq Scan. Such scans are marked [full] and listed as information.

Output: one line per statement (method, rows, execution time, every table scan as
table -> node and index), then every Seq Scan on a LARGE_TABLES table, then every full index
scan on one. The user is chosen by email and shown by id only.

Run from backend/:
    uv run python -m app.db.query_review --email demo-loss@example.com [--no-seqscan]
"""

import argparse
import asyncio
import json
import re
import sys
from collections.abc import Awaitable, Callable, Iterator, Mapping
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.enums import DifficultyLevel, EquipmentType, PlanStatus
from app.db.models import (
    AppUser,
    NutritionLog,
    PersonalRecord,
    TrainingPlan,
    TrainingSession,
    UserProfile,
    WorkoutLog,
    WorkoutLogExercise,
)
from app.db.repositories.analytics import SqlAnalyticsStore
from app.db.repositories.body_metrics import SqlBodyMetricsStore
from app.db.repositories.diet_plans import SqlDietPlanStore
from app.db.repositories.library import SqlLibraryRepository
from app.db.repositories.nutrition_logs import SqlNutritionLogStore
from app.db.repositories.reports import SqlReportStore
from app.db.repositories.schedule import SqlScheduleStore
from app.db.repositories.training_plans import SqlTrainingPlanStore
from app.db.repositories.workouts import SqlWorkoutStore
from app.db.session import database_url

# Tables that grow with users and time. The reference tables (exercise and its links,
# muscle_group, food_item and its links, allergen, injury_type and its exclusions) are
# small and fixed, so a Seq Scan there is fine.
LARGE_TABLES = frozenset(
    {
        "body_metrics",
        "workout_log",
        "workout_log_exercise",
        "workout_set",
        "nutrition_log",
        "nutrition_log_food_item",
        "personal_record",
        "plan_adjustment",
        "training_plan",
        "training_session",
        "session_exercise",
        "diet_plan",
        "meal",
        "meal_food_item",
        "notification",
        "progress_report",
        "refresh_token",
    }
)

SEQ_SCAN = "Seq Scan"
INDEX_SCANS = frozenset({"Index Scan", "Index Only Scan"})
SCAN_NODES = INDEX_SCANS | {SEQ_SCAN, "Bitmap Heap Scan"}
EXPLAIN = "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
NO_SEQSCAN = "SET LOCAL enable_seqscan = off"
SELECT = re.compile(r"\s*(SELECT|WITH)\b", re.IGNORECASE)
PAGE = 20  # limit of the list endpoints' first page


# ---------------------------------------------------------------- what is reviewed


@dataclass(frozen=True)
class Context:
    """The arguments of the reviewed methods for one user; `today` in the user's timezone."""

    user_id: int
    today: date
    now: datetime
    active_session_ids: tuple[int, ...]
    workout_id: int | None
    exercise_id: int | None
    nutrition_log_id: int | None
    level: DifficultyLevel | None
    equipment: EquipmentType | None


@dataclass(frozen=True)
class Stores:
    analytics: SqlAnalyticsStore
    workouts: SqlWorkoutStore
    nutrition_logs: SqlNutritionLogStore
    body_metrics: SqlBodyMetricsStore
    training_plans: SqlTrainingPlanStore
    diet_plans: SqlDietPlanStore
    library: SqlLibraryRepository
    reports: SqlReportStore
    schedule: SqlScheduleStore


def _stores(session: AsyncSession, sessions: async_sessionmaker[AsyncSession]) -> Stores:
    return Stores(
        analytics=SqlAnalyticsStore(session),
        workouts=SqlWorkoutStore(session),
        nutrition_logs=SqlNutritionLogStore(session),
        body_metrics=SqlBodyMetricsStore(session),
        training_plans=SqlTrainingPlanStore(session),
        diet_plans=SqlDietPlanStore(session),
        library=SqlLibraryRepository(sessions),
        reports=SqlReportStore(sessions),
        schedule=SqlScheduleStore(session),
    )


@dataclass(frozen=True)
class Review:
    name: str
    call: Callable[[Stores, Context], Awaitable[object]]
    needs: tuple[str, ...] = ()  # Context fields that must be set, or the method is skipped


def _ago(c: Context, days: int) -> date:
    return c.today - timedelta(days=days)


REVIEWS: tuple[Review, ...] = (
    # analytics (DB-10, DB-11)
    Review("analytics.record_days", lambda s, c: s.analytics.record_days(c.user_id)),
    Review(
        "analytics.data(T-27..T)",
        lambda s, c: s.analytics.data(c.user_id, _ago(c, 27), c.today),
    ),
    Review(
        "analytics.data(T-89..T)",
        lambda s, c: s.analytics.data(c.user_id, _ago(c, 89), c.today),
    ),
    Review("analytics.target_weight", lambda s, c: s.analytics.target_weight(c.user_id)),
    # logs (DB-09)
    Review(
        "workouts.list_workouts(all)",
        lambda s, c: s.workouts.list_workouts(c.user_id, None, None, PAGE, 0),
    ),
    Review(
        "workouts.list_workouts(T-29..T)",
        lambda s, c: s.workouts.list_workouts(c.user_id, _ago(c, 29), c.today, PAGE, 0),
    ),
    Review(
        "workouts.result",
        lambda s, c: s.workouts.result(c.user_id, c.workout_id),
        needs=("workout_id",),
    ),
    Review(
        "workouts.current_record",
        lambda s, c: s.workouts.current_record(c.user_id, c.exercise_id),
        needs=("exercise_id",),
    ),
    Review(
        "nutrition_logs.list_logs",
        lambda s, c: s.nutrition_logs.list_logs(c.user_id, None, None, PAGE, 0),
    ),
    Review(
        "nutrition_logs.get",
        lambda s, c: s.nutrition_logs.get(c.user_id, c.nutrition_log_id),
        needs=("nutrition_log_id",),
    ),
    Review(
        "nutrition_logs.daily_summary(T)",
        lambda s, c: s.nutrition_logs.daily_summary(c.user_id, c.today),
    ),
    Review("body_metrics.newest", lambda s, c: s.body_metrics.newest(c.user_id)),
    Review("body_metrics.history", lambda s, c: s.body_metrics.history(c.user_id, None, None)),
    Review("body_metrics.live_on(T)", lambda s, c: s.body_metrics.live_on(c.user_id, c.today)),
    # generators (B-11, B-12) and the library (DB-06)
    Review(
        "training_plans.catalogue",
        lambda s, c: s.training_plans.catalogue(c.user_id, include_custom=False),
    ),
    Review(
        "training_plans.active_injuries", lambda s, c: s.training_plans.active_injuries(c.user_id)
    ),
    Review(
        "training_plans.profile_limits", lambda s, c: s.training_plans.profile_limits(c.user_id)
    ),
    Review("training_plans.get_active", lambda s, c: s.training_plans.get_active(c.user_id)),
    Review(
        "training_plans.workout_days(T-27)",
        lambda s, c: s.training_plans.workout_days(list(c.active_session_ids), _ago(c, 27)),
        needs=("active_session_ids",),
    ),
    Review("diet_plans.foods", lambda s, c: s.diet_plans.foods()),
    Review("diet_plans.user_allergens", lambda s, c: s.diet_plans.user_allergens(c.user_id)),
    Review("diet_plans.excluded_foods", lambda s, c: s.diet_plans.excluded_foods(c.user_id)),
    Review("diet_plans.get_active", lambda s, c: s.diet_plans.get_active(c.user_id)),
    Review(
        "library.eligible_exercises",
        lambda s, c: s.library.eligible_exercises(c.user_id, level=c.level, equipment=c.equipment),
    ),
    Review("library.eligible_foods", lambda s, c: s.library.eligible_foods(c.user_id)),
    # other
    Review("reports.list_reports", lambda s, c: s.reports.list_reports(c.user_id, PAGE, 0)),
    Review(
        "schedule.notifications",
        lambda s, c: s.schedule.notifications(c.user_id, c.now, PAGE, 0),
    ),
)


async def load_context(conn: AsyncConnection, user_id: int, now: datetime | None = None) -> Context:
    """The arguments a client of this user would send: the active plan's sessions, the
    newest workout and meal log, an exercise with a current record (else one of the newest
    workout), the profile's level and equipment. Read before the capture starts."""
    now = now or datetime.now(UTC)
    timezone = await conn.scalar(select(AppUser.timezone).where(AppUser.id == user_id))
    if timezone is None:
        raise LookupError(f"no user with id {user_id}")
    sessions = (
        await conn.execute(
            select(TrainingSession.id)
            .join(TrainingPlan, TrainingPlan.id == TrainingSession.training_plan_id)
            .where(TrainingPlan.user_id == user_id, TrainingPlan.status == PlanStatus.ACTIVE)
            .order_by(TrainingSession.id)
        )
    ).scalars()
    workout_id = await conn.scalar(
        select(WorkoutLog.id)
        .where(WorkoutLog.user_id == user_id, WorkoutLog.deleted_at.is_(None))
        .order_by(WorkoutLog.log_date.desc(), WorkoutLog.id.desc())
        .limit(1)
    )
    exercise_id = await conn.scalar(
        select(PersonalRecord.exercise_id)
        .where(PersonalRecord.user_id == user_id, PersonalRecord.is_current)
        .order_by(PersonalRecord.id.desc())
        .limit(1)
    )
    if exercise_id is None and workout_id is not None:
        exercise_id = await conn.scalar(
            select(WorkoutLogExercise.exercise_id)
            .where(WorkoutLogExercise.workout_log_id == workout_id)
            .order_by(WorkoutLogExercise.sort_order)
            .limit(1)
        )
    nutrition_log_id = await conn.scalar(
        select(NutritionLog.id)
        .where(NutritionLog.user_id == user_id, NutritionLog.deleted_at.is_(None))
        .order_by(NutritionLog.log_date.desc(), NutritionLog.id.desc())
        .limit(1)
    )
    limits = (
        await conn.execute(
            select(UserProfile.experience_level, UserProfile.equipment).where(
                UserProfile.user_id == user_id
            )
        )
    ).first()
    return Context(
        user_id=user_id,
        today=now.astimezone(ZoneInfo(timezone)).date(),
        now=now,
        active_session_ids=tuple(sessions),
        workout_id=workout_id,
        exercise_id=exercise_id,
        nutrition_log_id=nutrition_log_id,
        level=None if limits is None else limits.experience_level,
        equipment=None if limits is None else limits.equipment,
    )


# ---------------------------------------------------------------- plans


@dataclass(frozen=True)
class Scan:
    table: str
    node: str  # one of SCAN_NODES
    index: str | None  # for a Bitmap Heap Scan, the bitmap index scans under it
    rows: int  # actual rows over all loops
    # an Index (Only) Scan without an Index Cond: it reads the whole index, for its order
    # (ORDER BY, merge join). With enable_seqscan off this is how a missing index can show
    # instead of a Seq Scan, so the report lists these on large tables; not asserted.
    full: bool = False

    @property
    def large(self) -> bool:
        return self.table in LARGE_TABLES


@dataclass(frozen=True)
class Statement:
    number: int  # 1-based, in the order the method sent it
    sql: str
    scans: tuple[Scan, ...]
    rows: int
    ms: float  # execution time

    def large_seq_scans(self) -> list[Scan]:
        return [s for s in self.scans if s.node == SEQ_SCAN and s.large]


@dataclass(frozen=True)
class MethodPlans:
    method: str
    statements: tuple[Statement, ...]
    skipped: str | None = None  # why the method did not run


class _Capture:
    """before_cursor_execute listener: keeps the SELECTs sent while `on`."""

    def __init__(self) -> None:
        self.on = False
        self.statements: list[tuple[str, Any]] = []

    def __call__(self, conn, cursor, statement, parameters, context, executemany) -> None:
        if self.on and not executemany and SELECT.match(statement):
            params = dict(parameters) if isinstance(parameters, Mapping) else parameters
            self.statements.append((statement, params))


def _node_rows(node: Mapping[str, Any]) -> int:
    return round(node["Actual Rows"] * node["Actual Loops"])


def _bitmap_indexes(node: Mapping[str, Any]) -> Iterator[str]:
    for child in node.get("Plans", ()):
        if child["Node Type"] == "Bitmap Index Scan":
            yield child["Index Name"]
        else:  # BitmapAnd / BitmapOr
            yield from _bitmap_indexes(child)


def scans(node: Mapping[str, Any]) -> Iterator[Scan]:
    """Every table scan of a plan node and its children, init plans and subplans included."""
    kind = node["Node Type"]
    if kind in SCAN_NODES:
        index = (
            ", ".join(_bitmap_indexes(node))
            if kind == "Bitmap Heap Scan"
            else node.get("Index Name")
        )
        full = kind in INDEX_SCANS and "Index Cond" not in node
        yield Scan(node["Relation Name"], kind, index, _node_rows(node), full)
    for child in node.get("Plans", ()):
        yield from scans(child)


async def _explain(conn: AsyncConnection, number: int, sql: str, params: Any) -> Statement:
    # through the driver, as the method's own statement went: same text, same parameters
    driver = (await conn.get_raw_connection()).driver_connection
    cursor = await driver.execute(EXPLAIN + sql, params)
    (output,) = await cursor.fetchone()
    plan = (json.loads(output) if isinstance(output, str) else output)[0]
    return Statement(
        number=number,
        sql=sql,
        scans=tuple(scans(plan["Plan"])),
        rows=_node_rows(plan["Plan"]),
        ms=plan["Execution Time"],
    )


async def review(
    conn: AsyncConnection,
    context: Context,
    *,
    no_seqscan: bool,
    reviews: tuple[Review, ...] = REVIEWS,
) -> list[MethodPlans]:
    """Runs every review on `conn`, inside the transaction the caller began and will roll
    back. Each method gets a fresh session (one unit of work, as in a request) on a
    savepoint of that transaction."""
    if no_seqscan:
        await conn.exec_driver_sql(NO_SEQSCAN)
    sessions = async_sessionmaker(
        bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    capture = _Capture()
    event.listen(conn.sync_connection, "before_cursor_execute", capture)
    results: list[MethodPlans] = []
    try:
        for item in reviews:
            missing = [f for f in item.needs if getattr(context, f) in (None, ())]
            if missing:
                results.append(MethodPlans(item.name, (), skipped=f"no {', '.join(missing)}"))
                continue
            capture.statements.clear()
            capture.on = True
            try:
                async with sessions() as session:
                    await item.call(_stores(session, sessions), context)
            finally:
                capture.on = False
            statements = [
                await _explain(conn, number, sql, params)
                for number, (sql, params) in enumerate(capture.statements, 1)
            ]
            results.append(MethodPlans(item.name, tuple(statements)))
    finally:
        event.remove(conn.sync_connection, "before_cursor_execute", capture)
    return results


def large_seq_scans(results: list[MethodPlans]) -> list[tuple[str, int, Scan]]:
    return [
        (m.method, s.number, scan)
        for m in results
        for s in m.statements
        for scan in s.large_seq_scans()
    ]


# ---------------------------------------------------------------- command line


def _runs(statements: tuple[Statement, ...]) -> Iterator[list[Statement]]:
    """Consecutive statements with the same SQL text: a query sent once per parent row
    (the items of each workout of a page, say) is printed as one line."""
    run: list[Statement] = []
    for statement in statements:
        if run and statement.sql != run[0].sql:
            yield run
            run = []
        run.append(statement)
    if run:
        yield run


def _merged_scans(run: list[Statement]) -> list[Scan]:
    rows: dict[tuple[str, str, str | None, bool], int] = {}
    for statement in run:
        for scan in statement.scans:
            key = (scan.table, scan.node, scan.index, scan.full)
            rows[key] = rows.get(key, 0) + scan.rows
    return [
        Scan(table, node, index, total, full) for (table, node, index, full), total in rows.items()
    ]


def _numbers(run: list[Statement]) -> str:
    first, last = run[0].number, run[-1].number
    return f"#{first}" if first == last else f"#{first}-{last} x{len(run)}"


def _scan_text(scan: Scan) -> str:
    index = f" {scan.index}" if scan.index else ""
    full = " [full]" if scan.full else ""
    return f"{scan.table} -> {scan.node}{index}{full} ({scan.rows})"


def report(context: Context, results: list[MethodPlans], *, no_seqscan: bool) -> str:
    """One line per statement; repeats of the same statement in a row share a line, with
    their rows and times added up."""
    args = ", ".join(
        f"{f.name}={getattr(context, f.name)}" for f in fields(context) if f.name != "now"
    )
    mode = "enable_seqscan = off" if no_seqscan else "planner defaults"
    lines = [f"pass: {mode}", f"arguments: {args}", ""]
    seq_lines, full_lines = [], []
    for m in results:
        if m.skipped:
            lines.append(f"{m.method:<34} skipped ({m.skipped})")
        for run in _runs(m.statements):
            scans_ = _merged_scans(run)
            scanned = "; ".join(_scan_text(scan) for scan in scans_) or "no table scan"
            rows = sum(s.rows for s in run)
            ms = sum(s.ms for s in run)
            lines.append(
                f"{m.method:<34} {_numbers(run):<10} rows {rows:>5} {ms:>8.3f} ms  {scanned}"
            )
            for scan in scans_:
                text = f"  {m.method} {_numbers(run)}: {_scan_text(scan)}"
                if scan.large and scan.node == SEQ_SCAN:
                    seq_lines.append(text)
                elif scan.large and scan.full:
                    full_lines.append(text)
    total = sum(s.ms for m in results for s in m.statements)
    count = sum(len(m.statements) for m in results)
    lines += ["", f"{count} statements, {total:.3f} ms execution in all", ""]
    seq = large_seq_scans(results)
    lines.append(f"Seq Scans on large tables: {len(seq) or 'none'}")
    lines += seq_lines
    lines.append(f"Full index scans on large tables (information): {len(full_lines) or 'none'}")
    return "\n".join(lines + full_lines)


async def _run(email: str, no_seqscan: bool) -> int:
    engine = create_async_engine(database_url())
    try:
        async with engine.connect() as conn:
            await conn.begin()
            try:
                user_id = await conn.scalar(
                    select(AppUser.id).where(func.lower(AppUser.email) == email.lower())
                )
                if user_id is None:
                    print("no user with that email", file=sys.stderr)
                    return 1
                context = await load_context(conn, user_id)
                results = await review(conn, context, no_seqscan=no_seqscan)
            finally:
                await conn.rollback()
    finally:
        await engine.dispose()
    print(report(context, results, no_seqscan=no_seqscan))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EXPLAIN ANALYZE of one user's reads.")
    parser.add_argument("--email", required=True, help="the user whose data is read")
    parser.add_argument(
        "--no-seqscan", action="store_true", help="SET LOCAL enable_seqscan = off first"
    )
    args = parser.parse_args(argv)
    # psycopg's async driver needs a selector loop (the Windows default is the proactor)
    return asyncio.run(_run(args.email, args.no_seqscan), loop_factory=asyncio.SelectorEventLoop)


if __name__ == "__main__":
    sys.exit(main())
