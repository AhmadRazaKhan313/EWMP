"""
Regression test for the HR Dashboard "always 0" bug (Medium):

`count_by_status()` did `str(row.employment_status)` on an Enum column,
which for a Python Enum gives "EmploymentStatus.ACTIVE" (the repr-style
default `__str__`), not the value "active" — even though `EmploymentStatus`
mixes in `str`. `get_dashboard_stats()` then looks up `by_status.get("active")`
etc., which never matches, so every dashboard card shows 0 regardless of
how many employees actually have that status.

No database needed — `db.execute()` returns a fake result whose rows carry
real `EmploymentStatus` enum members, exactly as SQLAlchemy would give back
for a `group_by(Employee.employment_status)` query.

Run:  cd backend && pytest tests/test_hr_dashboard_counts.py -v
"""
import asyncio
import uuid
from types import SimpleNamespace

import pytest

from app.models.employee import EmploymentStatus
from app.repositories.employee import EmployeeRepository
from app.services.employee import EmployeeService

TENANT = uuid.uuid4()


class _FakeRow(SimpleNamespace):
    """Mimics a SQLAlchemy Row with labeled columns (`.employment_status`, `.count`)."""


class _FakeCountResult:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _FakeDB:
    def __init__(self, result):
        self._result = result

    async def execute(self, stmt):
        return self._result


def _run(coro):
    return asyncio.run(coro)


class TestCountByStatus:
    def test_keys_are_plain_status_values_not_enum_repr(self):
        """THE bug assertion: keys must be 'active', not 'EmploymentStatus.ACTIVE'."""
        rows = [
            _FakeRow(employment_status=EmploymentStatus.ACTIVE, count=12),
            _FakeRow(employment_status=EmploymentStatus.PROBATION, count=3),
            _FakeRow(employment_status=EmploymentStatus.ON_LEAVE, count=2),
        ]
        db = _FakeDB(_FakeCountResult(rows))
        repo = EmployeeRepository(db, TENANT)

        result = _run(repo.count_by_status())

        assert result == {"active": 12, "probation": 3, "on_leave": 2}
        # Explicitly guard against the old broken shape reappearing.
        assert "EmploymentStatus.ACTIVE" not in result

    def test_empty_result_gives_empty_dict(self):
        db = _FakeDB(_FakeCountResult([]))
        repo = EmployeeRepository(db, TENANT)
        result = _run(repo.count_by_status())
        assert result == {}


class TestDashboardStatsUsesRealKeys:
    def test_dashboard_cards_reflect_actual_counts(self, monkeypatch):
        """End-to-end: get_dashboard_stats() must surface non-zero numbers
        when count_by_status() reports non-zero counts for those statuses."""

        class _FakeRepo:
            async def count_by_status(self):
                return {"active": 12, "probation": 3, "on_leave": 2, "notice_period": 1}

            async def count_by_department(self):
                return [{"department_id": None, "count": 18}]

        service = EmployeeService.__new__(EmployeeService)
        service.repo = _FakeRepo()

        stats = _run(service.get_dashboard_stats())

        assert stats["total_active"] == 12
        assert stats["on_probation"] == 3
        assert stats["on_leave"] == 2
        assert stats["notice_period"] == 1

    def test_dashboard_cards_are_zero_only_when_actually_zero(self):
        class _FakeRepo:
            async def count_by_status(self):
                return {}

            async def count_by_department(self):
                return []

        service = EmployeeService.__new__(EmployeeService)
        service.repo = _FakeRepo()

        stats = _run(service.get_dashboard_stats())
        assert stats["total_active"] == 0
        assert stats["on_probation"] == 0
