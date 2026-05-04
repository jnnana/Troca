"""Test fixtures for the Zocux protocol server.

Tests are integration tests against a real PostgreSQL and Redis. Configure them
via env vars before running pytest:

    ZOCUX_TEST_DATABASE_URL=postgresql://zocux:zocux_password@localhost:5432/zocux_test
    ZOCUX_TEST_REDIS_URL=redis://localhost:6379/15

If those vars are not set the suite falls back to DATABASE_URL/REDIS_URL.
The schema is reapplied (idempotent) and the data tables are truncated before
each test, so never point these vars at a production database.
"""

from __future__ import annotations

import os
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
import redis.asyncio as aioredis

# Resolve test connection strings BEFORE importing the server module —
# DATABASE_URL / REDIS_URL are read at module-import time.
TEST_DB_URL = os.environ.get(
    "ZOCUX_TEST_DATABASE_URL",
    os.environ.get("DATABASE_URL", "postgresql://zocux:zocux_password@localhost:5432/zocux_test"),
)
TEST_REDIS_URL = os.environ.get(
    "ZOCUX_TEST_REDIS_URL",
    os.environ.get("REDIS_URL", "redis://localhost:6379/15"),
)
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["REDIS_URL"] = TEST_REDIS_URL

from server import zocux_server as z  # noqa: E402

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


async def _apply_schema_and_truncate():
    conn = await asyncpg.connect(TEST_DB_URL)
    try:
        await conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
        await conn.execute("TRUNCATE protocol_messages, closed_deals RESTART IDENTITY")
    finally:
        await conn.close()


async def _flush_redis():
    r = aioredis.from_url(TEST_REDIS_URL)
    try:
        await r.flushdb()
    finally:
        await r.aclose()


# Opt-in fixture: integration test modules pull it in via
#   pytestmark = pytest.mark.usefixtures("clean_state")
# Pure unit modules (e.g. test_matching.py) skip it and never hit Postgres/Redis.
@pytest_asyncio.fixture
async def clean_state():
    try:
        await _apply_schema_and_truncate()
        await _flush_redis()
    except Exception as exc:
        pytest.skip(f"Test services unavailable: {exc}", allow_module_level=False)
    z.db_pool = None
    z.redis_client = None
    yield
    if z.db_pool is not None:
        await z.db_pool.close()
        z.db_pool = None
    if z.redis_client is not None:
        await z.redis_client.aclose()
        z.redis_client = None
