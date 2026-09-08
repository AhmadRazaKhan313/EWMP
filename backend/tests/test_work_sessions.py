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
        db = _FakeDB([
            _FakeResult(scalar=None),  # no existing session
            _FakeResult(scalar=None),  # attendance-sync: no attendance record yet today
        ])
        result = _run(start_session(_user(), TENANT, db))

        new_sessions = [s for s in db.added if isinstance(s, WorkSession)]
        assert len(new_sessions) == 1
        assert new_sessions[0].employee_id == EMP_ID
        assert new_sessions[0].status == WorkSessionStatus.ACTIVE
        assert result["status"] == "active"

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