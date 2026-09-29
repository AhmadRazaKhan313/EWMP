"""
Regression tests for audit finding C-2: the Celery worker could not boot,
and once booted, every second run of a task crashed.

1. `celery_app.include` listed two modules that don't exist
   (app.workers.tasks.payroll / .reports). The worker imports every include
   at boot, so it died with ModuleNotFoundError and NO background job ran —
   no emails, no device-offline sweep, no overnight session close.

2. Tasks call asyncio.run() (a fresh event loop per run) but used the
   module-level pooled async engine. Pooled asyncpg connections stay bound
   to the first loop, so the next run in the same worker process failed.
   Tasks now use app.core.database.worker_db_session (NullPool, per-loop).

Tests 1–2 need no database. Test 3 needs a live Postgres with migrations
applied — same convention as the other *_postgres tests in this folder
(TEST_DATABASE_URL, errors on connection if Postgres isn't running).
"""

import asyncio
import os

import pytest

from app.workers.celery_app import celery_app


def test_every_include_module_imports():
    """The worker boot step: importing every `include` must succeed."""
    celery_app.loader.import_default_modules()


def test_every_beat_schedule_entry_points_at_a_registered_task():
    celery_app.loader.import_default_modules()
    registered = set(celery_app.tasks.keys())
    for entry_name, entry in celery_app.conf.beat_schedule.items():
        assert entry["task"] in registered, (
            f"beat entry {entry_name!r} schedules unknown task {entry['task']!r}"
        )


def test_tasks_survive_repeated_asyncio_run_in_one_process(monkeypatch):
    """Simulates one worker process running each periodic task several
    times in a row — each call is its own asyncio.run(), exactly like
    Celery's prefork pool. Before the fix the 2nd call raised."""
    database_url = os.environ.get(
        "TEST_DATABASE_URL", "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp"
    )
    import app.core.database as database

    # Point the worker session helper at the test database without
    # touching the app-wide settings object.
    monkeypatch.setattr(database, "_async_db_url", database_url)

    from app.workers.tasks.device_health import mark_stale_devices_offline
    from app.workers.tasks.work_sessions import auto_close_overnight_sessions

    for _ in range(3):
        assert isinstance(mark_stale_devices_offline(), int)
        assert isinstance(auto_close_overnight_sessions(), int)

    # And the helper itself, directly, across fresh loops.
    from sqlalchemy import text

    async def _ping() -> int:
        async with database.worker_db_session() as db:
            return (await db.execute(text("SELECT 1"))).scalar_one()

    assert [asyncio.run(_ping()) for _ in range(3)] == [1, 1, 1]
