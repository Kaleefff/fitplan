"""DB-01: the baseline migrates both ways; deleting a user removes every row it owns (FR-U5);
updated_at moves on every update, soft deletes included.

These tests need the PostgreSQL from docker compose. They create a throwaway database
(fitplan_test) on it, drop it afterwards, and are skipped when PostgreSQL is not reachable.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, delete, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.enums import (
    AdjustmentReason,
    BodyRegion,
    DietRole,
    DifficultyLevel,
    EquipmentType,
    GoalType,
    InjurySeverity,
    MealType,
    NotificationType,
    ReportType,
    SexType,
)
from app.db.models import (
    Allergen,
    AppUser,
    BodyMetrics,
    DevicePushToken,
    DietPlan,
    Exercise,
    FoodCategory,
    FoodItem,
    Injury,
    InjuryType,
    Meal,
    MealFoodItem,
    MuscleGroup,
    Notification,
    NutritionLog,
    NutritionLogFoodItem,
    OauthIdentity,
    PasswordResetToken,
    PersonalRecord,
    PlanAdjustment,
    ProgressReport,
    RefreshToken,
    Reminder,
    SessionExercise,
    TrainingPlan,
    TrainingSession,
    UserAllergen,
    UserExcludedFood,
    UserProfile,
    WorkoutLog,
    WorkoutLogExercise,
    WorkoutSet,
)
from app.db.session import database_url

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DB = "fitplan_test"
ENUM_COUNT = 13
TABLES_WITH_UPDATED_AT = ("workout_log", "nutrition_log", "body_metrics")

# Shared library data: not owned by a user, must survive a user's deletion.
REFERENCE_TABLES = frozenset(
    {
        "allergen",
        "food_category",
        "food_item",
        "food_item_category",
        "food_item_allergen",
        "muscle_group",
        "exercise",
        "exercise_muscle_group",
        "injury_type",
        "injury_type_excluded_exercise",
    }
)
USER_OWNED_TABLES = sorted(set(Base.metadata.tables) - REFERENCE_TABLES)


def run_alembic(engine: Engine, action: str, revision: str) -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        config.attributes["configure_logger"] = False
        getattr(command, action)(config, revision)


@pytest.fixture(scope="module")
def admin_engine() -> Iterator[Engine]:
    engine = create_engine(database_url().set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect():
            pass
    except OperationalError:
        engine.dispose()
        pytest.skip("PostgreSQL is not reachable: run docker compose up -d")
    yield engine
    engine.dispose()


@pytest.fixture
def empty_db(admin_engine: Engine) -> Iterator[Engine]:
    def recreate(create: bool) -> None:
        with admin_engine.connect() as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
            if create:
                connection.execute(text(f"CREATE DATABASE {TEST_DB}"))

    recreate(create=True)
    engine = create_engine(database_url().set(database=TEST_DB))
    yield engine
    engine.dispose()
    recreate(create=False)


@pytest.fixture
def migrated_db(empty_db: Engine) -> Engine:
    run_alembic(empty_db, "upgrade", "head")
    return empty_db


def test_baseline_upgrades_and_downgrades(empty_db: Engine) -> None:
    run_alembic(empty_db, "upgrade", "head")
    with empty_db.connect() as connection:
        inspector = inspect(connection)
        assert set(inspector.get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
        assert inspector.get_view_names() == ["workout_log_summary"]
        assert len(inspector.get_enums()) == ENUM_COUNT

    run_alembic(empty_db, "downgrade", "base")
    with empty_db.connect() as connection:
        inspector = inspect(connection)
        assert inspector.get_table_names() == ["alembic_version"]
        assert inspector.get_view_names() == []
        assert inspector.get_enums() == []
        functions = connection.execute(
            text("SELECT count(*) FROM pg_proc WHERE proname = 'set_updated_at'")
        ).scalar_one()
        assert functions == 0

    # A full downgrade leaves nothing behind that blocks the next upgrade.
    run_alembic(empty_db, "upgrade", "head")


def diet_roles(engine: Engine) -> list[str]:
    with engine.connect() as connection:
        return list(
            connection.execute(text("SELECT unnest(enum_range(NULL::diet_role))::text")).scalars()
        )


def add_food_with_role(engine: Engine, role: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO food_item (name, cals_per_100g, protein_per_100g, fat_per_100g,"
                " carbs_per_100g, diet_role, suitable_meal_types, default_portion_g,"
                " min_portion_g, max_portion_g, portion_step_g)"
                " VALUES (:name, 42, 0, 0, 10.6, CAST(:role AS diet_role), '{snack}',"
                " 330, 100, 500, 10)"
            ),
            {"name": f"{role} food", "role": role},
        )


def test_0002_adds_the_other_role_and_its_downgrade_keeps_the_rest(empty_db: Engine) -> None:
    roles = [role.value for role in DietRole]
    run_alembic(empty_db, "upgrade", "0001")
    assert diet_roles(empty_db) == roles[:-1]
    add_food_with_role(empty_db, "dish")

    run_alembic(empty_db, "upgrade", "head")
    assert diet_roles(empty_db) == roles
    assert roles[-1] == "other"

    run_alembic(empty_db, "downgrade", "0001")
    assert diet_roles(empty_db) == roles[:-1]
    with empty_db.connect() as connection:
        kept = connection.execute(text("SELECT diet_role::text FROM food_item")).scalar_one()
    assert kept == "dish"


def test_0002_downgrade_refuses_while_a_food_uses_other(empty_db: Engine) -> None:
    run_alembic(empty_db, "upgrade", "head")
    add_food_with_role(empty_db, "other")
    with pytest.raises(Exception, match="diet_role 'other'"):
        run_alembic(empty_db, "downgrade", "0001")
    assert diet_roles(empty_db)[-1] == "other"


ADD_MEASUREMENT = text(
    "INSERT INTO body_metrics (user_id, measured_on, weight, client_uuid)"
    " VALUES (:u, current_date - :days, 80, :c)"
)


def test_0003_makes_client_uuid_unique_per_user_and_its_downgrade_refuses_shared_ones(
    empty_db: Engine,
) -> None:
    run_alembic(empty_db, "upgrade", "head")
    shared = uuid.uuid4()
    with empty_db.begin() as connection:
        users = (
            connection.execute(
                text(
                    "INSERT INTO app_user (email, password_hash, name, surname) VALUES"
                    " ('a@example.com', 'x', 'A', 'A'), ('b@example.com', 'x', 'B', 'B')"
                    " RETURNING id"
                )
            )
            .scalars()
            .all()
        )
        for user_id in users:
            connection.execute(ADD_MEASUREMENT, {"u": user_id, "days": 0, "c": shared})
    with pytest.raises(IntegrityError), empty_db.begin() as connection:
        connection.execute(ADD_MEASUREMENT, {"u": users[0], "days": 1, "c": shared})

    with pytest.raises(Exception, match="share a client_uuid"):
        run_alembic(empty_db, "downgrade", "0002")
    with empty_db.begin() as connection:
        connection.execute(text("DELETE FROM body_metrics WHERE user_id = :u"), {"u": users[1]})
    run_alembic(empty_db, "downgrade", "0002")
    with pytest.raises(IntegrityError), empty_db.begin() as connection:
        connection.execute(ADD_MEASUREMENT, {"u": users[1], "days": 0, "c": shared})


def test_0003_links_existing_records_to_their_workout_and_downgrades(empty_db: Engine) -> None:
    run_alembic(empty_db, "upgrade", "0002")
    with empty_db.begin() as connection:

        def insert(sql: str, **params) -> int:
            return connection.execute(text(sql + " RETURNING id"), params).scalar_one()

        user_id = insert(
            "INSERT INTO app_user (email, password_hash, name, surname)"
            " VALUES ('a@example.com', 'x', 'A', 'A')"
        )
        exercise_ids = [
            insert(
                "INSERT INTO exercise (name, difficulty_level, equipment, is_bodyweight,"
                " description, instruction) VALUES (:n, 'beginner', 'gym', false, '', '')",
                n=name,
            )
            for name in ("Bench press", "Back squat")
        ]
        workout_id = insert(
            "INSERT INTO workout_log (user_id, log_date, rpe_rating) VALUES (:u, current_date, 8)",
            u=user_id,
        )
        add_record = (
            "INSERT INTO personal_record (user_id, exercise_id, max_weight, max_reps, e1rm,"
            " achieved_date) VALUES (:u, :e, 60, 10, 80, current_date)"
        )
        named = insert(add_record, u=user_id, e=exercise_ids[0])
        unnamed = insert(add_record, u=user_id, e=exercise_ids[1])
        connection.execute(
            text(
                "INSERT INTO notification (user_id, message_type, scheduled_at, message, data)"
                " VALUES (:u, 'achievement', now(), 'New personal record', CAST(:d AS jsonb))"
            ),
            {
                "u": user_id,
                "d": f'{{"workout_log_id": {workout_id}, "personal_record_id": {named}}}',
            },
        )

    run_alembic(empty_db, "upgrade", "head")
    with empty_db.connect() as connection:
        linked = dict(
            connection.execute(text("SELECT id, workout_log_id FROM personal_record")).all()
        )
    assert linked == {named: workout_id, unnamed: None}

    run_alembic(empty_db, "downgrade", "0002")
    with empty_db.connect() as connection:
        columns = [c["name"] for c in inspect(connection).get_columns("personal_record")]
    assert "workout_log_id" not in columns


def add_user_with_a_row_everywhere(s: Session) -> int:
    """One user with at least one row in every user-owned table, plus the library rows it needs."""
    today = date.today()
    now = datetime.now(UTC)

    allergen = Allergen(name="gluten", description="Cereals containing gluten")
    category = FoodCategory(category_name="grains", description="Grains and cereals")
    food = FoodItem(
        name="oats",
        cals_per_100g=Decimal("389"),
        protein_per_100g=Decimal("16.9"),
        fat_per_100g=Decimal("6.9"),
        carbs_per_100g=Decimal("66.3"),
        diet_role=DietRole.CARB,
        suitable_meal_types=[MealType.BREAKFAST],
        is_vegetarian=True,
        is_vegan=True,
        default_portion_g=Decimal("60"),
        min_portion_g=Decimal("30"),
        max_portion_g=Decimal("120"),
        portion_step_g=Decimal("10"),
    )
    group = MuscleGroup(group_name="chest", region=BodyRegion.UPPER, description="Chest")
    exercise = Exercise(
        name="push-up",
        difficulty_level=DifficultyLevel.BEGINNER,
        equipment=EquipmentType.NONE,
        is_bodyweight=True,
        description="Push-up",
        instruction="Lower the chest, push back up",
    )
    injury_type = InjuryType(
        type_name="shoulder strain", description="Strained shoulder", avg_healing_time_days=21
    )
    user = AppUser(email="user@example.com", password_hash="x", name="Test", surname="User")
    s.add_all([allergen, category, food, group, exercise, injury_type, user])
    s.flush()

    diet_plan = DietPlan(
        user_id=user.id,
        name="Diet",
        goal=GoalType.MUSCLE_GAIN,
        meals_per_day=3,
        daily_cal_goal=2800,
        protein_goal=Decimal("160"),
        fat_goal=Decimal("80"),
        carbs_goal=Decimal("350"),
    )
    training_plan = TrainingPlan(
        user_id=user.id,
        plan_name="Training",
        goal=GoalType.MUSCLE_GAIN,
        num_training_days=3,
        experience_level=DifficultyLevel.BEGINNER,
        equipment=EquipmentType.GYM,
    )
    s.add_all(
        [
            diet_plan,
            training_plan,
            UserProfile(
                user_id=user.id,
                age=30,
                sex=SexType.MALE,
                current_weight=Decimal("80"),
                height=180,
                activity_level_pal=Decimal("1.55"),
                goal=GoalType.MUSCLE_GAIN,
                experience_level=DifficultyLevel.BEGINNER,
                equipment=EquipmentType.GYM,
                tdee=2800,
            ),
            RefreshToken(
                user_id=user.id,
                family_id=uuid.uuid4(),
                token_hash="a" * 64,
                expires_at=now + timedelta(days=30),
            ),
            PasswordResetToken(
                user_id=user.id, token_hash="b" * 64, expires_at=now + timedelta(hours=1)
            ),
            OauthIdentity(user_id=user.id, provider="google", subject="subject-1"),
            Notification(
                user_id=user.id,
                message_type=NotificationType.MOTIVATIONAL,
                scheduled_at=now,
                message="Keep going",
            ),
            Reminder(
                user_id=user.id,
                message_type=NotificationType.MEAL_REMINDER,
                time_of_day=time(8, 0),
                message="Breakfast",
            ),
            DevicePushToken(user_id=user.id, token="push-token", platform="android"),
            UserAllergen(user_id=user.id, allergen_id=allergen.id),
            UserExcludedFood(user_id=user.id, food_item_id=food.id),
            Injury(
                user_id=user.id,
                injury_type_id=injury_type.id,
                affected_muscle_group_id=group.id,
                severity=InjurySeverity.MILD,
                start_date=today,
            ),
            PersonalRecord(
                user_id=user.id,
                exercise_id=exercise.id,
                max_weight=Decimal("0"),
                max_reps=20,
                e1rm=Decimal("0"),
                achieved_date=today,
            ),
            BodyMetrics(user_id=user.id, measured_on=today, weight=Decimal("80")),
            ProgressReport(
                user_id=user.id,
                report_type=ReportType.WEEKLY,
                report_period_start=today - timedelta(days=6),
                report_period_end=today,
                training_volume=Decimal("0"),
                training_sessions_completed=0,
                training_sessions_planned=0,
            ),
        ]
    )
    s.flush()

    meal = Meal(
        diet_plan_id=diet_plan.id,
        day_index=1,
        meal_type=MealType.BREAKFAST,
        meal_order=1,
        planned_time=time(8, 0),
        planned_cals=700,
        planned_protein=Decimal("40"),
        planned_fat=Decimal("20"),
        planned_carbs=Decimal("90"),
    )
    training_session = TrainingSession(
        training_plan_id=training_plan.id,
        session_order=1,
        session_name="Push",
        day_of_week=1,
        estimated_duration=60,
    )
    s.add_all([meal, training_session])
    s.flush()

    session_exercise = SessionExercise(
        training_session_id=training_session.id,
        exercise_id=exercise.id,
        sort_order=1,
        planned_sets=3,
        planned_reps=10,
        rest_seconds=90,
    )
    nutrition_log = NutritionLog(
        user_id=user.id,
        log_date=today,
        meal_type=MealType.BREAKFAST,
        planned_meal_id=meal.id,
        actual_cals=Decimal("234"),
        actual_protein=Decimal("10.1"),
        actual_fat=Decimal("4.1"),
        actual_carbs=Decimal("39.8"),
    )
    workout_log = WorkoutLog(
        user_id=user.id, training_session_id=training_session.id, log_date=today, rpe_rating=7
    )
    s.add_all([session_exercise, nutrition_log, workout_log])
    s.flush()

    log_exercise = WorkoutLogExercise(
        workout_log_id=workout_log.id,
        exercise_id=exercise.id,
        session_exercise_id=session_exercise.id,
        sort_order=1,
    )
    s.add_all(
        [
            log_exercise,
            MealFoodItem(meal_id=meal.id, food_item_id=food.id, grams=Decimal("60")),
            NutritionLogFoodItem(
                nutrition_log_id=nutrition_log.id, food_item_id=food.id, grams=Decimal("60")
            ),
            PlanAdjustment(
                session_exercise_id=session_exercise.id,
                workout_log_id=workout_log.id,
                reason=AdjustmentReason.PROGRESSION,
                old_sets=3,
                new_sets=3,
                old_reps=10,
                new_reps=12,
            ),
        ]
    )
    s.flush()
    s.add(WorkoutSet(workout_log_exercise_id=log_exercise.id, set_number=1, reps=10))
    s.flush()
    return user.id


def row_counts(engine: Engine, tables: list[str]) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in tables
        }


def test_deleting_a_user_leaves_no_owned_row(migrated_db: Engine) -> None:
    with Session(migrated_db) as s:
        user_id = add_user_with_a_row_everywhere(s)
        s.commit()

    before = row_counts(migrated_db, USER_OWNED_TABLES)
    empty = sorted(table for table, n in before.items() if n == 0)
    assert empty == [], f"seed a row for these tables or mark them as reference: {empty}"

    with migrated_db.begin() as connection:
        connection.execute(delete(AppUser).where(AppUser.id == user_id))

    assert row_counts(migrated_db, USER_OWNED_TABLES) == dict.fromkeys(USER_OWNED_TABLES, 0)
    # The shared library is untouched.
    assert all(
        n > 0 for n in row_counts(migrated_db, ["allergen", "food_item", "exercise"]).values()
    )


def test_updated_at_moves_on_update(migrated_db: Engine) -> None:
    with Session(migrated_db) as s:
        user_id = add_user_with_a_row_everywhere(s)
        s.commit()

    def read_updated_at() -> dict[str, datetime]:
        with migrated_db.connect() as connection:
            return {
                table: connection.execute(
                    text(f"SELECT updated_at FROM {table} WHERE user_id = :user_id"),
                    {"user_id": user_id},
                ).scalar_one()
                for table in TABLES_WITH_UPDATED_AT
            }

    before = read_updated_at()
    with migrated_db.begin() as connection:
        for table in TABLES_WITH_UPDATED_AT:  # a soft delete is an update; sync must see it
            connection.execute(
                text(f"UPDATE {table} SET deleted_at = now() WHERE user_id = :user_id"),
                {"user_id": user_id},
            )
    after = read_updated_at()

    assert all(after[table] > before[table] for table in TABLES_WITH_UPDATED_AT)
