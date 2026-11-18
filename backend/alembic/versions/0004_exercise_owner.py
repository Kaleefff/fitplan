"""exercise.user_id: custom exercises owned by a user (DB-16, FR-P10, D26)

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-15 12:00:00

exercise.user_id is NULL for a library exercise (seeded) and the owner's id for a
custom one (FK to app_user, ON DELETE CASCADE). UNIQUE (name) becomes two partial
unique indexes: library names stay unique exactly as before; custom names are unique
per user, case-insensitively, and may repeat a library name or another user's custom
name (questions.md [DB-16] custom-exercise-name). The custom-name index also serves
`WHERE user_id = ?`, including the cascade from app_user, so user_id has no index of
its own. The one-primary-group index on exercise_muscle_group covers custom exercises
unchanged.

The four NO ACTION foreign keys that reference exercise become DEFERRABLE INITIALLY
DEFERRED (D26). PostgreSQL runs cascades level by level, so with immediate checks
`DELETE FROM app_user` failed on session_exercise (three levels down) while the
cascade to exercise (one level down) had already queued its check. Deferred, they are
checked at commit, after every cascade. Deleting a custom exercise sets them IMMEDIATE.

The downgrade refuses while a custom exercise exists: dropping the column would turn
it into a library exercise that every user sees.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# NO ACTION foreign keys to exercise.id, as (table, constraint name)
EXERCISE_REFERENCES = (
    ("session_exercise", "session_exercise_exercise_id_fkey"),
    ("session_exercise", "session_exercise_original_exercise_id_fkey"),
    ("workout_log_exercise", "workout_log_exercise_exercise_id_fkey"),
    ("personal_record", "personal_record_exercise_id_fkey"),
)

REFUSE_IF_CUSTOM = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM exercise WHERE user_id IS NOT NULL) THEN
        RAISE EXCEPTION 'exercise: custom exercises exist; delete them first';
    END IF;
END
$$
"""


def upgrade() -> None:
    op.add_column("exercise", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("exercise_user_id_fkey"),
        "exercise",
        "app_user",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # a custom name may equal a library name, so the table-wide UNIQUE (name) goes
    op.drop_constraint(op.f("exercise_name_key"), "exercise", type_="unique")
    op.create_index(
        "ux_exercise_library_name",
        "exercise",
        ["name"],
        unique=True,
        postgresql_where=sa.text("user_id IS NULL"),
    )
    op.create_index(
        "ux_exercise_custom_name",
        "exercise",
        ["user_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    for table, constraint in EXERCISE_REFERENCES:
        op.execute(
            f"ALTER TABLE {table} ALTER CONSTRAINT {constraint} DEFERRABLE INITIALLY DEFERRED"
        )


def downgrade() -> None:
    op.execute(REFUSE_IF_CUSTOM)
    for table, constraint in EXERCISE_REFERENCES:
        op.execute(f"ALTER TABLE {table} ALTER CONSTRAINT {constraint} NOT DEFERRABLE")
    op.drop_index("ux_exercise_custom_name", table_name="exercise")
    op.drop_index("ux_exercise_library_name", table_name="exercise")
    op.create_unique_constraint(op.f("exercise_name_key"), "exercise", ["name"])
    op.drop_constraint(op.f("exercise_user_id_fkey"), "exercise", type_="foreignkey")
    op.drop_column("exercise", "user_id")
