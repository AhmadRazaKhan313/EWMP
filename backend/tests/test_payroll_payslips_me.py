"""
Tests for GET /payroll/payslips/me — the self-service "browse my own
payslip history" endpoint. See the endpoint's own docstring in
app/api/v1/hrms/payroll.py for why this exists: GET /runs (the admin
payroll-runs list) is locked behind payroll.view, and GET
/runs/{run_id}/payslips needs a run_id an employee has no way to
discover on their own — so there was no self-service way to browse
payslip history at all before this endpoint.

Run:  cd backend && pytest tests/test_payroll_payslips_me.py -v
"""
import asyncio
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.exceptions import NotFoundError
from app.models.payroll import Payslip, PayslipStatus, PayrollRun, PayrollRunStatus

TENANT = uuid.uuid4()
EMP_ID = uuid.uuid4()


def _run(coro):
    return asyncio.run(coro)


class _FakeScalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class _FakeResult:
    def __init__(self, scalar=None, scalars_list=None, scalar_one=None):
        self._scalar = scalar
        self._scalars_list = scalars_list
        self._scalar_one = scalar_one

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar_one

    def scalars(self):
        return _FakeScalars(self._scalars_list or [])


class _FakeDB:
    def __init__(self, results):
        self._queue = list(results)

    async def execute(self, stmt):
        if not self._queue:
            raise AssertionError("FakeDB: ran out of queued results.")
        return self._queue.pop(0)


class _FakeEmployeeRepo:
    own_employee = None

    def __init__(self, db, tenant_id):
        pass

    async def get_by_user_id(self, user_id):
        return type(self).own_employee


@pytest.fixture(autouse=True)
def _patch_repo(monkeypatch):
    from app.api.v1.hrms import payroll as payroll_mod

    _FakeEmployeeRepo.own_employee = SimpleNamespace(id=EMP_ID)
    monkeypatch.setattr(payroll_mod, "EmployeeRepository", _FakeEmployeeRepo)


def _run_obj(**overrides):
    import datetime as dt

    defaults = dict(
        id=uuid.uuid4(), tenant_id=TENANT, name="September 2026",
        period_start=dt.date(2026, 9, 1), period_end=dt.date(2026, 9, 30),
        pay_date=dt.date(2026, 10, 1), status=PayrollRunStatus.PAID, currency="USD",
    )
    defaults.update(overrides)
    return PayrollRun(**defaults)


def _payslip(run, **overrides):
    defaults = dict(
        id=uuid.uuid4(), tenant_id=TENANT, payroll_run_id=run.id, employee_id=EMP_ID,
        status=PayslipStatus.PAID, gross_salary=Decimal("60000"),
        total_deductions=Decimal("10000"), net_salary=Decimal("50000"),
    )
    defaults.update(overrides)
    p = Payslip(**defaults)
    p.payroll_run = run
    return p


class TestListMyPayslips:
    def test_returns_the_callers_own_payslips(self):
        from app.api.v1.hrms.payroll import list_my_payslips

        run = _run_obj()
        payslip = _payslip(run)
        db = _FakeDB([
            _FakeResult(scalars_list=[payslip]),
            _FakeResult(scalar_one=1),
        ])
        user = SimpleNamespace(id=uuid.uuid4())

        result = _run(list_my_payslips(1, 25, user, TENANT, db))

        assert result["total"] == 1
        assert result["items"][0]["id"] == str(payslip.id)
        assert result["items"][0]["net_salary"] == "50000"
        assert result["items"][0]["run"]["name"] == "September 2026"

    def test_no_employee_profile_gets_404_not_403(self):
        """Same "clean 404, not an unhandled error" contract as every
        other self-service endpoint in this file (work-sessions, leave)."""
        from app.api.v1.hrms.payroll import list_my_payslips

        _FakeEmployeeRepo.own_employee = None
        db = _FakeDB([])
        user = SimpleNamespace(id=uuid.uuid4())

        with pytest.raises(NotFoundError):
            _run(list_my_payslips(1, 25, user, TENANT, db))

    def test_no_payroll_view_permission_required(self):
        """The whole point of this endpoint: it takes no `permission`
        dependency at all, unlike GET /runs (payroll.view) — a plain
        employee with zero payroll permissions must still be able to
        call this. Asserted at the signature level since a fake user
        with has_permission always False would pass either way."""
        import inspect

        from app.api.v1.hrms.payroll import list_my_payslips

        sig = inspect.signature(list_my_payslips)
        current_user_param = sig.parameters["current_user"]
        # `require_permission("...")` for other admin endpoints shows up
        # as a Depends() default whose dependency is a closure named
        # `dependency` wrapping require_permission's checks; get_current_user
        # itself is used directly elsewhere for self-service routes. The
        # simplest robust check: this must NOT be the same dependency
        # callable object require_permission would produce for e.g.
        # list_payroll_runs's current_user param.
        from app.api.v1.hrms.payroll import list_payroll_runs

        admin_param = inspect.signature(list_payroll_runs).parameters["current_user"]
        assert current_user_param.default.dependency != admin_param.default.dependency

    def test_empty_when_caller_has_no_payslips(self):
        from app.api.v1.hrms.payroll import list_my_payslips

        db = _FakeDB([
            _FakeResult(scalars_list=[]),
            _FakeResult(scalar_one=0),
        ])
        user = SimpleNamespace(id=uuid.uuid4())

        result = _run(list_my_payslips(1, 25, user, TENANT, db))
        assert result["total"] == 0
        assert result["items"] == []
