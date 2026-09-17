"""
Tests for app/workers/tasks/attendance.py — the midnight auto-checkout /
stale-break closeout sweep.

Same no-DB fake-session technique as the rest of this suite
(test_leave_completion.py, test_notifications.py), adapted for a task
that opens its own AsyncSessionLocal() rather than receiving `db` via
FastAPI's Depends.

Run:  cd backend && pytest tests/test_attendance_auto_checkout.py -v
"""
import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import app.workers.tasks.attendance as attendance_mod
from app.models.work_session import WorkSessionStatus

TENANT = uuid.uuid4()
EMP_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


class _FakeExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    def __init__(self, rows_queue):
        self._queue = list(rows_queue)
        self.committed = False

    async def execute(self, stmt):
        return self._queue.pop(0)

    async def commit(self):
        self.committed = True


class _FakeSessionCtx:
    """Fakes `async with AsyncSessionLocal() as db:`."""

    def __init__(self, db):
        self._db = db

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *exc):
        return False


def _run(coro):
    return asyncio.run(coro)


def _session(started_at, status=WorkSessionStatus.ACTIVE, breaks=None):
    return SimpleNamespace(
        id=uuid.uuid4(), tenant_id=TENANT, employee_id=EMP_ID,
        started_at=started_at, ended_at=None, status=status,
        total_minutes=None, breaks=breaks or [],
    )


def _break(started_at, ended_at=None):
    return SimpleNamespace(id=uuid.uuid4(), started_at=started_at, ended_at=ended_at)


class TestOrgTimezoneFallback:
    def test_valid_timezone_resolves(self):
        tz = attendance_mod._org_timezone("Asia/Karachi")
        assert str(tz) == "Asia/Karachi"

    def test_unknown_timezone_falls_back_to_utc_without_raising(self):
        tz = attendance_mod._org_timezone("Not/A_Real_Zone")
        assert str(tz) == "UTC"


class TestCloseStaleWorkSessions:
    def test_a_session_still_within_todays_local_date_is_left_running(self, monkeypatch):
        # Started 2 hours ago, same local calendar day — must NOT be touched.
        s = _session(started_at=datetime.now(UTC) - timedelta(hours=2))
        db = _FakeDB([_FakeExecuteResult([(s, "UTC")])])
        monkeypatch.setattr(attendance_mod, "AsyncSessionLocal", _FakeSessionCtx(db))

        count = _run(attendance_mod._close_stale_work_sessions())

        assert count == 0
        assert s.status == WorkSessionStatus.ACTIVE
        assert s.ended_at is None

    def test_a_session_from_a_previous_local_day_is_closed_at_that_days_midnight(self, monkeypatch):
        tz = ZoneInfo("UTC")
        # Started yesterday at 9am UTC, still open (forgot to check out).
        yesterday_9am = datetime.now(UTC).replace(hour=9, minute=0, second=0, microsecond=0) - timedelta(days=1)
        s = _session(started_at=yesterday_9am)
        db = _FakeDB([_FakeExecuteResult([(s, "UTC")])])
        monkeypatch.setattr(attendance_mod, "AsyncSessionLocal", _FakeSessionCtx(db))
        monkeypatch.setattr(attendance_mod, "_notify_auto_checkout", lambda *a, **kw: _noop())

        count = _run(attendance_mod._close_stale_work_sessions())

        assert count == 1
        assert s.status == WorkSessionStatus.ENDED
        # Closed at 23:59:59 of the day it STARTED, not "now".
        assert s.ended_at.astimezone(tz).date() == yesterday_9am.date()
        assert s.ended_at.astimezone(tz).hour == 23
        # 9am -> 23:59:59 = 14h59m59s worked, no breaks.
        assert s.total_minutes in (899, 900)
        assert db.committed

    def test_an_open_break_is_also_closed_at_the_same_midnight_boundary(self, monkeypatch):
        yesterday_9am = datetime.now(UTC).replace(hour=9, minute=0, second=0, microsecond=0) - timedelta(days=1)
        yesterday_1pm = yesterday_9am.replace(hour=13)
        open_break = _break(started_at=yesterday_1pm, ended_at=None)
        s = _session(started_at=yesterday_9am, status=WorkSessionStatus.ON_BREAK, breaks=[open_break])
        db = _FakeDB([_FakeExecuteResult([(s, "UTC")])])
        monkeypatch.setattr(attendance_mod, "AsyncSessionLocal", _FakeSessionCtx(db))
        monkeypatch.setattr(attendance_mod, "_notify_auto_checkout", lambda *a, **kw: _noop())

        _run(attendance_mod._close_stale_work_sessions())

        assert open_break.ended_at is not None
        assert open_break.ended_at == s.ended_at  # break closed at the SAME cutoff as the session
        # 9am->23:59:59 = ~15h elapsed, minus the break (13:00->23:59:59 = ~11h) = ~4h worked.
        assert 230 <= s.total_minutes <= 250

    def test_a_forgotten_break_that_spans_multiple_days_only_counts_that_days_hours(self, monkeypatch):
        # Laptop left on break over a long weekend — session started 3
        # days ago. Must still close at THAT day's midnight, not today's.
        three_days_ago_9am = (
            datetime.now(UTC).replace(hour=9, minute=0, second=0, microsecond=0) - timedelta(days=3)
        )
        s = _session(started_at=three_days_ago_9am)
        db = _FakeDB([_FakeExecuteResult([(s, "UTC")])])
        monkeypatch.setattr(attendance_mod, "AsyncSessionLocal", _FakeSessionCtx(db))
        monkeypatch.setattr(attendance_mod, "_notify_auto_checkout", lambda *a, **kw: _noop())

        _run(attendance_mod._close_stale_work_sessions())

        assert s.ended_at.date() == three_days_ago_9am.date()
        assert s.total_minutes in (899, 900)  # still just ~15h, not 3 days' worth

    def test_unknown_org_timezone_does_not_crash_the_whole_sweep(self, monkeypatch):
        yesterday_9am = datetime.now(UTC).replace(hour=9, minute=0, second=0, microsecond=0) - timedelta(days=1)
        s = _session(started_at=yesterday_9am)
        db = _FakeDB([_FakeExecuteResult([(s, "Not/Real")])])
        monkeypatch.setattr(attendance_mod, "AsyncSessionLocal", _FakeSessionCtx(db))
        monkeypatch.setattr(attendance_mod, "_notify_auto_checkout", lambda *a, **kw: _noop())

        count = _run(attendance_mod._close_stale_work_sessions())

        assert count == 1  # falls back to UTC and still closes it, doesn't raise

    def test_multiple_tenants_in_one_sweep_are_each_handled_independently(self, monkeypatch):
        yesterday_9am = datetime.now(UTC).replace(hour=9, minute=0, second=0, microsecond=0) - timedelta(days=1)
        today_9am = datetime.now(UTC).replace(hour=9, minute=0, second=0, microsecond=0)
        stale = _session(started_at=yesterday_9am)
        fresh = _session(started_at=today_9am if datetime.now(UTC).hour > 9 else datetime.now(UTC) - timedelta(minutes=5))
        db = _FakeDB([_FakeExecuteResult([(stale, "UTC"), (fresh, "UTC")])])
        monkeypatch.setattr(attendance_mod, "AsyncSessionLocal", _FakeSessionCtx(db))
        monkeypatch.setattr(attendance_mod, "_notify_auto_checkout", lambda *a, **kw: _noop())

        count = _run(attendance_mod._close_stale_work_sessions())

        assert count == 1
        assert stale.status == WorkSessionStatus.ENDED
        assert fresh.status == WorkSessionStatus.ACTIVE


async def _noop(*args, **kwargs):
    return None
