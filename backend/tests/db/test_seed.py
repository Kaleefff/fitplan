"""DB-02: the reference seed loads, a second load changes nothing, and a broken file
changes nothing at all.

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

from app.db.seed import SEED_DIR, SEEDS, SeedError, load, read_rows
from app.db.session import database_url
from tests.db.test_migrations import run_alembic

TEST_DB = "fitplan_seed_test"
TEMPORARY_SEED = SEED_DIR.parent / "dev" / "temporary_training_seed.sql"
TABLES = [table.name for table, _ in SEEDS]


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
        connection.execute(text(f"TRUNCATE {', '.join(TABLES)}, exercise RESTART IDENTITY CASCADE"))
    return engine


@pytest.fixture
def seed_copy(tmp_path: Path) -> Path:
    """A copy of database/seed/ that a test may break."""
    return Path(shutil.copytree(SEED_DIR, tmp_path / "seed"))


def snapshot(engine: Engine) -> dict[str, list[tuple]]:
    with engine.connect() as connection:
        return {
            table: [
                tuple(row) for row in connection.execute(text(f"SELECT * FROM {table} ORDER BY id"))
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

    assert all(r.inserted > 0 and r.updated == 0 for r in first)
    assert all(r.inserted == 0 and r.updated == 0 and r.unchanged > 0 for r in second)
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


def test_temporary_exercises_load_on_top_and_survive_a_reload(db):
    """The temporary exercises (until DB-03) link to the seeded groups and injury types by
    name; a second reference load keeps every link."""
    run(db)
    raw = db.raw_connection()
    try:
        raw.autocommit = True
        raw.cursor().execute(TEMPORARY_SEED.read_text(encoding="utf-8"))
    finally:
        raw.close()

    def state() -> tuple:
        with db.connect() as connection:
            return (
                connection.execute(
                    text("SELECT group_name, id FROM muscle_group ORDER BY id")
                ).all(),
                connection.execute(text("SELECT count(*) FROM exercise_muscle_group")).scalar_one(),
                connection.execute(
                    text("SELECT count(*) FROM injury_type_excluded_exercise")
                ).scalar_one(),
                connection.execute(
                    text(
                        "SELECT count(*) FROM exercise e WHERE NOT EXISTS (SELECT 1 FROM"
                        " exercise_muscle_group l WHERE l.exercise_id = e.id AND l.is_primary)"
                    )
                ).scalar_one(),
            )

    before = state()
    run(db)

    groups, group_links, injury_links, without_primary = before
    assert len(groups) == 10
    assert group_links > 0 and injury_links > 0
    assert without_primary == 0
    assert state() == before


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
