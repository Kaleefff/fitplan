"""MongoDB fixtures shared by the buffer tests (DB-07).

`buffer_db` is a throwaway database (fitplan_buffer_test) whose `meal_recognitions`
collection is dropped around every test; skipped when MongoDB is not reachable, like
the PostgreSQL tests. Not autouse: tests without MongoDB do not touch it.
"""

from collections.abc import AsyncIterator

import pytest
from pymongo import AsyncMongoClient, MongoClient
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import PyMongoError

from app.core.config import get_settings
from app.db.repositories.meal_recognitions import COLLECTION

MONGO_TEST_DB = "fitplan_buffer_test"
SERVER_SELECTION_MS = 1000


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
