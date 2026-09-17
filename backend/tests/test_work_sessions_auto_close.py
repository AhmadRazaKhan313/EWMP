"""
Tests for _next_local_midnight_utc — the timezone cutoff math behind
work_sessions.auto_close_overnight_sessions.

Only the pure helper is covered here, not the Celery task itself: it
talks to AsyncSessionLocal() directly rather than taking an injected
`db`, the same shape device_health.mark_stale_devices_offline already
uses (and which also has no test file) — so there's nothing here for the
_FakeDB pattern used elsewhere in this test suite to attach to. The
timezone-boundary math is the one part of this file worth pinning down
regardless, since getting it wrong silently mis-bills employees' hours.

Run:  cd backend && pytest tests/test_work_sessions_auto_close.py -v
"""
from datetime import UTC, datetime, timedelta

from app.workers.tasks.work_sessions import _next_local_midnight_utc


class TestNextLocalMidnightUtc:
    def test_none_when_session_has_not_crossed_midnight_yet(self):
        # Started an hour ago, same local day — nothing to close.
        started_at = datetime.now(UTC) - timedelta(hours=1)
        assert _next_local_midnight_utc(started_at, "UTC") is None

    def test_returns_utc_midnight_for_a_utc_org(self):
        started_at = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
        cutoff = _next_local_midnight_utc(started_at, "UTC")
        assert cutoff == datetime(2026, 3, 2, 0, 0, tzinfo=UTC)

    def test_uses_local_midnight_not_utc_midnight_for_a_non_utc_org(self):
        # Asia/Karachi is UTC+5 — 9 AM local on Mar 1 is 04:00 UTC. Local
        # midnight (Mar 2 00:00 PKT) is 2026-03-01 19:00 UTC, several
        # hours before UTC midnight would have been. Getting this wrong
        # (using UTC midnight instead) would either cut the session off
        # too early or let it run 5 extra hours into the next local day.
        started_at = datetime(2026, 3, 1, 4, 0, tzinfo=UTC)
        cutoff = _next_local_midnight_utc(started_at, "Asia/Karachi")
        assert cutoff == datetime(2026, 3, 1, 19, 0, tzinfo=UTC)

    def test_falls_back_to_utc_for_an_unknown_timezone_name(self):
        started_at = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
        cutoff = _next_local_midnight_utc(started_at, "Not/ARealZone")
        assert cutoff == datetime(2026, 3, 2, 0, 0, tzinfo=UTC)

    def test_far_in_the_past_session_closes_at_its_first_midnight_not_the_latest_one(self):
        # A session that's been open for many days should close at the
        # midnight right after it started — not "the most recent
        # midnight" — so a days-old forgotten check-in doesn't get
        # credited with multiple days of "work".
        started_at = datetime.now(UTC) - timedelta(days=5, hours=1)
        cutoff = _next_local_midnight_utc(started_at, "UTC")
        expected_day = (started_at + timedelta(days=1)).date()
        assert cutoff.date() == expected_day
        assert cutoff.time() == datetime.min.time()
