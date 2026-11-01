"""DB-02, DB-03: the reference seed loads, a second load changes nothing, and a broken
file changes nothing at all.

Uses its own throwaway database (fitplan_seed_test) on the PostgreSQL from docker
compose; skipped when PostgreSQL is not reachable. Delete the temporary-seed test
together with database/dev/temporary_training_seed.sql (DB-03).
"""

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError

from app.db.seed import SEED_DIR, SEEDS, TABLES, SeedError, load, read_rows
from app.db.session import database_url
from tests.db.test_migrations import run_alembic

TEST_DB = "fitplan_seed_test"
TEMPORARY_SEED = SEED_DIR.parent / "dev" / "temporary_training_seed.sql"


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    admin = create_engine(database_url().set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect():
            pass
    except OperationalError:
        admin.dispose()
        pytest.skip("PostgreSQL is not reachable: run docker compose up -d")

    def recreate(create: bool) -> None:
        with admin.connect() as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
            if create:
                connection.execute(text(f"CREATE DATABASE {TEST_DB}"))

    recreate(create=True)
    test_engine = create_engine(database_url().set(database=TEST_DB))
    run_alembic(test_engine, "upgrade", "head")
    yield test_engine
    test_engine.dispose()
    recreate(create=False)
    admin.dispose()


@pytest.fixture
def db(engine: Engine) -> Engine:
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
    return engine


@pytest.fixture
def seed_copy(tmp_path: Path) -> Path:
    """A copy of database/seed/ that a test may break."""
    return Path(shutil.copytree(SEED_DIR, tmp_path / "seed"))


def snapshot(engine: Engine) -> dict[str, list[tuple]]:
    with engine.connect() as connection:
        return {
            table: [
                tuple(row)
                for row in connection.execute(text(f"SELECT * FROM {table} ORDER BY 1, 2"))
            ]
            for table in TABLES
        }


def run(engine: Engine, seed_dir: Path = SEED_DIR):
    with engine.begin() as connection:
        return load(connection, seed_dir)


def replace_line(path: Path, old: str, new: str) -> None:
    content = path.read_text(encoding="utf-8")
    assert old in content
    path.write_text(content.replace(old, new, 1), encoding="utf-8")


def test_second_load_gives_identical_data(db):
    first = run(db)
    before = snapshot(db)
    second = run(db)

    assert all(r.updated == 0 and r.deleted == 0 for r in first)
    assert all(r.inserted == 0 and r.updated == 0 and r.deleted == 0 for r in second)
    assert [r.unchanged for r in second] == [r.inserted for r in first]
    assert snapshot(db) == before


def test_muscle_groups_match_algorithms_section_3(db):
    run(db)
    with db.connect() as connection:
        groups = dict(connection.execute(text("SELECT group_name, region FROM muscle_group")).all())

    assert groups == {
        "chest": "upper",
        "back": "upper",
        "shoulders": "upper",
        "biceps": "upper",
        "triceps": "upper",
        "quadriceps": "lower",
        "hamstrings": "lower",
        "glutes": "lower",
        "calves": "lower",
        "core": "core",
    }


def test_allergens_are_eu_14_plus_lactose(db):
    run(db)
    with db.connect() as connection:
        names = set(connection.execute(text("SELECT name FROM allergen")).scalars())

    assert len(names) == 15
    assert {"Gluten", "Milk", "Lactose", "Sulphites"} <= names


def test_changed_row_is_updated_in_place(db, seed_copy):
    run(db)
    with db.connect() as connection:
        chest_id = connection.execute(
            text("SELECT id FROM muscle_group WHERE group_name = 'chest'")
        ).scalar_one()
    replace_line(seed_copy / "muscle_group.csv", "Pectoralis major", "Pectoralis Major")

    results = {r.table: r for r in run(db, seed_copy)}

    assert results["muscle_group"].updated == 1
    assert results["muscle_group"].unchanged == 9
    with db.connect() as connection:
        row = connection.execute(
            text("SELECT id, description FROM muscle_group WHERE group_name = 'chest'")
        ).one()
    assert row.id == chest_id
    assert row.description.startswith("Pectoralis Major")


def test_replaces_temporary_seed_and_keeps_its_ids(db):
    raw = db.raw_connection()
    try:
        raw.autocommit = True
        raw.cursor().execute(TEMPORARY_SEED.read_text(encoding="utf-8"))
    finally:
        raw.close()
    query = "SELECT name, id FROM exercise UNION ALL SELECT group_name, id FROM muscle_group"
    with db.connect() as connection:
        before = {row[0]: row[1] for row in connection.execute(text(query))}

    run(db)

    with db.connect() as connection:
        after = {row[0]: row[1] for row in connection.execute(text(query))}
        placeholders = (
            connection.execute(
                text(
                    "SELECT name FROM exercise WHERE description = 'Temporary seed'"
                    " UNION ALL SELECT group_name FROM muscle_group"
                    " WHERE description = 'Temporary seed'"
                )
            )
            .scalars()
            .all()
        )
    assert placeholders == ["Plank"]
    assert {name: after[name] for name in before} == before


def test_broken_file_changes_nothing(db, seed_copy):
    run(db)
    before = snapshot(db)
    replace_line(seed_copy / "muscle_group.csv", "Pectoralis major", "Pectoralis Major")
    replace_line(seed_copy / "injury_type.csv", 'running.",21', 'running.",0')

    with pytest.raises(SeedError, match="injury_type_avg_healing_time_days_check"):
        run(db, seed_copy)

    assert snapshot(db) == before


@pytest.mark.parametrize(
    ("file", "old", "new", "message"),
    [
        ("allergen.csv", "Lupin,", "Gluten,", "duplicate name 'Gluten'"),
        ("allergen.csv", "Lupin,", "Lupin,extra,", "wrong number of fields"),
        ("food_category.csv", "category_name,description", "category_name,descr", "unknown"),
        ("muscle_group.csv", "calves,lower", "calves,legs", "not a valid BodyRegion"),
        ("injury_type.csv", "type_name,", "id,type_name,", "ids are generated"),
    ],
)
def test_file_errors_are_reported(seed_copy, file, old, new, message):
    replace_line(seed_copy / file, old, new)
    table, key = next((t, k) for t, k in SEEDS if f"{t.name}.csv" == file)

    with pytest.raises(SeedError, match=message):
        read_rows(seed_copy / file, table, key)


# ---------------------------------------------------------------- exercises (DB-03)

EXERCISES = """\
name,difficulty_level,equipment,is_compound,is_bodyweight,primary_group,secondary_groups,description,instruction
Push-up,beginner,none,true,true,chest,triceps;shoulders,Press up from the floor.,Lower and press up.
Plank,beginner,none,false,true,core,,Hold a straight line on the forearms.,Brace and hold.
"""
EXCLUSIONS = "injury_type,exercise\nWrist sprain,Push-up\n"
EXERCISE_TABLES = ["exercise", "exercise_muscle_group", "injury_type_excluded_exercise"]


@pytest.fixture
def exercise_seed(seed_copy: Path) -> Path:
    (seed_copy / "exercise.csv").write_text(EXERCISES, encoding="utf-8")
    (seed_copy / "injury_type_excluded_exercise.csv").write_text(EXCLUSIONS, encoding="utf-8")
    return seed_copy


def links(engine: Engine) -> set[tuple]:
    with engine.connect() as connection:
        return {
            tuple(row)
            for row in connection.execute(
                text(
                    "SELECT e.name, m.group_name, l.is_primary FROM exercise_muscle_group l"
                    " JOIN exercise e ON e.id = l.exercise_id"
                    " JOIN muscle_group m ON m.id = l.muscle_group_id"
                )
            )
        }


def exclusions(engine: Engine) -> set[tuple]:
    with engine.connect() as connection:
        return {
            tuple(row)
            for row in connection.execute(
                text(
                    "SELECT t.type_name, e.name FROM injury_type_excluded_exercise x"
                    " JOIN injury_type t ON t.id = x.injury_type_id"
                    " JOIN exercise e ON e.id = x.exercise_id"
                )
            )
        }


def by_table(results) -> dict:
    return {r.table: r for r in results}


def test_exercises_load_with_groups_and_exclusions(db, exercise_seed):
    first = by_table(run(db, exercise_seed))
    second = by_table(run(db, exercise_seed))

    assert links(db) == {
        ("Push-up", "chest", True),
        ("Push-up", "triceps", False),
        ("Push-up", "shoulders", False),
        ("Plank", "core", True),
    }
    assert exclusions(db) == {("Wrist sprain", "Push-up")}
    assert [first[t].inserted for t in EXERCISE_TABLES] == [2, 4, 1]
    assert [second[t].unchanged for t in EXERCISE_TABLES] == [2, 4, 1]
    assert all(
        second[t].inserted + second[t].updated + second[t].deleted == 0 for t in EXERCISE_TABLES
    )


def test_changed_groups_are_moved_and_the_exercise_id_kept(db, exercise_seed):
    run(db, exercise_seed)
    with db.connect() as connection:
        before = connection.execute(
            text("SELECT id FROM exercise WHERE name = 'Push-up'")
        ).scalar_one()
    replace_line(exercise_seed / "exercise.csv", "chest,triceps;shoulders", "triceps,chest")

    result = by_table(run(db, exercise_seed))["exercise_muscle_group"]

    assert (result.inserted, result.updated, result.deleted) == (0, 2, 1)
    assert links(db) == {
        ("Push-up", "triceps", True),
        ("Push-up", "chest", False),
        ("Plank", "core", True),
    }
    with db.connect() as connection:
        after = connection.execute(
            text("SELECT id FROM exercise WHERE name = 'Push-up'")
        ).scalar_one()
    assert after == before


def test_exclusion_no_longer_listed_is_deleted(db, exercise_seed):
    run(db, exercise_seed)
    (exercise_seed / "injury_type_excluded_exercise.csv").write_text(
        "injury_type,exercise\n", encoding="utf-8"
    )

    result = by_table(run(db, exercise_seed))["injury_type_excluded_exercise"]

    assert result.deleted == 1
    assert exclusions(db) == set()


@pytest.mark.parametrize(
    ("file", "old", "new", "message"),
    [
        ("exercise.csv", "chest,triceps;shoulders", "chest,triceps;chest", "listed twice"),
        ("exercise.csv", "chest,triceps;shoulders", "chest,triceps;forearms", "unknown muscle"),
        ("exercise.csv", ",core,,", ",,,", r"empty \['primary_group'\]"),
        ("exercise.csv", "Brace and hold.", "", r"empty \['instruction'\]"),
        ("exercise.csv", "beginner,none,false", "beginner,bands,false", "not a valid Equipment"),
        ("exercise.csv", ",is_bodyweight,", ",", r"columns \['is_bodyweight'\] missing"),
        ("injury_type_excluded_exercise.csv", ",Push-up", ",Burpee", "not in exercise.csv"),
        ("injury_type_excluded_exercise.csv", "Wrist sprain,", "Broken wrist,", "unknown injury"),
        (
            "injury_type_excluded_exercise.csv",
            "Wrist sprain,Push-up\n",
            "Wrist sprain,Push-up\nWrist sprain,Push-up\n",
            "duplicate",
        ),
    ],
)
def test_broken_exercise_files_change_nothing(db, exercise_seed, file, old, new, message):
    run(db, exercise_seed)
    before = snapshot(db)
    replace_line(exercise_seed / file, old, new)

    with pytest.raises(SeedError, match=message):
        run(db, exercise_seed)

    assert snapshot(db) == before
