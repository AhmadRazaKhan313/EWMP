"""
Regression test for audit finding C-8: `alembic upgrade head` failed on a
brand-new, empty database.

Two sibling revisions branch from a1b2c3d4e5f6 and both add
attendance_punches.deleted_at / attendance_regularizations.deleted_at:
c4d8f1a6b3e7 (with IF NOT EXISTS) and b7d4f1a92c63 (used to be a plain
op.add_column). Existing databases had been migrated step by step and never
hit it, but every fresh install stopped with DuplicateColumnError halfway
through the chain.

This test creates a throwaway database, runs the real Alembic CLI against it
(`upgrade head`), checks the columns exist, then walks both sibling branches
down and back up. It needs a live Postgres whose user may CREATE DATABASE —
same TEST_DATABASE_URL convention as the other *_postgres tests here; it is
skipped (not failed) if the role lacks that privilege.
"""

import os
import subprocess
import sys
import uuid

import asyncpg
import pytest
import pytest_asyncio

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp"
)
PLAIN_URL = TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


def _url_for_database(name: str) -> str:
    base, _, _ = PLAIN_URL.rpartition("/")
    return f"{base}/{name}"


def _alembic(database_url: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": database_url}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


@pytest_asyncio.fixture
async def fresh_database():
    name = f"ewmp_migtest_{uuid.uuid4().hex[:10]}"
    admin = await asyncpg.connect(PLAIN_URL)
    try:
        try:
            await admin.execute(f'CREATE DATABASE "{name}"')
        except asyncpg.InsufficientPrivilegeError:
            pytest.skip("TEST_DATABASE_URL role cannot CREATE DATABASE")
        yield _url_for_database(name)
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()


async def _columns(database_url: str, table: str) -> set[str]:
    conn = await asyncpg.connect(database_url)
    try:
        rows = await conn.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name = $1",
            table,
        )
        return {r["column_name"] for r in rows}
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_fresh_database_upgrades_to_head(fresh_database):
    result = _alembic(fresh_database, "upgrade", "head")
    assert result.returncode == 0, result.stderr[-3000:]

    for table in ("attendance_punches", "attendance_regularizations"):
        assert "deleted_at" in await _columns(fresh_database, table)


@pytest.mark.asyncio
async def test_sibling_branches_round_trip(fresh_database):
    """Down to the common parent and back up: both sibling revisions must
    tolerate the other one having already added / dropped the column."""
    assert _alembic(fresh_database, "upgrade", "head").returncode == 0

    down = _alembic(fresh_database, "downgrade", "a1b2c3d4e5f6")
    assert down.returncode == 0, down.stderr[-3000:]

    up = _alembic(fresh_database, "upgrade", "head")
    assert up.returncode == 0, up.stderr[-3000:]
    assert "deleted_at" in await _columns(fresh_database, "attendance_punches")
