"""app_user: unique index on lower(email), one account per mailbox (DB-15, FR-U1)

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-20 12:00:00

The API lowercases the whole email on register, login and email change (api-rules.md
Auth and account); this index makes the database refuse a second account whose email
differs from an existing one only in case, whatever the caller sends.

The upgrade stops, changing nothing, when two existing emails are equal after lower():
one of the accounts has to be changed or removed by hand first. app_user_email_key
(exact-match UNIQUE from the baseline) stays; the repository maps both to EmailTakenError.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ux_app_user_email_lower"

REFUSE_CASE_DUPLICATES = """
DO $$
DECLARE
    duplicates integer;
BEGIN
    SELECT count(*) INTO duplicates
    FROM (SELECT 1 FROM app_user GROUP BY lower(email) HAVING count(*) > 1) AS d;
    IF duplicates > 0 THEN
        RAISE EXCEPTION 'app_user: % email(s) shared by several accounts after lower(); '
            'merge or rename them first (SELECT lower(email), array_agg(id) FROM app_user '
            'GROUP BY 1 HAVING count(*) > 1)', duplicates;
    END IF;
END
$$
"""


def upgrade() -> None:
    op.execute(REFUSE_CASE_DUPLICATES)
    op.execute(f"CREATE UNIQUE INDEX {INDEX} ON app_user (lower(email))")


def downgrade() -> None:
    op.execute(f"DROP INDEX {INDEX}")
