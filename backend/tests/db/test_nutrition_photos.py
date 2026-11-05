"""`SqlConfirmedPhotoPaths` on a real PostgreSQL (DB-07, FR-N4); skipped without it."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.db.enums import MealType
from app.db.models import NutritionLog
from app.db.repositories.nutrition_photos import SqlConfirmedPhotoPaths
from app.db.repositories.users import SqlUserRepository
from tests.db.test_repositories import (  # noqa: F401  (fixtures)
    anyio_backend,
    migrated_db,
    sessions,
)

pytestmark = pytest.mark.anyio


def log(user_id: int, photo_url: str | None, deleted: bool = False) -> NutritionLog:
    return NutritionLog(
        user_id=user_id,
        log_date=date(2026, 11, 3),
        meal_type=MealType.LUNCH,
        meal_photo_url=photo_url,
        actual_cals=Decimal("500"),
        actual_protein=Decimal("20"),
        actual_fat=Decimal("15"),
        actual_carbs=Decimal("60"),
        deleted_at=datetime.now(UTC) if deleted else None,
    )


async def test_confirmed_photo_paths_lists_distinct_non_null_urls(sessions):  # noqa: F811
    users = SqlUserRepository(sessions)
    ann = (await users.add(email="ann@example.com", password_hash="h", name="A", surname="B")).id
    bob = (await users.add(email="bob@example.com", password_hash="h", name="B", surname="C")).id
    paths = SqlConfirmedPhotoPaths(sessions)
    assert await paths() == set()

    async with sessions.begin() as session:
        session.add_all(
            [
                log(ann, f"meals/{ann}/a.jpg"),
                log(ann, f"meals/{ann}/a.jpg"),  # the same photo twice
                log(ann, f"meals/{ann}/deleted.jpg", deleted=True),  # soft delete keeps it
                log(ann, None),  # logged by hand
                log(bob, f"meals/{bob}/b.png"),
            ]
        )

    assert await paths() == {f"meals/{ann}/a.jpg", f"meals/{ann}/deleted.jpg", f"meals/{bob}/b.png"}
