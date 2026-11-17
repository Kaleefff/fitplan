"""Shared helpers for the database tests.

`delete_users` removes every test user from PostgreSQL (see the comment on it).

`buffer_db` is a throwaway database (fitplan_buffer_test) whose `meal_recognitions`
collection is dropped around every test (DB-07); skipped when MongoDB is not reachable,
like the PostgreSQL tests. Not autouse: tests without MongoDB do not touch it.
"""

from collections.abc import AsyncIterator

import pytest
from pymongo import AsyncMongoClient, MongoClient
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import PyMongoError
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import get_settings
from app.db.repositories.meal_recognitions import COLLECTION

MONGO_TEST_DB = "fitplan_buffer_test"
SERVER_SELECTION_MS = 1000

# Remove users with DELETE, never with TRUNCATE app_user ... CASCADE. TRUNCATE CASCADE
# empties every table with a foreign key to app_user, whatever its rows hold, and since
# migration 0004 that includes exercise (custom exercises, D26): it would wipe the seeded
# exercise library and its links too. DELETE applies the ON DELETE rules row by row, so
# only what users own goes (their custom exercises included), and the deferred exercise
# foreign keys are checked at commit, as for a real account deletion. The id sequence
# restarts as TRUNCATE ... RESTART IDENTITY did: tests rely on the first user being 1.
DELETE_USERS = text("DELETE FROM app_user")
RESTART_USER_IDS = text("ALTER TABLE app_user ALTER COLUMN id RESTART")


def delete_users(connection: Connection) -> None:
    connection.execute(DELETE_USERS)
    connection.execute(RESTART_USER_IDS)


async def delete_users_async(connection: AsyncConnection) -> None:
    await connection.execute(DELETE_USERS)
    await connection.execute(RESTART_USER_IDS)


@pytest.fixture(scope="module")
def mongo_reachable() -> None:
    client = MongoClient(
        **get_settings().mongo_client_kwargs(), serverSelectionTimeoutMS=SERVER_SELECTION_MS
    )
    try:
        client.admin.command("ping")
    except PyMongoError:
        pytest.skip("MongoDB is not reachable: run docker compose up -d")
    finally:
        client.close()


@pytest.fixture
async def buffer_db(mongo_reachable) -> AsyncIterator[AsyncDatabase]:
    client = AsyncMongoClient(
        **get_settings().mongo_client_kwargs(), serverSelectionTimeoutMS=SERVER_SELECTION_MS
    )
    db = client[MONGO_TEST_DB]
    await db.drop_collection(COLLECTION)
    yield db
    await db.drop_collection(COLLECTION)
    await client.close()
