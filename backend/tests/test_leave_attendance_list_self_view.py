"""
Regression tests for self-service scoping on the two list endpoints that
back the web dashboard's Attendance and Leave sections.

Before this change, GET /attendance and GET /leave/requests were gated
purely by the manager-level permission (`attendance.view` / `leave.view`)
via `Depends(require_permission(...))`. A plain employee holding only the
self-service permission (`attendance.view_own` / `leave.apply`) got a flat
403 on both — there was no way for an ordinary employee to see even their
own attendance/leave history on the web dashboard.

Both endpoints now accept either tier:
  - `attendance.view` / `leave.view`  -> org-wide, employee_id filter is
    optional and whatever the caller passed through the query string
    (unchanged from before).
  - `attendance.view_own` / `leave.apply` -> employee_id is forced to the
    caller's own employee id, ignoring any employee_id passed in the query
    string, so a self-service holder can never read a colleague's records
    by passing a different id.
  - Neither permission -> PermissionDeniedError.

No database needed — `db.execute()` is faked with a pre-queued list of
results in the exact order the endpoint code issues queries, same pattern
as test_leave_completion.py / test_attendance_self_scope.py.

Run:  cd backend && pytest tests/test_leave_attendance_list_self_view.py -v
"""

import asyncio
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

import app.api.v1.hrms.attendance as attendance_mod
import app.api.v1.hrms.leave as leave_mod
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models.attendance import AttendanceRecord, AttendanceStatus, LeaveRequest, LeaveRequestStatus, LeaveType

TENANT = uuid.uuid4()
OWN_EMP = uuid.uuid4()
OTHER_EMP = uuid.uuid4()
USER_ID = uuid.uuid4()


def _run(coro):
    return asyncio.run(coro)


# ── Fake DB plumbing (mirrors test_leave_completion.py) ──────────────────────
class _FakeScalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class _FakeResult:
    def __init__(self, *, scalars_list=None, rows=None, count=None):
        self._scalars_list = scalars_list
        self._rows = rows
        self._count = count

    def scalar_one(self):
        return self._count

    def scalars(self):
        return _FakeScalars(self._scalars_list or [])

    def all(self):
        return self._rows or []


class _FakeDB:
    """Executes a pre-queued list of canned results, in call order. If the
    queue is empty, no db.execute() call should happen — used to prove the
    permission-denied path short-circuits before touching the database."""

    def __init__(self, results):
        self._queue = list(results)

    async def execute(self, stmt):
        if not self._queue:
            raise AssertionError(
                "FakeDB: unexpected db.execute() call — the endpoint should "
                "have raised PermissionDeniedError before querying."
            )
        return self._queue.pop(0)


class _FakeEmployeeRepo:
    own_employee = None
    by_id: dict = {}

    def __init__(self, db, tenant_id):
        pass

    async def get_by_user_id(self, user_id):
        return type(self).own_employee


def _emp(emp_id):
    return SimpleNamespace(id=emp_id)


def _user(*, permissions: set[str] = frozenset()):
    return SimpleNamespace(id=USER_ID, has_permission=lambda code: code in permissions)


@pytest.fixture(autouse=True)
def _patch_repos(monkeypatch):
    _FakeEmployeeRepo.own_employee = _emp(OWN_EMP)
    monkeypatch.setattr(attendance_mod, "EmployeeRepository", _FakeEmployeeRepo)
    monkeypatch.setattr(leave_mod, "EmployeeRepository", _FakeEmployeeRepo)


# ── GET /attendance ────────────────────────────────────────────────────────

class TestListAttendanceSelfView:
    def test_view_own_forces_employee_id_to_self_ignoring_query_param(self):
        record = AttendanceRecord(
            id=uuid.uuid4(), tenant_id=TENANT, employee_id=OWN_EMP, date=date(2026, 3, 1),
            status=AttendanceStatus.PRESENT,
        )
        db = _FakeDB([_FakeResult(scalars_list=[record]), _FakeResult(count=1)])

        result = _run(attendance_mod.list_attendance(
            None, None, OTHER_EMP, None, 1, 25,  # employee_id=OTHER_EMP in the query
            _user(permissions={"attendance.view_own"}), TENANT, db,
        ))

        # Must not raise, and must return exactly the (faked) self-scoped row —
        # the OTHER_EMP the caller asked for is never honored for this tier.
        assert result["items"][0]["employee_id"] == str(OWN_EMP)

    def test_view_own_without_linked_employee_profile_raises_not_found(self):
        _FakeEmployeeRepo.own_employee = None
        db = _FakeDB([])  # must never reach the database
        with pytest.raises(NotFoundError):
            _run(attendance_mod.list_attendance(
                None, None, None, None, 1, 25,
                _user(permissions={"attendance.view_own"}), TENANT, db,
            ))

    def test_no_attendance_permission_at_all_is_denied_before_any_query(self):
        db = _FakeDB([])  # must never reach the database
        with pytest.raises(PermissionDeniedError):
            _run(attendance_mod.list_attendance(
                None, None, None, None, 1, 25,
                _user(permissions=set()), TENANT, db,
            ))

    def test_full_view_permission_keeps_org_wide_behavior_unchanged(self):
        r1 = AttendanceRecord(id=uuid.uuid4(), tenant_id=TENANT, employee_id=OWN_EMP, date=date(2026, 3, 1), status=AttendanceStatus.PRESENT)
        r2 = AttendanceRecord(id=uuid.uuid4(), tenant_id=TENANT, employee_id=OTHER_EMP, date=date(2026, 3, 1), status=AttendanceStatus.PRESENT)
        db = _FakeDB([_FakeResult(scalars_list=[r1, r2]), _FakeResult(count=2)])

        result = _run(attendance_mod.list_attendance(
            None, None, None, None, 1, 25,  # no employee_id filter -> org-wide
            _user(permissions={"attendance.view"}), TENANT, db,
        ))

        assert {item["employee_id"] for item in result["items"]} == {str(OWN_EMP), str(OTHER_EMP)}


# ── GET /leave/requests ────────────────────────────────────────────────────

def _leave_row(employee_id):
    lt = LeaveType(id=uuid.uuid4(), tenant_id=TENANT, name="Annual Leave", code="AL", color="#3b82f6")
    req = LeaveRequest(
        id=uuid.uuid4(), tenant_id=TENANT, employee_id=employee_id, leave_type_id=lt.id,
        start_date=date(2026, 3, 1), end_date=date(2026, 3, 1), total_days=Decimal("1"),
        status=LeaveRequestStatus.PENDING, duration_type="full_day",
        created_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
    )
    user_row = SimpleNamespace(full_name="Jordan Rivera")
    return req, user_row, lt


class TestListLeaveRequestsSelfView:
    def test_apply_only_forces_employee_id_to_self_ignoring_query_param(self):
        row = _leave_row(OWN_EMP)
        db = _FakeDB([_FakeResult(rows=[row]), _FakeResult(count=1)])

        result = _run(leave_mod.list_leave_requests(
            None, OTHER_EMP, 1, 25,  # employee_id=OTHER_EMP in the query
            _user(permissions={"leave.apply"}), TENANT, db,
        ))

        assert result["items"][0]["employee_id"] == str(OWN_EMP)

    def test_apply_only_without_linked_employee_profile_raises_not_found(self):
        _FakeEmployeeRepo.own_employee = None
        db = _FakeDB([])  # must never reach the database
        with pytest.raises(NotFoundError):
            _run(leave_mod.list_leave_requests(
                None, None, 1, 25,
                _user(permissions={"leave.apply"}), TENANT, db,
            ))

    def test_no_leave_permission_at_all_is_denied_before_any_query(self):
        db = _FakeDB([])  # must never reach the database
        with pytest.raises(PermissionDeniedError):
            _run(leave_mod.list_leave_requests(
                None, None, 1, 25,
                _user(permissions=set()), TENANT, db,
            ))

    def test_full_view_permission_keeps_org_wide_behavior_unchanged(self):
        row1 = _leave_row(OWN_EMP)
        row2 = _leave_row(OTHER_EMP)
        db = _FakeDB([_FakeResult(rows=[row1, row2]), _FakeResult(count=2)])

        result = _run(leave_mod.list_leave_requests(
            None, None, 1, 25,  # no employee_id filter -> org-wide
            _user(permissions={"leave.view"}), TENANT, db,
        ))

        assert {item["employee_id"] for item in result["items"]} == {str(OWN_EMP), str(OTHER_EMP)}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
