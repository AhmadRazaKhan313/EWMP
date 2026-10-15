"""
Auto-cutoff deadline logic.

The rule for a forgotten check-out: a MORNING shift (starts before 12:00) is
closed at 00:00 that night; an EVENING shift (starts at/after 12:00) is closed
at 09:00 the next morning. Hours for the closed punch are 0.

These are pure-function tests — no database — because the cutoff maths is
where the multi-shift and overnight edge cases live, and those are worth
pinning down independently of the scheduler that applies them.
"""

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.models.attendance import Shift
from app.services.attendance_punches import (
    CutoffPolicy,
    compute_cutoff_at,
)


def make_shift(start: str, end: str, overnight: bool = False, break_minutes: int = 60) -> Shift:
    """A Shift instance that is never persisted — only its time fields matter here."""
    shift = Shift()
    shift.start_time = time.fromisoformat(start)
    shift.end_time = time.fromisoformat(end)
    shift.is_overnight = overnight
    shift.break_duration_minutes = break_minutes
    return shift


def at(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=UTC)


KARACHI = ZoneInfo("Asia/Karachi")


class TestMorningShift:
    def test_closed_at_midnight_that_night(self):
        shift = make_shift("09:00", "18:00")
        assert compute_cutoff_at(at("2026-09-17T09:05:00"), shift) == at("2026-09-18T00:00:00")

    def test_early_start_shift_is_also_a_morning_shift(self):
        shift = make_shift("06:00", "14:00")
        assert compute_cutoff_at(at("2026-09-17T06:00:00"), shift) == at("2026-09-18T00:00:00")

    def test_a_late_check_in_still_closes_at_the_same_midnight(self):
        shift = make_shift("09:00", "18:00")
        assert compute_cutoff_at(at("2026-09-17T15:00:00"), shift) == at("2026-09-18T00:00:00")

    def test_midnight_is_on_the_office_clock_not_utc(self):
        shift = make_shift("09:00", "18:00")
        punch_in = datetime(2026, 9, 17, 9, 0, tzinfo=KARACHI)
        assert compute_cutoff_at(punch_in, shift, zone=KARACHI) == datetime(2026, 9, 18, 0, 0, tzinfo=KARACHI)


class TestEveningShift:
    def test_closed_at_nine_the_next_morning(self):
        shift = make_shift("14:00", "22:00")
        assert compute_cutoff_at(at("2026-09-17T14:05:00"), shift) == at("2026-09-18T09:00:00")

    def test_shift_starting_exactly_at_noon_is_evening(self):
        shift = make_shift("12:00", "20:00")
        assert compute_cutoff_at(at("2026-09-17T12:00:00"), shift) == at("2026-09-18T09:00:00")

    def test_night_shift_evening_punch_closes_after_its_own_end(self):
        shift = make_shift("22:00", "06:00", overnight=True)
        assert compute_cutoff_at(at("2026-09-17T22:30:00"), shift) == at("2026-09-18T09:00:00")

    def test_after_midnight_punch_of_a_night_shift_closes_the_same_morning(self):
        shift = make_shift("22:00", "06:00", overnight=True)
        assert compute_cutoff_at(at("2026-09-18T00:30:00"), shift) == at("2026-09-18T09:00:00")

    def test_nine_pm_in_karachi(self):
        shift = make_shift("14:00", "22:00")
        punch_in = datetime(2026, 9, 17, 14, 0, tzinfo=KARACHI)
        assert compute_cutoff_at(punch_in, shift, zone=KARACHI) == datetime(2026, 9, 18, 9, 0, tzinfo=KARACHI)


class TestNoShift:
    def test_morning_check_in_closes_at_midnight(self):
        assert compute_cutoff_at(at("2026-09-17T08:00:00"), None) == at("2026-09-18T00:00:00")

    def test_afternoon_check_in_closes_at_nine_next_morning(self):
        assert compute_cutoff_at(at("2026-09-17T15:00:00"), None) == at("2026-09-18T09:00:00")


class TestPolicyIsConfigurable:
    def test_times_can_be_changed(self):
        policy = CutoffPolicy(evening_cutoff_time=time(10, 0), morning_shift_starts_before=time(13, 0))
        shift = make_shift("12:30", "20:30")  # morning under this policy
        assert compute_cutoff_at(at("2026-09-17T12:30:00"), shift, policy) == at("2026-09-18T00:00:00")
        late = make_shift("14:00", "22:00")
        assert compute_cutoff_at(at("2026-09-17T14:00:00"), late, policy) == at("2026-09-18T10:00:00")


class TestTheOriginalBug:
    def test_a_friday_punch_cannot_still_be_open_on_monday(self):
        monday_morning = at("2026-09-21T09:00:00")
        for shift in (None, make_shift("09:00", "18:00"), make_shift("14:00", "22:00"),
                      make_shift("22:00", "06:00", overnight=True)):
            assert compute_cutoff_at(at("2026-09-18T09:00:00"), shift) < monday_morning

    def test_the_cutoff_is_always_after_the_punch_in(self):
        for hour in range(24):
            punch_in = at(f"2026-09-17T{hour:02d}:15:00")
            for shift in (None, make_shift("09:00", "18:00"), make_shift("22:00", "06:00", overnight=True)):
                assert compute_cutoff_at(punch_in, shift) > punch_in
