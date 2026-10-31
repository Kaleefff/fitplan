"""Reference seed loader (DB-02).

Loads the CSV files of database/seed/ into PostgreSQL. Each file is named after its
table and its header row uses the table's column names. The natural key (the name
column) identifies a row, so the loader is idempotent: new names are inserted,
changed rows are updated, identical rows are left alone. Rows that are no longer
in a file are kept, because user data may reference them.

Run from backend/:  uv run python -m app.db.seed  [--dir PATH]
"""

import argparse
import csv
import enum
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Table, literal_column, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError

from app.db.models import Allergen, FoodCategory, InjuryType, MuscleGroup
from app.db.session import create_sync_engine

SEED_DIR = Path(__file__).resolve().parents[3] / "database" / "seed"

SEEDS: list[tuple[Table, str]] = [
    (MuscleGroup.__table__, "group_name"),
    (InjuryType.__table__, "type_name"),
    (Allergen.__table__, "name"),
    (FoodCategory.__table__, "category_name"),
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
    unchanged: int = 0


def convert(table: Table, column: str, raw: str) -> Any:
    """CSV text to the column's Python type; an empty field is NULL."""
    if raw == "":
        return None
    python_type = table.c[column].type.python_type
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


def read_rows(path: Path, table: Table, key: str) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        header = reader.fieldnames or []
        unknown = [name for name in header if name not in table.c]
        if unknown:
            raise SeedError(f"{path.name}: unknown columns {unknown}")
        if key not in header:
            raise SeedError(f"{path.name}: key column {key!r} missing")
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
                rows.append({col: convert(table, col, raw) for col, raw in record.items()})
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


def load(conn: Connection, seed_dir: Path = SEED_DIR) -> list[TableResult]:
    """Load every seed file inside the caller's transaction."""
    results = []
    for table, key in SEEDS:
        path = seed_dir / f"{table.name}.csv"
        if not path.is_file():
            raise SeedError(f"missing seed file {path}")
        results.append(upsert(conn, table, key, read_rows(path, table, key)))
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
            f"{r.table:<15} inserted {r.inserted:>3}  updated {r.updated:>3}  "
            f"unchanged {r.unchanged:>3}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
