"""
Regression tests for two attendance Medium bugs:

1. `record_attendance` ("regularize"): accepted `check_in`/`check_out` time
   string parameters but never wrote them onto the created record — HR's
   entered times were silently dropped. It also always INSERTed a new row,
   even when one already existed for that employee+date, creating
   duplicate attendance records every time the same day was regularized
   more than once.

2. `check_out`: looked up today's attendance record via
   `AttendanceRecord.date == now.date()` computed AT CHECK-OUT TIME. For an
   overnight shift (check in 11pm, check out 1am the next day), "today" at
   check-out is a different calendar date than the check-in's record was
   filed under, so the record was never found and check-out failed
   outright with "No check-in found" — it didn't just compute wrong hours,
   it couldn't check out at all.

No database needed — same fake-DB-queue technique used throughout this
test suite (test_device_enrollment_c3.py, test_leave_completion.py, etc).

Run:  cd backend && pytest tests/test_attendance_regularize_overnight.py -v
"""
import asyncio
import uuid
from datetime import date as ddate
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.api.v1.hrms.attendance import CheckOutRequest, check_out, record_attendance
from app.core.exceptions import ValidationError
from app.models.attendance import AttendanceRecord, AttendanceSource, AttendanceStatus

TENANT = uuid.uuid4()
EMP_ID = uuid.uuid4()


class _FakeResult:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class _FakeDB:
    def __init__(self, results):
        self._queue = list(results)
        self.added = []

    async def execute(self, stmt):
        if not self._queue:
            raise AssertionError("FakeDB: ran out of queued results — unexpected extra db.execute() call.")
        return self._queue.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()


def _run(coro):
    return asyncio.run(coro)


def _record(**overrides):
    defaults = dict(
        id=uuid.uuid4(), tenant_id=TENANT, employee_id=EMP_ID, date=ddate(2026, 3, 1),
        status=AttendanceStatus.PRESENT, check_in=None, check_out=None,
        check_in_source=AttendanceSource.MANUAL, check_out_source=None,
        is_regularized=False, regularized_by_id=None,
    )
    defaults.update(overrides)
    return AttendanceRecord(**defaults)


def _employee(**overrides):
    defaults = dict(id=EMP_ID, tenant_id=TENANT, default_shift_id=None, branch_id=None)
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class _FakeEmployeeRepo:
    own_employee = None

    def __init__(self, db, tenant_id):
        pass

    async def get_by_user_id(self, user_id):
        return type(self).own_employee


@pytest.fixture(autouse=True)
def _patch_repo(monkeypatch):
    import app.api.v1.hrms.attendance as attendance_mod

    _FakeEmployeeRepo.own_employee = _employee()
    monkeypatch.setattr(attendance_mod, "EmployeeRepository", _FakeEmployeeRepo)


def _user():
    return SimpleNamespace(id=uuid.uuid4(), has_permission=lambda code: True)


# ── record_attendance ("regularize") ────────────────────────────────────────
class TestRegularizeTimesAreStored:
    def test_check_in_and_check_out_times_are_actually_saved(self):
        """THE bug assertion: previously these were accepted but discarded."""
        db = _FakeDB([_FakeResult(scalar=None)])  # no existing record for this date
        result = _run(
            record_attendance(
                EMP_ID, ddate(2026, 3, 1), "09:15", "17:45",
                AttendanceStatus.PRESENT, _user(), TENANT, db,
            )
        )
        new_records = [r for r in db.added if isinstance(r, AttendanceRecord)]
        assert len(new_records) == 1
        rec = new_records[0]
        assert rec.check_in == datetime(2026, 3, 1, 9, 15, tzinfo=timezone.utc)
        assert rec.check_out == datetime(2026, 3, 1, 17, 45, tzinfo=timezone.utc)
        assert result["created"] is True

    def test_accepts_hh_mm_ss_format_too(self):
        db = _FakeDB([_FakeResult(scalar=None)])
        _run(
            record_attendance(
                EMP_ID, ddate(2026, 3, 1), "09:15:30", None,
                AttendanceStatus.PRESENT, _user(), TENANT, db,
            )
        )
        rec = db.added[0]
        assert rec.check_in == datetime(2026, 3, 1, 9, 15, 30, tzinfo=timezone.utc)

    def test_rejects_malformed_time_string(self):
        db = _FakeDB([])
        with pytest.raises(ValidationError):
            _run(
                record_attendance(
                    EMP_ID, ddate(2026, 3, 1), "not-a-time", None,
                    AttendanceStatus.PRESENT, _user(), TENANT, db,
                )
            )

    def test_rejects_check_out_before_check_in(self):
        db = _FakeDB([])
        with pytest.raises(ValidationError):
            _run(
                record_attendance(
                    EMP_ID, ddate(2026, 3, 1), "17:00", "09:00",
                    AttendanceStatus.PRESENT, _user(), TENANT, db,
                )
            )


class TestRegularizeDoesNotDuplicate:
    def test_regularizing_twice_updates_the_same_row_not_a_new_one(self):
        """THE bug assertion: calling this a second time for the same
        employee+date used to always INSERT a second row."""
        existing = _record(check_in=None, check_out=None)
        db = _FakeDB([_FakeResult(scalar=existing)])  # an existing record IS found
        result = _run(
            record_attendance(
                EMP_ID, ddate(2026, 3, 1), "09:00", "17:00",
                AttendanceStatus.PRESENT, _user(), TENANT, db,
            )
        )
        # No new row was added — the existing one was mutated in place.
        assert db.added == []
        assert result["created"] is False
        assert result["id"] == str(existing.id)
        assert existing.check_in == datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc)
        assert existing.check_out == datetime(2026, 3, 1, 17, 0, tzinfo=timezone.utc)
        assert existing.is_regularized is True

    def test_partial_update_preserves_the_other_existing_time(self):
        """Regularizing with only check_out provided must not null out an
        already-recorded check_in (or vice versa)."""
        existing = _record(check_in=datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc), check_out=None)
        db = _FakeDB([_FakeResult(scalar=existing)])
        _run(
            record_attendance(
                EMP_ID, ddate(2026, 3, 1), None, "17:30",
                AttendanceStatus.PRESENT, _user(), TENANT, db,
            )
        )
        assert existing.check_in == datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc)  # untouched
        assert existing.check_out == datetime(2026, 3, 1, 17, 30, tzinfo=timezone.utc)  # updated


# ── check_out overnight fix ──────────────────────────────────────────────────
class _CapturingDB:
    """Captures the FIRST SQLAlchemy statement passed to execute() (the
    check_out endpoint's own AttendanceRecord lookup, which is what this
    test actually inspects), so we can assert on ITS structure — not just
    hand back canned data. Every call after the first (e.g. the
    attendance-sync module's own internal WorkSession lookup) gets a
    harmless empty result, so it short-circuits immediately without
    disturbing what was captured."""

    def __init__(self, result):
        self._first_result = result
        self.captured_stmt = None
        self._call_count = 0

    async def execute(self, stmt):
        self._call_count += 1
        if self._call_count == 1:
            self.captured_stmt = stmt
            return self._first_result
        return _FakeResult(scalar=None)

    async def flush(self):
        pass


class TestCheckOutOvernight:
    def test_query_no_longer_filters_by_calendar_date(self):
        """THE bug assertion: the record lookup must not require
        AttendanceRecord.date == today — that's exactly what broke overnight
        shifts. It should instead look for any still-open session
        (check_in set, check_out still null)."""
        yesterday_record = _record(
            date=ddate(2026, 3, 1),
            check_in=datetime(2026, 3, 1, 23, 0, tzinfo=timezone.utc),
            check_out=None,
        )
        db = _CapturingDB(_FakeResult(scalar=yesterday_record))
        body = CheckOutRequest()
        _run(check_out(body, _user(), TENANT, db))

        compiled = str(db.captured_stmt.compile(compile_kwargs={"literal_binds": True}))
        where_clause = compiled.split("WHERE", 1)[1] if "WHERE" in compiled else ""
        assert "attendance_records.date =" not in where_clause, (
            "check_out's lookup still filters by attendance_records.date == <today> — "
            "this is exactly what breaks overnight shifts (bug still present)."
        )
        assert "check_out IS NULL" in where_clause
        assert "check_in IS NOT NULL" in where_clause

    def test_finds_yesterdays_open_session_when_checking_out_after_midnight(self):
        yesterday_record = _record(
            date=ddate(2026, 3, 1),
            check_in=datetime(2026, 3, 1, 23, 0, tzinfo=timezone.utc),  # checked in 11pm
            check_out=None,
        )
        db = _FakeDB([_FakeResult(scalar=yesterday_record), _FakeResult(scalar=None)])  # + attendance-sync's WorkSession lookup
        body = CheckOutRequest()
        result = _run(check_out(body, _user(), TENANT, db))

        assert result["id"] == str(yesterday_record.id)
        assert yesterday_record.check_out is not None

    def test_computes_correct_duration_across_midnight(self, monkeypatch):
        import app.api.v1.hrms.attendance as attendance_mod

        checked_in_at = datetime(2026, 3, 1, 23, 0, tzinfo=timezone.utc)
        checked_out_at = datetime(2026, 3, 2, 1, 0, tzinfo=timezone.utc)  # 2 hours later, next calendar day

        class _FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return checked_out_at

        monkeypatch.setattr(attendance_mod, "datetime", _FrozenDateTime)

        yesterday_record = _record(date=ddate(2026, 3, 1), check_in=checked_in_at, check_out=None)
        db = _FakeDB([_FakeResult(scalar=yesterday_record), _FakeResult(scalar=None)])  # + attendance-sync's WorkSession lookup
        body = CheckOutRequest()
        _run(check_out(body, _user(), TENANT, db))

        # 23:00 -> 01:00 the next day = 120 minutes, not a negative/huge number.
        assert yesterday_record.total_minutes == 120

    def test_no_open_session_gives_a_clean_400_not_a_crash(self):
        db = _FakeDB([_FakeResult(scalar=None)])
        body = CheckOutRequest()
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _run(check_out(body, _user(), TENANT, db))
        assert exc_info.value.status_code == 400
