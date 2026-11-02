"""Reference seed loader (DB-02, DB-03, DB-04).

Loads the CSV files of database/seed/ into PostgreSQL. Each file is named after its
table and its header row uses the table's column names. The natural key (the name
column) identifies a row, so the loader is idempotent: new names are inserted,
changed rows are updated, identical rows are left alone. Rows that are no longer
in a file are kept, because user data may reference them.

Exercises (DB-03) carry their muscle groups in two extra columns: `primary_group`
(exactly one) and `secondary_groups` (names separated by `;`, may be empty).
`injury_type_excluded_exercise.csv` lists `injury_type,exercise` name pairs. For the
exercises in exercise.csv both files are authoritative: links that are no longer
listed are deleted (no user data references a link row).

Foods (DB-04): `suitable_meal_types` lists meal types separated by `;`; `categories`
(at least one) and `allergens` (may be empty) list names the same way, and the food's
category and allergen links are synced like the exercise links. `source` cites where
the values per 100 g come from (`FDC:<id>` for USDA FoodData Central, `SLV:<number>` for
the Swedish Food Agency); it is checked but not stored. `is_active` and
`recognition_label` are not in the file, so a load never changes them.

Run from backend/:  uv run python -m app.db.seed  [--dir PATH]
"""

import argparse
import csv
import enum
import re
import sys
from collections.abc import Collection
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import (
    ARRAY,
    Column,
    Connection,
    Table,
    delete,
    literal_column,
    or_,
    select,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError

from app.db.models import (
    Allergen,
    Exercise,
    ExerciseMuscleGroup,
    FoodCategory,
    FoodItem,
    FoodItemAllergen,
    FoodItemCategory,
    InjuryType,
    InjuryTypeExcludedExercise,
    MuscleGroup,
)
from app.db.session import create_sync_engine

SEED_DIR = Path(__file__).resolve().parents[3] / "database" / "seed"

SEEDS: list[tuple[Table, str]] = [
    (MuscleGroup.__table__, "group_name"),
    (InjuryType.__table__, "type_name"),
    (Allergen.__table__, "name"),
    (FoodCategory.__table__, "category_name"),
]

EXERCISE: Table = Exercise.__table__
EXERCISE_GROUP: Table = ExerciseMuscleGroup.__table__
EXCLUSION: Table = InjuryTypeExcludedExercise.__table__
GROUP_COLUMNS = ("primary_group", "secondary_groups")
EXCLUSION_HEADER = ["injury_type", "exercise"]

FOOD: Table = FoodItem.__table__
FOOD_CATEGORY: Table = FoodItemCategory.__table__
FOOD_ALLERGEN: Table = FoodItemAllergen.__table__
FOOD_EXTRA = ("categories", "allergens", "source")
FOOD_NOT_IN_FILE = ("id", "is_active", "recognition_label")
FOOD_SOURCE = re.compile(r"(FDC|SLV):[1-9][0-9]*")

# every table the loader writes, parents first
TABLES: list[str] = [table.name for table, _ in SEEDS] + [
    EXERCISE.name,
    EXERCISE_GROUP.name,
    EXCLUSION.name,
    FOOD.name,
    FOOD_CATEGORY.name,
    FOOD_ALLERGEN.name,
]

TRUE_VALUES = {"true", "t", "yes", "1"}
FALSE_VALUES = {"false", "f", "no", "0"}


class SeedError(Exception):
    """A seed file does not match its table."""


@dataclass
class TableResult:
    table: str
    inserted: int = 0
    updated: int = 0
    deleted: int = 0
    unchanged: int = 0


def convert(table: Table, column: str, raw: str) -> Any:
    """CSV text to the column's Python type; an empty field is NULL."""
    if raw == "":
        return None
    column_type = table.c[column].type
    if isinstance(column_type, ARRAY):
        values = split_names(raw)
        if len(set(values)) != len(values):
            raise ValueError(f"{column}: a value is listed twice in {raw!r}")
        return [convert_value(column_type.item_type.python_type, v) for v in values]
    return convert_value(column_type.python_type, raw)


def convert_value(python_type: type, raw: str) -> Any:
    if python_type is bool:
        value = raw.strip().lower()
        if value in TRUE_VALUES:
            return True
        if value in FALSE_VALUES:
            return False
        raise ValueError(f"not a boolean: {raw!r}")
    if issubclass(python_type, enum.Enum):
        return python_type(raw)
    if python_type in (int, Decimal):
        return python_type(raw)
    return raw


def seed_file(seed_dir: Path, name: str) -> Path:
    path = seed_dir / f"{name}.csv"
    if not path.is_file():
        raise SeedError(f"missing seed file {path}")
    return path


def read_rows(
    path: Path,
    table: Table,
    key: str,
    extra: Collection[str] = (),
    required: Collection[str] = (),
) -> list[dict[str, Any]]:
    """Rows of a seed file; `extra` columns are not in the table and stay raw text."""
    with path.open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        header = reader.fieldnames or []
        unknown = [name for name in header if name not in table.c and name not in extra]
        if unknown:
            raise SeedError(f"{path.name}: unknown columns {unknown}")
        if key not in header:
            raise SeedError(f"{path.name}: key column {key!r} missing")
        missing = [name for name in required if name not in header]
        if missing:
            raise SeedError(f"{path.name}: columns {missing} missing")
        if "id" in header:
            raise SeedError(f"{path.name}: ids are generated, remove the id column")

        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for line, record in enumerate(reader, start=2):
            if None in record or None in record.values():
                raise SeedError(f"{path.name}:{line}: wrong number of fields")
            if record[key] in seen:
                raise SeedError(f"{path.name}:{line}: duplicate {key} {record[key]!r}")
            seen.add(record[key])
            try:
                rows.append(
                    {
                        col: raw if col in extra else convert(table, col, raw)
                        for col, raw in record.items()
                    }
                )
            except ValueError as error:
                raise SeedError(f"{path.name}:{line}: {error}") from error
    return rows


def upsert(conn: Connection, table: Table, key: str, rows: list[dict[str, Any]]) -> TableResult:
    """Insert new keys, update changed rows, skip identical ones."""
    result = TableResult(table.name)
    if not rows:
        return result
    columns = [col for col in rows[0] if col != key]
    stmt = insert(table).values(rows)
    changed = or_(*(table.c[col].is_distinct_from(stmt.excluded[col]) for col in columns))
    stmt = stmt.on_conflict_do_update(
        index_elements=[key],
        set_={col: stmt.excluded[col] for col in columns},
        where=changed,
    ).returning(literal_column("xmax = 0").label("inserted"))
    try:
        written = conn.execute(stmt).scalars().all()
    except DBAPIError as error:
        raise SeedError(f"{table.name}.csv: {error.orig}".strip()) from None
    result.inserted = sum(written)
    result.updated = len(written) - result.inserted
    result.unchanged = len(rows) - len(written)
    return result


def name_ids(conn: Connection, name: Column) -> dict[str, int]:
    return {row[0]: row[1] for row in conn.execute(select(name, name.table.c.id))}


def sync_links(
    conn: Connection,
    table: Table,
    keys: tuple[str, str],
    scope: tuple[str, set[int]],
    desired: dict[tuple[int, int], bool],
    flag: str | None = None,
) -> TableResult:
    """Make the link rows inside `scope` equal `desired` ({(key1, key2): flag value}).

    Order matters for a partial unique index on the flag (one primary group per
    exercise): stale rows are deleted and flags cleared before any is set.
    """
    result = TableResult(table.name)
    first, second = table.c[keys[0]], table.c[keys[1]]
    scope_column, scope_ids = table.c[scope[0]], scope[1]
    pair = tuple_(first, second)
    current: dict[tuple[int, int], bool] = {}
    if scope_ids:
        columns = [first, second, table.c[flag]] if flag else [first, second]
        for row in conn.execute(select(*columns).where(scope_column.in_(scope_ids))):
            current[(row[0], row[1])] = row[2] if flag else True

    stale = [k for k in current if k not in desired]
    changed = {k: v for k, v in desired.items() if k in current and current[k] != v}
    new = {k: v for k, v in desired.items() if k not in current}
    try:
        if stale:
            conn.execute(delete(table).where(pair.in_(stale)))
        if flag:
            for value in (False, True):
                targets = [k for k, v in changed.items() if v is value]
                if targets:
                    conn.execute(update(table).where(pair.in_(targets)).values({flag: value}))
        if new:
            conn.execute(
                insert(table).values(
                    [
                        {keys[0]: k[0], keys[1]: k[1], **({flag: v} if flag else {})}
                        for k, v in new.items()
                    ]
                )
            )
    except DBAPIError as error:
        raise SeedError(f"{table.name}: {error.orig}".strip()) from None
    result.inserted = len(new)
    result.updated = len(changed)
    result.deleted = len(stale)
    result.unchanged = len(desired) - len(new) - len(changed)
    return result


def split_names(raw: str) -> list[str]:
    return [name.strip() for name in raw.split(";") if name.strip()]


def load_exercises(conn: Connection, seed_dir: Path) -> list[TableResult]:
    """exercise.csv with its muscle groups, then injury_type_excluded_exercise.csv."""
    path = seed_file(seed_dir, EXERCISE.name)
    required = [col.name for col in EXERCISE.c if col.name != "id"] + list(GROUP_COLUMNS)
    rows = read_rows(path, EXERCISE, "name", extra=GROUP_COLUMNS, required=required)

    group_ids = name_ids(conn, MuscleGroup.__table__.c.group_name)
    groups_by_exercise: dict[str, dict[int, bool]] = {}
    for row in rows:
        name = row["name"]
        empty = [col for col, value in row.items() if value in (None, "")]
        empty = [col for col in empty if col != "secondary_groups"]
        if empty:
            raise SeedError(f"{path.name}: {name!r}: empty {empty}")
        primary = row.pop("primary_group").strip()
        secondary = split_names(row.pop("secondary_groups"))
        unknown = [g for g in [primary, *secondary] if g not in group_ids]
        if unknown:
            raise SeedError(f"{path.name}: {name!r}: unknown muscle groups {unknown}")
        if primary in secondary or len(set(secondary)) != len(secondary):
            raise SeedError(f"{path.name}: {name!r}: a muscle group is listed twice")
        groups_by_exercise[name] = {
            group_ids[primary]: True,
            **{group_ids[g]: False for g in secondary},
        }

    exercises = upsert(conn, EXERCISE, "name", rows)
    exercise_ids = {
        n: i for n, i in name_ids(conn, EXERCISE.c.name).items() if n in groups_by_exercise
    }
    seeded = set(exercise_ids.values())
    links = sync_links(
        conn,
        EXERCISE_GROUP,
        ("exercise_id", "muscle_group_id"),
        ("exercise_id", seeded),
        {
            (exercise_ids[name], group): primary
            for name, groups in groups_by_exercise.items()
            for group, primary in groups.items()
        },
        flag="is_primary",
    )
    exclusions = load_exclusions(conn, seed_dir, exercise_ids)
    return [exercises, links, exclusions]


def load_exclusions(conn: Connection, seed_dir: Path, exercise_ids: dict[str, int]) -> TableResult:
    path = seed_file(seed_dir, EXCLUSION.name)
    type_ids = name_ids(conn, InjuryType.__table__.c.type_name)
    desired: dict[tuple[int, int], bool] = {}
    with path.open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != EXCLUSION_HEADER:
            raise SeedError(f"{path.name}: header must be {','.join(EXCLUSION_HEADER)}")
        for line, record in enumerate(reader, start=2):
            if None in record or None in record.values():
                raise SeedError(f"{path.name}:{line}: wrong number of fields")
            injury_type, exercise = record["injury_type"], record["exercise"]
            if injury_type not in type_ids:
                raise SeedError(f"{path.name}:{line}: unknown injury type {injury_type!r}")
            if exercise not in exercise_ids:
                raise SeedError(f"{path.name}:{line}: exercise {exercise!r} not in exercise.csv")
            key = (type_ids[injury_type], exercise_ids[exercise])
            if key in desired:
                raise SeedError(f"{path.name}:{line}: duplicate {injury_type!r}, {exercise!r}")
            desired[key] = True
    return sync_links(
        conn,
        EXCLUSION,
        ("injury_type_id", "exercise_id"),
        ("exercise_id", set(exercise_ids.values())),
        desired,
    )


def link_ids(where: str, raw: str, ids: dict[str, int], what: str, required: bool) -> list[int]:
    names = split_names(raw)
    if required and not names:
        raise SeedError(f"{where}: no {what}")
    unknown = [n for n in names if n not in ids]
    if unknown:
        raise SeedError(f"{where}: unknown {what} {unknown}")
    if len(set(names)) != len(names):
        raise SeedError(f"{where}: one of the {what} is listed twice")
    return [ids[n] for n in names]


def load_foods(conn: Connection, seed_dir: Path) -> list[TableResult]:
    """food_item.csv with its categories and allergens."""
    path = seed_file(seed_dir, FOOD.name)
    required = [col.name for col in FOOD.c if col.name not in FOOD_NOT_IN_FILE]
    rows = read_rows(path, FOOD, "name", extra=FOOD_EXTRA, required=[*required, *FOOD_EXTRA])

    category_ids = name_ids(conn, FoodCategory.__table__.c.category_name)
    allergen_ids = name_ids(conn, Allergen.__table__.c.name)
    categories: dict[str, list[int]] = {}
    allergens: dict[str, list[int]] = {}
    for row in rows:
        name = row["name"]
        where = f"{path.name}: {name!r}"
        empty = [col for col, value in row.items() if value in (None, "")]
        empty = [col for col in empty if col != "allergens"]
        if empty:
            raise SeedError(f"{where}: empty {empty}")
        source = row.pop("source").strip()
        if not FOOD_SOURCE.fullmatch(source):
            raise SeedError(f"{where}: source {source!r} is not FDC:<id> or SLV:<number>")
        categories[name] = link_ids(where, row.pop("categories"), category_ids, "categories", True)
        allergens[name] = link_ids(where, row.pop("allergens"), allergen_ids, "allergens", False)

    foods = upsert(conn, FOOD, "name", rows)
    food_ids = {n: i for n, i in name_ids(conn, FOOD.c.name).items() if n in categories}
    seeded = ("food_item_id", set(food_ids.values()))
    return [
        foods,
        sync_links(
            conn,
            FOOD_CATEGORY,
            ("food_item_id", "food_category_id"),
            seeded,
            {(food_ids[n], c): True for n, ids in categories.items() for c in ids},
        ),
        sync_links(
            conn,
            FOOD_ALLERGEN,
            ("food_item_id", "allergen_id"),
            seeded,
            {(food_ids[n], a): True for n, ids in allergens.items() for a in ids},
        ),
    ]


def load(conn: Connection, seed_dir: Path = SEED_DIR) -> list[TableResult]:
    """Load every seed file inside the caller's transaction."""
    results = []
    for table, key in SEEDS:
        path = seed_file(seed_dir, table.name)
        results.append(upsert(conn, table, key, read_rows(path, table, key)))
    results.extend(load_exercises(conn, seed_dir))
    results.extend(load_foods(conn, seed_dir))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load the reference seeds.")
    parser.add_argument("--dir", type=Path, default=SEED_DIR, help="seed folder")
    args = parser.parse_args(argv)

    engine = create_sync_engine()
    try:
        with engine.begin() as conn:
            results = load(conn, args.dir)
    except SeedError as error:
        print(f"seed error: {error}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    for r in results:
        print(
            f"{r.table:<30} inserted {r.inserted:>3}  updated {r.updated:>3}  "
            f"deleted {r.deleted:>3}  unchanged {r.unchanged:>3}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
