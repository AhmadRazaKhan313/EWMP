"""
Test for get_dashboard_stats — proves each stat card number comes from a
real, tenant-scoped query with the right filters (not the hardcoded dummy
object the frontend used to ship with).

Uses a fake AsyncSession that returns pre-queued scalar counts in the exact
order the service issues its 6 queries — same fake-DB pattern used
throughout this test suite (test_leave_completion.py, etc.), no real
database needed.

Run:  cd backend && pytest tests/test_dashboard_stats.py -v
"""

import asyncio
import uuid

import pytest

from app.services.dashboard import get_dashboard_stats

TENANT = uuid.uuid4()


def _run(coro):
    return asyncio.run(coro)


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one(self):
        return self._value


class _FakeDB:
    """Returns the next queued count on each execute(), in call order —
    matches the 6 queries get_dashboard_stats issues, in the order they're
    written: employees, present-today, on-leave-today, open-tickets,
    devices-online, devices-total, assets-assigned."""

    def __init__(self, counts):
        self._queue = list(counts)
        self.call_count = 0

    async def execute(self, stmt):
        self.call_count += 1
        if not self._queue:
            raise AssertionError("FakeDB: more execute() calls than expected counts queued")
        return _FakeResult(self._queue.pop(0))


class TestDashboardStats:
    def test_returns_all_expected_keys_from_the_queued_counts(self):
        db = _FakeDB([247, 198, 12, 34, 183, 190, 312])

        result = _run(get_dashboard_stats(db, TENANT))

        assert result == {
            "total_employees": 247,
            "present_today": 198,
            "on_leave_today": 12,
            "open_tickets": 34,
            "devices_online": 183,
            "devices_total": 190,
            "assets_assigned": 312,
        }

    def test_issues_exactly_seven_queries_no_more_no_less(self):
        db = _FakeDB([0, 0, 0, 0, 0, 0, 0])
        _run(get_dashboard_stats(db, TENANT))
        assert db.call_count == 7

    def test_all_zero_org_returns_zeros_not_an_error(self):
        db = _FakeDB([0, 0, 0, 0, 0, 0, 0])
        result = _run(get_dashboard_stats(db, TENANT))
        assert all(v == 0 for v in result.values())


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
