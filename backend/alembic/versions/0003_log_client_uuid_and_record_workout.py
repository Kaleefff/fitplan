"""client_uuid unique per user on the log tables; personal_record.workout_log_id

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-03 18:00:00

UNIQUE (client_uuid) becomes UNIQUE (user_id, client_uuid) on workout_log,
nutrition_log and body_metrics: a create that repeats another user's client_uuid is
stored for its own user. The downgrade refuses while two rows of a table share a
client_uuid, since the old constraint could not be restored.

personal_record.workout_log_id names the workout that set the record (nullable, ON
DELETE SET NULL, indexed). Records stored before it are linked through their
achievement notification, until now the only place that named the workout.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOG_TABLES = ("workout_log", "nutrition_log", "body_metrics")

REFUSE_IF_SHARED = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM {table} GROUP BY client_uuid HAVING count(*) > 1) THEN
        RAISE EXCEPTION '{table}: two users share a client_uuid; give them new ones first';
    END IF;
END
$$
"""

LINK_RECORDS_TO_WORKOUTS = """
UPDATE personal_record AS r
SET workout_log_id = w.id
FROM notification AS n
JOIN workout_log AS w ON w.id = (n.data ->> 'workout_log_id')::int
WHERE n.message_type = 'achievement'
  AND (n.data ->> 'personal_record_id')::int = r.id
  AND w.user_id = r.user_id
"""


def upgrade() -> None:
    for table in LOG_TABLES:
        op.drop_constraint(op.f(f"{table}_client_uuid_key"), table, type_="unique")
        op.create_unique_constraint(
            op.f(f"{table}_user_id_client_uuid_key"), table, ["user_id", "client_uuid"]
        )
    op.add_column("personal_record", sa.Column("workout_log_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("personal_record_workout_log_id_fkey"),
        "personal_record",
        "workout_log",
        ["workout_log_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_personal_record_workout_log_id"), "personal_record", ["workout_log_id"]
    )
    op.execute(LINK_RECORDS_TO_WORKOUTS)


def downgrade() -> None:
    for table in LOG_TABLES:
        op.execute(REFUSE_IF_SHARED.format(table=table))
    op.drop_index(op.f("ix_personal_record_workout_log_id"), table_name="personal_record")
    op.drop_constraint(
        op.f("personal_record_workout_log_id_fkey"), "personal_record", type_="foreignkey"
    )
    op.drop_column("personal_record", "workout_log_id")
    for table in LOG_TABLES:
        op.drop_constraint(op.f(f"{table}_user_id_client_uuid_key"), table, type_="unique")
        op.create_unique_constraint(op.f(f"{table}_client_uuid_key"), table, ["client_uuid"])
