"""diet_role 'other': foods that can be logged and added by hand but are never planned

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-01 17:00:00

PostgreSQL cannot drop an enum value, so the downgrade rebuilds the type. It refuses
while a food_item still uses 'other': deleting those rows would break nutrition logs
and meals that reference them.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLES_0001 = ("protein", "carb", "vegetable", "fruit", "dairy", "fat", "dish")

REFUSE_IF_USED = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM food_item WHERE diet_role::text = 'other') THEN
        RAISE EXCEPTION 'food_item rows use diet_role ''other''; give them another role first';
    END IF;
END
$$
"""


def upgrade() -> None:
    op.execute("ALTER TYPE diet_role ADD VALUE IF NOT EXISTS 'other'")


def downgrade() -> None:
    op.execute(REFUSE_IF_USED)
    values = ", ".join(f"'{role}'" for role in ROLES_0001)
    op.execute("ALTER TYPE diet_role RENAME TO diet_role_0002")
    op.execute(f"CREATE TYPE diet_role AS ENUM ({values})")
    op.execute(
        "ALTER TABLE food_item ALTER COLUMN diet_role TYPE diet_role "
        "USING diet_role::text::diet_role"
    )
    op.execute("DROP TYPE diet_role_0002")
