"""
Tests for PATCH/DELETE /payroll/runs/{id} — a run can only be edited or
deleted while still in DRAFT (never generated). Anything past that must
go through Reverse instead.

Run:  cd backend && pytest tests/test_payroll_run_edit_delete.py -v
"""
import asyncio
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

TENANT = uuid.uuid4()


def _run(coro):
    return asyncio.run(coro)


def _user():
    return SimpleNamespace(id=uuid.uuid4())


class _FakeResult:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class _FakeDB:
    def __init__(self, results):
        self._queue = list(results)
        self.deleted = []

    async def execute(self, stmt):
        return self._queue.pop(0)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def flush(self):
        pass


def _draft_run():
    from app.models.payroll import PayrollRun, PayrollRunStatus

    return PayrollRun(
        id=uuid.uuid4(), tenant_id=TENANT, name="June Payroll", period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30), pay_date=date(2026, 6, 30), currency="USD",
        status=PayrollRunStatus.DRAFT, processed_by_id=uuid.uuid4(),
    )


def _review_run():
    from app.models.payroll import PayrollRun, PayrollRunStatus

    return PayrollRun(
        id=uuid.uuid4(), tenant_id=TENANT, name="June Payroll", period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30), pay_date=date(2026, 6, 30), currency="USD",
        status=PayrollRunStatus.REVIEW, processed_by_id=uuid.uuid4(),
    )


class TestUpdateDraftRun:
    def test_can_edit_a_draft_run(self):
        from app.api.v1.hrms.payroll import update_payroll_run, PayrollRunUpdate

        run = _draft_run()
        db = _FakeDB([_FakeResult(scalar=run)])

        result = _run(update_payroll_run(run.id, PayrollRunUpdate(name="Renamed Run"), _user(), TENANT, db))

        assert result["updated"] is True
        assert run.name == "Renamed Run"

    def test_can_edit_the_period_dates_of_a_draft_run(self):
        from app.api.v1.hrms.payroll import update_payroll_run, PayrollRunUpdate

        run = _draft_run()
        db = _FakeDB([_FakeResult(scalar=run)])

        _run(update_payroll_run(run.id, PayrollRunUpdate(period_start=date(2026, 7, 1), period_end=date(2026, 7, 31)), _user(), TENANT, db))

        assert run.period_start == date(2026, 7, 1)
        assert run.period_end == date(2026, 7, 31)

    def test_only_provided_fields_change(self):
        from app.api.v1.hrms.payroll import update_payroll_run, PayrollRunUpdate

        run = _draft_run()
        original_period_start = run.period_start
        db = _FakeDB([_FakeResult(scalar=run)])

        _run(update_payroll_run(run.id, PayrollRunUpdate(name="New Name"), _user(), TENANT, db))

        assert run.name == "New Name"
        assert run.period_start == original_period_start  # untouched

    def test_cannot_edit_a_run_past_draft(self):
        from app.api.v1.hrms.payroll import update_payroll_run, PayrollRunUpdate
        from app.core.exceptions import ValidationError

        run = _review_run()
        db = _FakeDB([_FakeResult(scalar=run)])

        with pytest.raises(ValidationError, match="DRAFT"):
            _run(update_payroll_run(run.id, PayrollRunUpdate(name="Sneaky rename"), _user(), TENANT, db))

    def test_editing_a_missing_run_raises_not_found(self):
        from app.api.v1.hrms.payroll import update_payroll_run, PayrollRunUpdate
        from app.core.exceptions import NotFoundError

        db = _FakeDB([_FakeResult(scalar=None)])
        with pytest.raises(NotFoundError):
            _run(update_payroll_run(uuid.uuid4(), PayrollRunUpdate(name="x"), _user(), TENANT, db))


class TestDeleteDraftRun:
    def test_can_delete_a_draft_run(self):
        from app.api.v1.hrms.payroll import delete_payroll_run

        run = _draft_run()
        db = _FakeDB([_FakeResult(scalar=run)])

        _run(delete_payroll_run(run.id, _user(), TENANT, db))

        assert db.deleted == [run]

    def test_cannot_delete_a_run_past_draft(self):
        from app.api.v1.hrms.payroll import delete_payroll_run
        from app.core.exceptions import ValidationError

        run = _review_run()
        db = _FakeDB([_FakeResult(scalar=run)])

        with pytest.raises(ValidationError, match="DRAFT"):
            _run(delete_payroll_run(run.id, _user(), TENANT, db))

        assert db.deleted == []

    def test_deleting_a_missing_run_raises_not_found(self):
        from app.api.v1.hrms.payroll import delete_payroll_run
        from app.core.exceptions import NotFoundError

        db = _FakeDB([_FakeResult(scalar=None)])
        with pytest.raises(NotFoundError):
            _run(delete_payroll_run(uuid.uuid4(), _user(), TENANT, db))
