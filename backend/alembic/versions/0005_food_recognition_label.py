"""food_item.recognition_label = lower(name) for every food (A-01, D25)

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-19 12:00:00

Gemini picks every label from the active recognition labels that ai-service sends
(algorithms.md 11); matching compares lower(trim(label)) on both sides. A label is the
food's name lower-cased; the seed labels foods added later the same way (app/db/seed.py).

The upgrade stops, changing nothing, when a name is longer than recognition_label
(VARCHAR(100)) or two names are equal after lower() (the label is UNIQUE): both need
a rename first. The downgrade clears only labels still equal to lower(name), so a label
set by hand survives.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REFUSE_UNLABELLABLE = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM food_item WHERE char_length(lower(name)) > 100) THEN
        RAISE EXCEPTION 'food_item: a name is longer than 100 characters; shorten it first';
    END IF;
    IF EXISTS (SELECT 1 FROM food_item GROUP BY lower(name) HAVING count(*) > 1) THEN
        RAISE EXCEPTION 'food_item: names equal after lower(); rename one first';
    END IF;
END
$$
"""


def upgrade() -> None:
    op.execute(REFUSE_UNLABELLABLE)
    op.execute("UPDATE food_item SET recognition_label = lower(name)")


def downgrade() -> None:
    op.execute(
        "UPDATE food_item SET recognition_label = NULL WHERE recognition_label = lower(name)"
    )
