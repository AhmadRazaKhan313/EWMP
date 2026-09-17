"""
Tests for the Phase 3 self-service WorkSession/Break API.

Run:  cd backend && pytest tests/test_work_sessions.py -v
"""
import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.api.v1.hrms.work_sessions import (
    BreakStartRequest,
    end_break,
    end_session,
    get_active_session,
    list_break_types,
    list_breaks,
    start_break,
    start_session,
)
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models.work_session import BreakRecord, BreakType, WorkSession, WorkSessionStatus

TENANT = uuid.uuid4()
EMP_ID = uuid.uuid4()
OTHER_EMP_ID = uuid.uuid4()


class _FakeResult:
    def __init__(self, scalar=None, scalars_list=None):
        self._scalar = scalar
        self._scalars_list = scalars_list or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        if self._scalar is None:
            raise AssertionError("scalar_one() called with no row queued")
        return self._scalar

    def scalars(self):
        return self


class _FakeDB:
    def __init__(self, results):
        self._queue = list(results)
        self.added = []

    async def execute(self, stmt):
        if not self._queue:
            raise AssertionError("FakeDB: ran out of queued results.")
        return self._queue.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    def all(self):  # supports .scalars().all() chains where pre-seeded
        raise NotImplementedError


class _ScalarsResult:
    """Separate helper for the `.scalars().all()` call in end_session/list_breaks."""

    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items

    def scalar_one_or_none(self):
        raise NotImplementedError


class _FakeEmployeeRepo:
    own_employee = None

    def __init__(self, db, tenant_id):
        pass

    async def get_by_user_id(self, user_id):
        return type(self).own_employee

    async def get(self, employee_id):
        """Used by start_session's attendance-sync step (EmployeeRepository(db,
        tenant_id).get(employee_id)) — a plain lookup, not a db.execute() call,
        so it doesn't consume a queued _FakeDB result."""
        return SimpleNamespace(id=employee_id, default_shift_id=None)


@pytest.fixture(autouse=True)
def _patch_repo(monkeypatch):
    import app.api.v1.hrms.work_sessions as ws_mod

    _FakeEmployeeRepo.own_employee = SimpleNamespace(id=EMP_ID)
    monkeypatch.setattr(ws_mod, "EmployeeRepository", _FakeEmployeeRepo)


def _run(coro):
    return asyncio.run(coro)


def _user():
    return SimpleNamespace(id=uuid.uuid4())


def _session(**overrides):
    defaults = dict(
        id=uuid.uuid4(), tenant_id=TENANT, employee_id=EMP_ID,
        started_at=datetime.now(UTC) - timedelta(hours=2),
        ended_at=None, status=WorkSessionStatus.ACTIVE, total_minutes=None,
    )
    defaults.update(overrides)
    return WorkSession(**defaults)


class TestGetActiveSession:
    def test_returns_none_when_no_active_session(self):
        db = _FakeDB([_FakeResult(scalar=None)])
        result = _run(get_active_session(_user(), TENANT, db))
        assert result is None

    def test_returns_the_active_session(self):
        session = _session()
        db = _FakeDB([_FakeResult(scalar=session), _ScalarsResult([])])  # + _break_totals
        result = _run(get_active_session(_user(), TENANT, db))
        assert result["id"] == str(session.id)
        assert result["status"] == "active"

    def test_returns_an_on_break_session_too_not_just_active(self):
        session = _session(status=WorkSessionStatus.ON_BREAK)
        db = _FakeDB([_FakeResult(scalar=session), _ScalarsResult([])])  # + _break_totals
        result = _run(get_active_session(_user(), TENANT, db))
        assert result["status"] == "on_break"


class TestStartSession:
    def test_creates_a_new_session_when_none_exists(self):
        # Starting a session now also opens an attendance PUNCH (see
        # ensure_attendance_checked_in in attendance_sync.py, rewritten to
        # fix the bug where every desktop check-in after the day's first
        # silently vanished from attendance — see that function's
        # docstring). That path makes more round trips than the old
        # single-column write it replaced:
        #   1. WorkSession existing-session check (this test's own guard)
        #   2. get_open_punch — is a punch already open? (idempotency check)
        #   3. get_open_punch again, inside open_punch itself (defense in
        #      depth against a race between the two calls)
        #   4. get_or_create_day — does today's attendance_records row exist?
        #   5. recalculate_from_punches — re-reads the day's punches to
        #      rebuild check_in/check_out/total_minutes from them
        # employee.default_shift_id is None in this fixture, so no Shift
        # lookup follows step 5.
        db = _FakeDB([
            _FakeResult(scalar=None),  # 1. no existing WorkSession
            _FakeResult(scalar=None),  # 2. no open punch (idempotency check)
            _FakeResult(scalar=None),  # 3. no open punch (open_punch's own check)
            _FakeResult(scalar=None),  # 4. no attendance_records row for today yet
            _ScalarsResult([]),        # 5. recalculate_from_punches's punch list
        ])
        result = _run(start_session(_user(), TENANT, db))

        new_sessions = [s for s in db.added if isinstance(s, WorkSession)]
        assert len(new_sessions) == 1
        assert new_sessions[0].employee_id == EMP_ID
        assert new_sessions[0].status == WorkSessionStatus.ACTIVE
        assert result["status"] == "active"

        # The bug this whole rewrite exists to fix: a new attendance PUNCH
        # must actually be created, every time, not only silently accepted
        # on the day's first call. Asserting on the created objects
        # directly, rather than only on the WorkSession, is what would
        # have caught the original "second check-in vanishes" bug — the
        # old code also returned a 200 with a plausible-looking response.
        from app.models.attendance import AttendancePunch

        new_punches = [p for p in db.added if isinstance(p, AttendancePunch)]
        assert len(new_punches) == 1
        assert new_punches[0].employee_id == EMP_ID

    def test_is_idempotent_returns_existing_session_instead_of_creating_a_second(self):
        """THE core assertion: starting twice must never fork into two
        concurrent sessions (e.g. a double-click on Check In)."""
        existing = _session()
        db = _FakeDB([_FakeResult(scalar=existing), _ScalarsResult([])])  # + _break_totals

        result = _run(start_session(_user(), TENANT, db))

        assert db.added == []  # nothing new created
        assert result["id"] == str(existing.id)

    def test_no_employee_profile_gets_404(self):
        from app.api.v1.hrms.work_sessions import EmployeeRepository as PatchedRepo
        PatchedRepo.own_employee = None  # type: ignore[attr-defined]
        db = _FakeDB([])
        with pytest.raises(NotFoundError):
            _run(start_session(_user(), TENANT, db))


class TestEndSession:
    def test_computes_total_minutes_excluding_break_time(self):
        started = datetime.now(UTC) - timedelta(hours=2)
        session = _session(started_at=started)
        db = _FakeDB([
            _FakeResult(scalar=session),  # _get_own_session_or_404
            _FakeResult(scalar=None),  # no open break
            _ScalarsResult([]),  # no breaks at all -> 0 break minutes
            _FakeResult(scalar=None),  # attendance-sync check-out: no open attendance record
        ])

        result = _run(end_session(session.id, _user(), TENANT, db))

        # ~120 minutes elapsed, 0 break minutes -> total ~120 (allow small test-runtime slack)
        assert 118 <= result["total_minutes"] <= 121
        assert result["status"] == "ended"

    def test_subtracts_a_completed_break_from_the_total(self):
        started = datetime.now(UTC) - timedelta(hours=2)
        session = _session(started_at=started)
        break_record = BreakRecord(
            id=uuid.uuid4(), tenant_id=TENANT, work_session_id=session.id,
            started_at=started + timedelta(minutes=30),
            ended_at=started + timedelta(minutes=45),  # 15-minute break
        )
        db = _FakeDB([
            _FakeResult(scalar=session),
            _FakeResult(scalar=None),  # no OPEN break (this one's already closed)
            _ScalarsResult([break_record]),
            _FakeResult(scalar=None),  # attendance-sync check-out
        ])

        result = _run(end_session(session.id, _user(), TENANT, db))

        assert 103 <= result["total_minutes"] <= 106  # 120 - 15 = 105ish

    def test_auto_closes_a_dangling_open_break_on_end(self):
        started = datetime.now(UTC) - timedelta(hours=1)
        session = _session(started_at=started, status=WorkSessionStatus.ON_BREAK)
        open_break = BreakRecord(
            id=uuid.uuid4(), tenant_id=TENANT, work_session_id=session.id,
            started_at=started + timedelta(minutes=10), ended_at=None,
        )
        db = _FakeDB([
            _FakeResult(scalar=session),
            _FakeResult(scalar=open_break),
            _ScalarsResult([open_break]),
            _FakeResult(scalar=None),  # attendance-sync check-out
        ])

        _run(end_session(session.id, _user(), TENANT, db))

        assert open_break.ended_at is not None

    def test_cannot_end_an_already_ended_session(self):
        session = _session(status=WorkSessionStatus.ENDED, ended_at=datetime.now(UTC))
        db = _FakeDB([_FakeResult(scalar=session)])
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _run(end_session(session.id, _user(), TENANT, db))
        assert exc_info.value.status_code == 409

    def test_cannot_end_another_employees_session(self):
        session = _session(employee_id=OTHER_EMP_ID)
        db = _FakeDB([_FakeResult(scalar=session)])
        with pytest.raises(PermissionDeniedError):
            _run(end_session(session.id, _user(), TENANT, db))

    def test_unknown_session_404s(self):
        db = _FakeDB([_FakeResult(scalar=None)])
        with pytest.raises(NotFoundError):
            _run(end_session(uuid.uuid4(), _user(), TENANT, db))


class TestBreaks:
    def test_start_break_pauses_an_active_session(self):
        session = _session(status=WorkSessionStatus.ACTIVE)
        db = _FakeDB([_FakeResult(scalar=session), _ScalarsResult([])])  # + _break_totals

        _run(start_break(session.id, BreakStartRequest(), _user(), TENANT, db))

        assert session.status == WorkSessionStatus.ON_BREAK
        new_breaks = [b for b in db.added if isinstance(b, BreakRecord)]
        assert len(new_breaks) == 1

    def test_cannot_start_a_break_on_an_already_on_break_session(self):
        session = _session(status=WorkSessionStatus.ON_BREAK)
        db = _FakeDB([_FakeResult(scalar=session)])
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _run(start_break(session.id, BreakStartRequest(), _user(), TENANT, db))
        assert exc_info.value.status_code == 409

    def test_cannot_start_a_break_on_an_ended_session(self):
        session = _session(status=WorkSessionStatus.ENDED)
        db = _FakeDB([_FakeResult(scalar=session)])
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            _run(start_break(session.id, BreakStartRequest(), _user(), TENANT, db))

    def test_end_break_resumes_the_session(self):
        session = _session(status=WorkSessionStatus.ON_BREAK)
        open_break = BreakRecord(
            id=uuid.uuid4(), tenant_id=TENANT, work_session_id=session.id,
            started_at=datetime.now(UTC) - timedelta(minutes=10), ended_at=None,
        )
        db = _FakeDB([_FakeResult(scalar=session), _FakeResult(scalar=open_break), _ScalarsResult([])])

        result = _run(end_break(session.id, _user(), TENANT, db))

        assert session.status == WorkSessionStatus.ACTIVE
        assert open_break.ended_at is not None
        assert result["status"] == "active"

    def test_cannot_end_a_break_on_a_session_not_on_break(self):
        session = _session(status=WorkSessionStatus.ACTIVE)
        db = _FakeDB([_FakeResult(scalar=session)])
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _run(end_break(session.id, _user(), TENANT, db))
        assert exc_info.value.status_code == 409

    def test_list_breaks_returns_all_breaks_for_the_session(self):
        session = _session()
        b1 = BreakRecord(id=uuid.uuid4(), tenant_id=TENANT, work_session_id=session.id, started_at=datetime.now(UTC), ended_at=None)
        db = _FakeDB([_FakeResult(scalar=session), _ScalarsResult([b1])])

        result = _run(list_breaks(session.id, _user(), TENANT, db))
        assert len(result["items"]) == 1


class TestListBreakTypes:
    def test_returns_only_active_types(self):
        active = BreakType(id=uuid.uuid4(), tenant_id=TENANT, name="Lunch", is_paid=False, max_minutes=60, is_active=True)
        db = _FakeDB([_ScalarsResult([active])])

        result = _run(list_break_types(_user(), TENANT, db))

        assert len(result["items"]) == 1
        assert result["items"][0]["name"] == "Lunch"
        assert result["items"][0]["is_paid"] is False
        assert result["items"][0]["max_minutes"] == 60

    def test_empty_org_gets_an_empty_list_not_an_error(self):
        db = _FakeDB([_ScalarsResult([])])
        result = _run(list_break_types(_user(), TENANT, db))
        assert result["items"] == []


class TestBreakTotalsPrecisionBugFix:
    """
    Regression tests for the sub-60-second-break bug: `_break_totals` used
    to floor-divide each break's duration to whole minutes
    (`int(seconds // 60)`) before summing. A break lasting anything under
    60 seconds — the norm in practice, since there's always some network
    latency between the break/start and break/end clicks and the server
    timestamps it records — floored to exactly 0 and vanished from the
    total entirely. The desktop/web timers then subtracted 0 break time
    from "time since check-in", so the break's real duration silently got
    counted as WORKED time instead of break time once the employee
    resumed — reported as "working time shows the wrong minute after a
    break ends".

    Fix: sum whole seconds first, only floor-divide to minutes for the
    (kept for compatibility) `total_break_minutes` value; the new
    `total_break_seconds` is exact and is what timer math should use.
    """

    def test_a_59_second_break_no_longer_vanishes(self):
        from app.api.v1.hrms.work_sessions import _break_totals

        started = datetime.now(UTC) - timedelta(seconds=59)
        b = BreakRecord(id=uuid.uuid4(), tenant_id=TENANT, work_session_id=uuid.uuid4(), started_at=started, ended_at=datetime.now(UTC))
        db = _FakeDB([_ScalarsResult([b])])

        minutes, seconds, open_break = _run(_break_totals(db, uuid.uuid4()))

        # The old bug: minutes == 0 AND (because desktop/web multiplied
        # minutes * 60) the break contributed literally nothing to the
        # subtraction. The fix doesn't change the (inherently lossy)
        # minutes value, but does give callers the precise seconds.
        assert minutes == 0
        assert seconds == 59
        assert open_break is None

    def test_a_90_second_break_no_longer_loses_its_extra_30_seconds(self):
        from app.api.v1.hrms.work_sessions import _break_totals

        started = datetime.now(UTC) - timedelta(seconds=90)
        b = BreakRecord(id=uuid.uuid4(), tenant_id=TENANT, work_session_id=uuid.uuid4(), started_at=started, ended_at=datetime.now(UTC))
        db = _FakeDB([_ScalarsResult([b])])

        minutes, seconds, _ = _run(_break_totals(db, uuid.uuid4()))

        assert minutes == 1  # old lossy value, kept for compatibility
        assert seconds == 90  # what timer math should actually subtract

    def test_multiple_short_breaks_sum_correctly_in_seconds(self):
        from app.api.v1.hrms.work_sessions import _break_totals

        now = datetime.now(UTC)
        b1 = BreakRecord(id=uuid.uuid4(), tenant_id=TENANT, work_session_id=uuid.uuid4(), started_at=now - timedelta(seconds=200), ended_at=now - timedelta(seconds=155))  # 45s
        b2 = BreakRecord(id=uuid.uuid4(), tenant_id=TENANT, work_session_id=uuid.uuid4(), started_at=now - timedelta(seconds=100), ended_at=now - timedelta(seconds=60))  # 40s
        db = _FakeDB([_ScalarsResult([b1, b2])])

        minutes, seconds, _ = _run(_break_totals(db, uuid.uuid4()))

        # Old bug: floor(45/60) + floor(40/60) = 0 + 0 = 0 minutes, both
        # breaks vanish even though together they're 85 real seconds.
        assert seconds == 85
        assert minutes == 1  # floor(85/60) — correct once summed as seconds first

    def test_end_break_response_carries_the_precise_seconds_field(self):
        """End-to-end through the real endpoint: a ~1-minute break's
        end_break() response must expose total_break_seconds, not just
        the lossy total_break_minutes, so clients can fix their math."""
        session = _session(status=WorkSessionStatus.ON_BREAK)
        open_break = BreakRecord(
            id=uuid.uuid4(), tenant_id=TENANT, work_session_id=session.id,
            started_at=datetime.now(UTC) - timedelta(seconds=58), ended_at=None,
        )
        db = _FakeDB([
            _FakeResult(scalar=session),       # _get_own_session_or_404
            _FakeResult(scalar=open_break),    # the open-break lookup
            _ScalarsResult([open_break]),      # _break_totals (open_break.ended_at gets set before this query re-runs)
        ])

        result = _run(end_break(session.id, _user(), TENANT, db))

        assert result["status"] == "active"
        assert "total_break_seconds" in result
        # The break was ~58s — under the old bug this would've reported
        # total_break_minutes == 0 and (multiplied by 60) contributed
        # nothing; now total_break_seconds reflects the real duration.
        assert result["total_break_seconds"] >= 57

class TestDesktopSecondCheckInIsNotDropped:
    """
    Regression guard for the reported bug: the 1st check-in/check-out of
    the day showed up correctly, but every one after that neither counted
    towards worked minutes nor appeared anywhere.

    Root cause: ensure_attendance_checked_in (attendance_sync.py) wrote
    straight onto AttendanceRecord.check_in and returned immediately
    whenever that column was already set for today — which is every call
    after the first. The desktop app's own WorkSession was tracking each
    start/stop correctly; only the ATTENDANCE side silently stopped
    updating after punch one.

    This test starts and ends two sessions in the same day and checks the
    attendance side directly (via the punch service), which is the part
    that used to go silent.
    """

    def test_a_second_desktop_session_the_same_day_creates_a_second_punch(self):
        import app.services.attendance_sync as sync_mod
        from app.models.attendance import AttendancePunch, AttendanceRecord

        calls: list[tuple[str, object]] = []

        class _RecordingDB:
            """Mimics just enough of AsyncSession for the punch service to
            run against real (unpersisted) in-memory model instances,
            rather than hand-queued opaque results — the previous style
            of test could not have caught this bug because the fake
            queue's replies are just whatever the test author queued,
            independent of what the code under test actually did with
            them."""

            def __init__(self):
                self.records: list[AttendanceRecord] = []
                self.punches: list[AttendancePunch] = []

            def add(self, obj):
                if isinstance(obj, AttendanceRecord):
                    self.records.append(obj)
                elif isinstance(obj, AttendancePunch):
                    self.punches.append(obj)

            async def flush(self):
                for obj in (*self.records, *self.punches):
                    if getattr(obj, "id", None) is None:
                        obj.id = uuid.uuid4()

            async def execute(self, stmt):
                entity = stmt.column_descriptions[0]["entity"]
                calls.append((entity.__name__, None))

                if entity is AttendancePunch:
                    # Both "is there an open punch" and "all punches for
                    # this record" queries land here; distinguish by
                    # whether the statement filters on punch_out IS NULL.
                    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
                    if "punch_out IS NULL" in compiled:
                        open_ones = [p for p in self.punches if p.punch_out is None]
                        return _FakeResult(scalar=open_ones[-1] if open_ones else None)
                    return _ScalarsResult(list(self.punches))

                if entity is AttendanceRecord:
                    return _FakeResult(scalar=self.records[-1] if self.records else None)

                if entity.__name__ == "Shift":
                    return _FakeResult(scalar=None)

                raise AssertionError(f"unexpected query against {entity}")

        db = _RecordingDB()
        employee = SimpleNamespace(id=EMP_ID, default_shift_id=None)

        morning_in = datetime.now(UTC) - timedelta(hours=6)
        morning_out = morning_in + timedelta(hours=2)
        afternoon_in = morning_out + timedelta(hours=1)
        afternoon_out = afternoon_in + timedelta(hours=2)

        from app.models.attendance import AttendanceSource

        _run(
            sync_mod.ensure_attendance_checked_in(
                db, TENANT, employee, source=AttendanceSource.DESKTOP_AGENT, checked_in_at=morning_in
            )
        )
        _run(sync_mod.ensure_attendance_checked_out(db, TENANT, EMP_ID, checked_out_at=morning_out))

        # This second start is the exact scenario that used to vanish.
        _run(
            sync_mod.ensure_attendance_checked_in(
                db, TENANT, employee, source=AttendanceSource.DESKTOP_AGENT, checked_in_at=afternoon_in
            )
        )
        record = _run(
            sync_mod.ensure_attendance_checked_out(db, TENANT, EMP_ID, checked_out_at=afternoon_out)
        )

        assert len(db.punches) == 2, "the afternoon session must create its OWN punch, not be dropped"
        assert db.punches[0].punch_in == morning_in
        assert db.punches[0].punch_out == morning_out
        assert db.punches[1].punch_in == afternoon_in
        assert db.punches[1].punch_out == afternoon_out

        # And the day's total must be the SUM of both sessions (2h + 2h),
        # not just the first one — this is the number payroll reads.
        assert record.total_minutes == 240
        assert record.punch_count == 2
