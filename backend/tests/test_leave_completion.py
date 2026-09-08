"""
Regression tests for "Leave completion": bug C2 remainder (balances never
wired), H5 (approver_id stored a User id into an employees FK, no status
guard), H6 (half-day/hourly unsupported end-to-end), and the Medium bug
where the leave list showed a literal "Employee" string + raw leave-type
UUID instead of real names.

No database needed — `db.execute()` is faked with a pre-queued list of
results in the exact order the endpoint code issues queries (we control
that order since we wrote it), same technique as the existing
`_FakeAsyncSession` pattern used for C3. `EmployeeRepository` is
monkeypatched the same way `test_leave_self_scope.py` already does it.

Run:  cd backend && pytest tests/test_leave_completion.py -v
"""

import asyncio
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

import app.api.v1.hrms.leave as leave_mod
from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.models.attendance import LeaveBalance, LeaveRequest, LeaveRequestStatus, LeaveType

TENANT = uuid.uuid4()
EMP_ID = uuid.uuid4()
APPROVER_USER_ID = uuid.uuid4()
APPROVER_EMPLOYEE_ID = uuid.uuid4()


# ── Fake DB plumbing (no real database) ─────────────────────────────────────
class _FakeScalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class _FakeResult:
    def __init__(self, *, scalar=None, scalars_list=None, rows=None, count=None):
        self._scalar = scalar
        self._scalars_list = scalars_list
        self._rows = rows
        self._count = count

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._count

    def scalars(self):
        return _FakeScalars(self._scalars_list or [])

    def all(self):
        return self._rows or []


class _FakeDB:
    """Executes a pre-queued list of canned results, in call order."""

    def __init__(self, results):
        self._queue = list(results)
        self.added = []

    async def execute(self, stmt):
        if not self._queue:
            raise AssertionError(
                "FakeDB: ran out of queued results — code made an unexpected "
                "extra db.execute() call (or fewer than expected)."
            )
        return self._queue.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()


class _FakeEmployeeRepo:
    """Same pattern as test_leave_self_scope.py — configured per test."""

    own_employee = None
    by_id: dict = {}

    def __init__(self, db, tenant_id):
        pass

    async def get_by_user_id(self, user_id):
        return type(self).own_employee

    async def get(self, employee_id):
        return type(self).by_id.get(employee_id)


@pytest.fixture(autouse=True)
def _patch_repo(monkeypatch):
    _FakeEmployeeRepo.own_employee = SimpleNamespace(id=EMP_ID)
    _FakeEmployeeRepo.by_id = {EMP_ID: SimpleNamespace(id=EMP_ID)}
    monkeypatch.setattr(leave_mod, "EmployeeRepository", _FakeEmployeeRepo)


def _user(*, can_approve: bool = False, can_view_all_leave: bool = False, user_id=EMP_ID):
    return SimpleNamespace(
        id=user_id,
        has_permission=lambda code: (
            (can_approve and code == "leave.approve")
            or (can_view_all_leave and code == "leave.view")
        ),
    )


def _leave_type(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        name="Annual Leave",
        code="AL",
        days_per_year=Decimal("20"),
        min_days_per_request=Decimal("1"),
        max_days_per_request=None,
        is_active=True,
        color="#3b82f6",
    )
    defaults.update(overrides)
    return LeaveType(**defaults)


def _balance(leave_type_id, **overrides):
    defaults = dict(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        employee_id=EMP_ID,
        leave_type_id=leave_type_id,
        year=2026,
        entitled_days=Decimal("20"),
        carried_forward_days=Decimal("0"),
        used_days=Decimal("0"),
        pending_days=Decimal("0"),
    )
    defaults.update(overrides)
    return LeaveBalance(**defaults)


def _run(coro):
    return asyncio.run(coro)


# ── H6: pure duration computation ───────────────────────────────────────────
class TestComputeTotalDays:
    def test_full_day_multi_day_range(self):
        d = leave_mod._compute_total_days(
            "full_day", date(2026, 3, 1), date(2026, 3, 3), None, None, Decimal("8")
        )
        assert d == Decimal("3")

    def test_half_day_is_half(self):
        d = leave_mod._compute_total_days(
            "half_day", date(2026, 3, 1), date(2026, 3, 1), "morning", None, Decimal("8")
        )
        assert d == Decimal("0.5")

    def test_half_day_rejects_multi_day_range(self):
        with pytest.raises(ValidationError):
            leave_mod._compute_total_days(
                "half_day", date(2026, 3, 1), date(2026, 3, 2), "morning", None, Decimal("8")
            )

    def test_half_day_rejects_missing_period(self):
        with pytest.raises(ValidationError):
            leave_mod._compute_total_days(
                "half_day", date(2026, 3, 1), date(2026, 3, 1), None, None, Decimal("8")
            )

    def test_hourly_converts_using_hours_per_day(self):
        d = leave_mod._compute_total_days(
            "hourly", date(2026, 3, 1), date(2026, 3, 1), None, 4, Decimal("8")
        )
        assert d == Decimal("0.50")

    def test_hourly_respects_custom_hours_per_day(self):
        d = leave_mod._compute_total_days(
            "hourly", date(2026, 3, 1), date(2026, 3, 1), None, 3, Decimal("6")
        )
        assert d == Decimal("0.50")

    def test_hourly_rejects_multi_day_range(self):
        with pytest.raises(ValidationError):
            leave_mod._compute_total_days(
                "hourly", date(2026, 3, 1), date(2026, 3, 2), None, 4, Decimal("8")
            )

    def test_hourly_rejects_zero_or_negative_hours(self):
        with pytest.raises(ValidationError):
            leave_mod._compute_total_days("hourly", date(2026, 3, 1), date(2026, 3, 1), None, 0, Decimal("8"))

    def test_hourly_rejects_more_than_a_full_work_day(self):
        with pytest.raises(ValidationError):
            leave_mod._compute_total_days("hourly", date(2026, 3, 1), date(2026, 3, 1), None, 10, Decimal("8"))

    def test_unknown_duration_type_rejected(self):
        with pytest.raises(ValidationError):
            leave_mod._compute_total_days("weekly", date(2026, 3, 1), date(2026, 3, 1), None, None, Decimal("8"))


# ── H6: org-configurable hours-per-day ──────────────────────────────────────
class TestHoursPerDay:
    def test_uses_org_setting_when_present(self):
        org = SimpleNamespace(settings={"standard_work_hours_per_day": 6})
        db = _FakeDB([_FakeResult(scalar=org)])
        result = _run(leave_mod._hours_per_day(db, TENANT))
        assert result == Decimal("6")

    def test_falls_back_to_default_when_unset(self):
        org = SimpleNamespace(settings={})
        db = _FakeDB([_FakeResult(scalar=org)])
        result = _run(leave_mod._hours_per_day(db, TENANT))
        assert result == leave_mod.DEFAULT_WORK_HOURS_PER_DAY

    def test_falls_back_to_default_when_org_missing(self):
        db = _FakeDB([_FakeResult(scalar=None)])
        result = _run(leave_mod._hours_per_day(db, TENANT))
        assert result == leave_mod.DEFAULT_WORK_HOURS_PER_DAY

    def test_ignores_garbage_setting_value(self):
        org = SimpleNamespace(settings={"standard_work_hours_per_day": "not-a-number"})
        db = _FakeDB([_FakeResult(scalar=org)])
        result = _run(leave_mod._hours_per_day(db, TENANT))
        assert result == leave_mod.DEFAULT_WORK_HOURS_PER_DAY


# ── C2: apply_leave balance enforcement ─────────────────────────────────────
class TestApplyLeaveBalance:
    def _apply(self, body_kwargs, leave_type, balance, org=None):
        body = leave_mod.LeaveApplyRequest(leave_type_id=leave_type.id, **body_kwargs)
        db = _FakeDB([
            _FakeResult(scalar=leave_type),                       # leave type lookup
            _FakeResult(scalar=org or SimpleNamespace(settings={})),  # org / hours-per-day
            _FakeResult(scalar=balance),                            # balance lookup
        ])
        result = _run(leave_mod.apply_leave(body, _user(), TENANT, db))
        return result, db

    def test_rejects_insufficient_balance(self):
        lt = _leave_type(days_per_year=Decimal("5"))
        bal = _balance(lt.id, entitled_days=Decimal("5"), used_days=Decimal("4"))  # 1 day left
        body_kwargs = dict(start_date="2026-03-01", end_date="2026-03-05")  # 5 days requested
        with pytest.raises(ConflictError):
            self._apply(body_kwargs, lt, bal)

    def test_allows_when_within_balance_and_increments_pending(self):
        lt = _leave_type(days_per_year=Decimal("20"))
        bal = _balance(lt.id, entitled_days=Decimal("20"))
        body_kwargs = dict(start_date="2026-03-01", end_date="2026-03-03")  # 3 days
        result, db = self._apply(body_kwargs, lt, bal)
        assert result["total_days"] == 3.0
        assert bal.pending_days == Decimal("3")

    def test_rejects_below_min_days_per_request(self):
        lt = _leave_type(min_days_per_request=Decimal("2"))
        bal = _balance(lt.id)
        body_kwargs = dict(start_date="2026-03-01", end_date="2026-03-01")  # 1 day, min is 2
        with pytest.raises(ValidationError):
            self._apply(body_kwargs, lt, bal)

    def test_rejects_above_max_days_per_request(self):
        lt = _leave_type(max_days_per_request=Decimal("2"))
        bal = _balance(lt.id)
        body_kwargs = dict(start_date="2026-03-01", end_date="2026-03-05")  # 5 days, max is 2
        with pytest.raises(ValidationError):
            self._apply(body_kwargs, lt, bal)

    def test_half_day_request_bypasses_min_days_floor(self):
        lt = _leave_type(min_days_per_request=Decimal("1"))
        bal = _balance(lt.id)
        body_kwargs = dict(
            start_date="2026-03-01", end_date="2026-03-01",
            duration_type="half_day", half_day_period="morning",
        )
        result, db = self._apply(body_kwargs, lt, bal)
        assert result["total_days"] == 0.5
        assert bal.pending_days == Decimal("0.5")

    def test_hourly_request_deducts_correct_fraction(self):
        lt = _leave_type()
        bal = _balance(lt.id)
        org = SimpleNamespace(settings={"standard_work_hours_per_day": 8})
        body_kwargs = dict(
            start_date="2026-03-01", end_date="2026-03-01",
            duration_type="hourly", hours=2,
        )
        result, db = self._apply(body_kwargs, lt, bal, org=org)
        assert result["total_days"] == 0.25
        assert bal.pending_days == Decimal("0.25")

    def test_inactive_leave_type_rejected(self):
        lt = _leave_type(is_active=False)
        bal = _balance(lt.id)
        body_kwargs = dict(start_date="2026-03-01", end_date="2026-03-01")
        with pytest.raises(ValidationError):
            self._apply(body_kwargs, lt, bal)

    def test_end_before_start_rejected(self):
        lt = _leave_type()
        bal = _balance(lt.id)
        body_kwargs = dict(start_date="2026-03-05", end_date="2026-03-01")
        with pytest.raises(ValidationError):
            self._apply(body_kwargs, lt, bal)


# ── H5: approve/reject — status guard + approver FK fix + balance movement ──
class TestApproveLeave:
    def test_stores_approver_employee_id_not_user_id(self):
        """THE H5 assertion: approver_id must be the approver's EMPLOYEE id,
        never their raw User id."""
        _FakeEmployeeRepo.own_employee = SimpleNamespace(id=APPROVER_EMPLOYEE_ID)
        lt = _leave_type()
        req = LeaveRequest(
            id=uuid.uuid4(), tenant_id=TENANT, employee_id=EMP_ID, leave_type_id=lt.id,
            start_date=date(2026, 3, 1), end_date=date(2026, 3, 3), total_days=Decimal("3"),
            status=LeaveRequestStatus.PENDING,
        )
        bal = _balance(lt.id, pending_days=Decimal("3"))
        db = _FakeDB([
            _FakeResult(scalar=req),
            _FakeResult(scalar=lt),
            _FakeResult(scalar=bal),
        ])
        approver = _user(can_approve=True, user_id=APPROVER_USER_ID)
        result = _run(leave_mod.approve_leave(req.id, approver, TENANT, db))

        assert req.approver_id == APPROVER_EMPLOYEE_ID
        assert req.approver_id != APPROVER_USER_ID
        assert result["status"] == "approved"

    def test_moves_pending_to_used_on_approval(self):
        _FakeEmployeeRepo.own_employee = SimpleNamespace(id=APPROVER_EMPLOYEE_ID)
        lt = _leave_type()
        req = LeaveRequest(
            id=uuid.uuid4(), tenant_id=TENANT, employee_id=EMP_ID, leave_type_id=lt.id,
            start_date=date(2026, 3, 1), end_date=date(2026, 3, 3), total_days=Decimal("3"),
            status=LeaveRequestStatus.PENDING,
        )
        bal = _balance(lt.id, pending_days=Decimal("3"), used_days=Decimal("0"))
        db = _FakeDB([_FakeResult(scalar=req), _FakeResult(scalar=lt), _FakeResult(scalar=bal)])
        _run(leave_mod.approve_leave(req.id, _user(can_approve=True), TENANT, db))

        assert bal.pending_days == Decimal("0")
        assert bal.used_days == Decimal("3")

    def test_cannot_approve_a_non_pending_request(self):
        """THE H5 status-guard assertion: no double-approval / approving an
        already-rejected request."""
        lt = _leave_type()
        req = LeaveRequest(
            id=uuid.uuid4(), tenant_id=TENANT, employee_id=EMP_ID, leave_type_id=lt.id,
            start_date=date(2026, 3, 1), end_date=date(2026, 3, 3), total_days=Decimal("3"),
            status=LeaveRequestStatus.APPROVED,
        )
        db = _FakeDB([_FakeResult(scalar=req)])
        with pytest.raises(ConflictError):
            _run(leave_mod.approve_leave(req.id, _user(can_approve=True), TENANT, db))

    def test_approver_with_no_employee_profile_gets_null_approver_id(self):
        """An HR admin/owner approving without their own employee record must
        not crash and must not write a User id into the employees FK."""
        _FakeEmployeeRepo.own_employee = None
        lt = _leave_type()
        req = LeaveRequest(
            id=uuid.uuid4(), tenant_id=TENANT, employee_id=EMP_ID, leave_type_id=lt.id,
            start_date=date(2026, 3, 1), end_date=date(2026, 3, 3), total_days=Decimal("3"),
            status=LeaveRequestStatus.PENDING,
        )
        bal = _balance(lt.id, pending_days=Decimal("3"))
        db = _FakeDB([_FakeResult(scalar=req), _FakeResult(scalar=lt), _FakeResult(scalar=bal)])
        _run(leave_mod.approve_leave(req.id, _user(can_approve=True), TENANT, db))
        assert req.approver_id is None

    def test_approving_unknown_request_404s(self):
        db = _FakeDB([_FakeResult(scalar=None)])
        with pytest.raises(NotFoundError):
            _run(leave_mod.approve_leave(uuid.uuid4(), _user(can_approve=True), TENANT, db))


class TestRejectLeave:
    def test_cannot_reject_a_non_pending_request(self):
        lt = _leave_type()
        req = LeaveRequest(
            id=uuid.uuid4(), tenant_id=TENANT, employee_id=EMP_ID, leave_type_id=lt.id,
            start_date=date(2026, 3, 1), end_date=date(2026, 3, 3), total_days=Decimal("3"),
            status=LeaveRequestStatus.REJECTED,
        )
        db = _FakeDB([_FakeResult(scalar=req)])
        with pytest.raises(ConflictError):
            _run(leave_mod.reject_leave(req.id, leave_mod.LeaveRejectRequest(), _user(can_approve=True), TENANT, db))

    def test_releases_pending_hold_on_reject(self):
        lt = _leave_type()
        req = LeaveRequest(
            id=uuid.uuid4(), tenant_id=TENANT, employee_id=EMP_ID, leave_type_id=lt.id,
            start_date=date(2026, 3, 1), end_date=date(2026, 3, 3), total_days=Decimal("3"),
            status=LeaveRequestStatus.PENDING,
        )
        bal = _balance(lt.id, pending_days=Decimal("3"))
        db = _FakeDB([_FakeResult(scalar=req), _FakeResult(scalar=bal)])
        _run(leave_mod.reject_leave(req.id, leave_mod.LeaveRejectRequest(reason="No coverage"), _user(can_approve=True), TENANT, db))
        assert bal.pending_days == Decimal("0")
        assert req.status == LeaveRequestStatus.REJECTED
        assert req.rejection_reason == "No coverage"

    def test_reject_without_existing_balance_row_does_not_crash(self):
        lt = _leave_type()
        req = LeaveRequest(
            id=uuid.uuid4(), tenant_id=TENANT, employee_id=EMP_ID, leave_type_id=lt.id,
            start_date=date(2026, 3, 1), end_date=date(2026, 3, 3), total_days=Decimal("3"),
            status=LeaveRequestStatus.PENDING,
        )
        db = _FakeDB([_FakeResult(scalar=req), _FakeResult(scalar=None)])
        _run(leave_mod.reject_leave(req.id, leave_mod.LeaveRejectRequest(), _user(can_approve=True), TENANT, db))
        assert req.status == LeaveRequestStatus.REJECTED


# ── Medium bug: list shows real employee/leave-type names ──────────────────
class TestListLeaveRequestsDisplay:
    def test_returns_real_employee_and_leave_type_names(self):
        lt = _leave_type(name="Sick Leave")
        req = LeaveRequest(
            id=uuid.uuid4(), tenant_id=TENANT, employee_id=EMP_ID, leave_type_id=lt.id,
            start_date=date(2026, 3, 1), end_date=date(2026, 3, 1), total_days=Decimal("1"),
            status=LeaveRequestStatus.PENDING, duration_type="full_day",
            created_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        )
        user = SimpleNamespace(full_name="Jordan Rivera")
        db = _FakeDB([
            _FakeResult(rows=[(req, user, lt)]),
            _FakeResult(count=1),
        ])
        result = _run(leave_mod.list_leave_requests(
            None, None, 1, 25, _user(can_view_all_leave=True), TENANT, db,
        ))
        item = result["items"][0]
        assert item["employee_name"] == "Jordan Rivera"
        assert item["employee_name"] != "Employee"
        assert item["leave_type"] == "Sick Leave"
        # Must not be a raw UUID string.
        assert item["leave_type"] != str(lt.id)


# ── GET /leave/balances ──────────────────────────────────────────────────
class TestGetLeaveBalances:
    def test_self_scope_default_uses_own_employee(self):
        lt = _leave_type(name="Annual Leave", days_per_year=Decimal("20"))
        db = _FakeDB([
            _FakeResult(scalars_list=[lt]),
            _FakeResult(scalars_list=[]),  # no existing balance row yet
        ])
        result = _run(leave_mod.get_leave_balances(None, 2026, _user(), TENANT, db))
        assert result["employee_id"] == str(EMP_ID)
        assert len(result["items"]) == 1
        assert result["items"][0]["entitled_days"] == 20.0
        assert result["items"][0]["remaining_days"] == 20.0  # untouched year -> full entitlement

    def test_uses_existing_balance_row_when_present(self):
        lt = _leave_type(name="Annual Leave", days_per_year=Decimal("20"))
        bal = _balance(lt.id, used_days=Decimal("5"), pending_days=Decimal("2"))
        db = _FakeDB([
            _FakeResult(scalars_list=[lt]),
            _FakeResult(scalars_list=[bal]),
        ])
        result = _run(leave_mod.get_leave_balances(None, 2026, _user(), TENANT, db))
        assert result["items"][0]["used_days"] == 5.0
        assert result["items"][0]["remaining_days"] == 13.0  # 20 - 5 - 2

    def test_viewing_another_employee_requires_leave_approve(self):
        other_id = uuid.uuid4()
        with pytest.raises(PermissionDeniedError):
            _run(leave_mod.get_leave_balances(other_id, 2026, _user(can_approve=False), TENANT, _FakeDB([])))