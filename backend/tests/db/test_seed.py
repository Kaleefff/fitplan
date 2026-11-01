"""DB-02, DB-03, DB-04: the reference seed loads, a second load changes nothing, and a broken
file changes nothing at all.

Uses its own throwaway database (fitplan_seed_test) on the PostgreSQL from docker
compose; skipped when PostgreSQL is not reachable.
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


# ---------------------------------------------------------------- foods (DB-04)

FOODS = """\
name,cals_per_100g,protein_per_100g,fat_per_100g,carbs_per_100g,diet_role,suitable_meal_types,\
is_vegetarian,is_vegan,default_portion_g,min_portion_g,max_portion_g,portion_step_g,categories,\
allergens,source
Tofu,144,17.3,8.7,2.8,protein,breakfast;lunch;dinner,true,true,150,50,300,10,Plant proteins,\
Soybeans,FDC:172475
Bagel,264,10.6,1.32,52.4,carb,breakfast;lunch,true,true,90,50,150,10,Bread and bakery,\
Gluten;Sesame,FDC:174899
Goulash,75,8.3,2.8,3.6,dish,lunch;dinner,false,false,350,200,500,50,Prepared dishes,,SLV:1068
"""
FOOD_TABLES = ["food_item", "food_item_category", "food_item_allergen"]


@pytest.fixture
def food_seed(seed_copy: Path) -> Path:
    (seed_copy / "food_item.csv").write_text(FOODS, encoding="utf-8")
    return seed_copy


def food_links(engine: Engine) -> dict[str, set[tuple]]:
    queries = {
        "categories": "SELECT f.name, c.category_name FROM food_item_category l"
        " JOIN food_item f ON f.id = l.food_item_id"
        " JOIN food_category c ON c.id = l.food_category_id",
        "allergens": "SELECT f.name, a.name FROM food_item_allergen l"
        " JOIN food_item f ON f.id = l.food_item_id JOIN allergen a ON a.id = l.allergen_id",
    }
    with engine.connect() as connection:
        return {k: {tuple(r) for r in connection.execute(text(q))} for k, q in queries.items()}


def food_row(engine: Engine, name: str):
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT id, suitable_meal_types::text[] AS meals, is_active"
                " FROM food_item WHERE name = :name"
            ),
            {"name": name},
        ).one()


def test_foods_load_with_categories_and_allergens(db, food_seed):
    first = by_table(run(db, food_seed))
    second = by_table(run(db, food_seed))

    assert food_links(db) == {
        "categories": {
            ("Tofu", "Plant proteins"),
            ("Bagel", "Bread and bakery"),
            ("Goulash", "Prepared dishes"),
        },
        "allergens": {("Tofu", "Soybeans"), ("Bagel", "Gluten"), ("Bagel", "Sesame")},
    }
    assert food_row(db, "Tofu").meals == ["breakfast", "lunch", "dinner"]
    assert [first[t].inserted for t in FOOD_TABLES] == [3, 3, 3]
    assert [second[t].unchanged for t in FOOD_TABLES] == [3, 3, 3]
    assert all(second[t].inserted + second[t].updated + second[t].deleted == 0 for t in FOOD_TABLES)


def test_changed_food_is_updated_and_its_links_synced(db, food_seed):
    run(db, food_seed)
    before = food_row(db, "Bagel").id
    replace_line(food_seed / "food_item.csv", "breakfast;lunch,true", "breakfast,true")
    replace_line(food_seed / "food_item.csv", "Gluten;Sesame", "Gluten")

    results = by_table(run(db, food_seed))

    assert results["food_item"].updated == 1
    assert results["food_item_allergen"].deleted == 1
    assert ("Bagel", "Sesame") not in food_links(db)["allergens"]
    assert food_row(db, "Bagel").id == before
    assert food_row(db, "Bagel").meals == ["breakfast"]


def test_a_reload_keeps_is_active(db, food_seed):
    run(db, food_seed)
    with db.begin() as connection:
        connection.execute(text("UPDATE food_item SET is_active = false WHERE name = 'Bagel'"))

    run(db, food_seed)

    assert food_row(db, "Bagel").is_active is False


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("Plant proteins,", "Tofu products,", "unknown categories"),
        ("Plant proteins,", ",", r"empty \['categories'\]"),
        ("Plant proteins,", ";,", "no categories"),
        ("Gluten;Sesame", "Gluten;Celery stalks", "unknown allergens"),
        ("Gluten;Sesame", "Gluten;Gluten", "listed twice"),
        ("breakfast;lunch,true", "brunch;lunch,true", "not a valid MealType"),
        ("breakfast;lunch,true", "lunch;lunch,true", "listed twice"),
        ("dish,lunch", "starter,lunch", "not a valid DietRole"),
        (",SLV:1068", ",USDA", "source 'USDA'"),
        ("150,50,300,10", "150,50,300,", r"empty \['portion_step_g'\]"),
        ("true,true,150", "false,true,150", "food_item_check"),
        ("350,200,500,50", "550,200,500,50", "food_item_check1"),
    ],
)
def test_broken_food_file_changes_nothing(db, food_seed, old, new, message):
    run(db, food_seed)
    before = snapshot(db)
    replace_line(food_seed / "food_item.csv", old, new)

    with pytest.raises(SeedError, match=message):
        run(db, food_seed)

    assert snapshot(db) == before
