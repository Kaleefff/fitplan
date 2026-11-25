"""(user_id, updated_at, id) on the synced log tables: sync pull by cursor (DB-13, NFR-OFF)

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-25 12:00:00

GET /sync/pull reads one user's changes in (updated_at, kind, id) order after a cursor
(api-rules.md Sync); each table's branch of that query is a range scan of this index:
user_id equal, (updated_at, id) after the cursor, already in order. Not partial: deleted
rows are pulled too, as tombstones.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SYNCED_TABLES = ("workout_log", "nutrition_log", "body_metrics")


def upgrade() -> None:
    for table in SYNCED_TABLES:
        op.create_index(f"ix_{table}_user_updated", table, ["user_id", "updated_at", "id"])


def downgrade() -> None:
    for table in SYNCED_TABLES:
        op.drop_index(f"ix_{table}_user_updated", table_name=table)
