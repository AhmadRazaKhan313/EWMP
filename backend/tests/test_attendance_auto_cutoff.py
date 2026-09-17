"""
Auto-cutoff deadline logic.

These are pure-function tests — no database — because the cutoff maths is
where the multi-shift and overnight edge cases live, and those are worth
pinning down independently of the scheduler that applies them.
"""

from datetime import UTC, datetime, time

import pytest

from app.models.attendance import Shift
from app.services.attendance_punches import (
    CutoffPolicy,
    _resolve_shift_end,
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


class TestDayShift:
    def test_cutoff_is_shift_end_plus_grace(self):
        shift = make_shift("09:00", "18:00")
        # Punched in on time; 4h grace after an 18:00 end → 22:00.
        assert compute_cutoff_at(at("2026-09-17T09:05:00"), shift) == at("2026-09-17T22:00:00")

    def test_grace_is_configurable(self):
        shift = make_shift("09:00", "18:00")
        policy = CutoffPolicy(grace_hours_after_shift_end=2)
        assert compute_cutoff_at(at("2026-09-17T09:00:00"), shift, policy) == at(
            "2026-09-17T20:00:00"
        )

    def test_early_arrival_is_capped_from_arrival_not_from_shift_end(self):
        """
        Someone who arrives at 06:30 for a 09:00 shift is NOT given until
        22:00 (shift end + grace). The 14h cap measured from their actual
        punch-in closes them at 20:30 first, and the earlier of the two
        always wins.

        This is the right answer even though it is the less obvious one:
        by 20:30 they have been punched in for fourteen hours, and no
        shift configuration should be able to authorise more than that.
        """
        shift = make_shift("09:00", "18:00")
        assert compute_cutoff_at(at("2026-09-17T06:30:00"), shift) == at("2026-09-17T20:30:00")

    def test_shift_deadline_applies_once_arrival_is_late_enough(self):
        """The mirror of the above — arrive at 08:00 and the 22:00 shift
        deadline is earlier than the 22:00 cap, so they coincide; arrive
        any later and the shift deadline governs."""
        shift = make_shift("09:00", "18:00")
        assert compute_cutoff_at(at("2026-09-17T10:00:00"), shift) == at("2026-09-17T22:00:00")


class TestOvernightShift:
    def test_evening_punch_ends_next_morning(self):
        shift = make_shift("22:00", "06:00", overnight=True)
        # In at 22:30 on the 17th → shift ends 06:00 on the 18th, +4h grace.
        assert compute_cutoff_at(at("2026-09-17T22:30:00"), shift) == at("2026-09-18T10:00:00")

    def test_after_midnight_punch_ends_the_same_morning_not_a_day_later(self):
        """
        The case that makes overnight shifts hard: someone punching in at
        00:30 is in the SECOND half of a 22:00-06:00 shift. Their shift
        ends at 06:00 that same morning, four and a half hours later — not
        at 06:00 tomorrow, which would give them a 29-hour window.
        """
        shift = make_shift("22:00", "06:00", overnight=True)
        assert _resolve_shift_end(at("2026-09-18T00:30:00"), shift) == at("2026-09-18T06:00:00")
        assert compute_cutoff_at(at("2026-09-18T00:30:00"), shift) == at("2026-09-18T10:00:00")


class TestHardCap:
    def test_no_shift_falls_back_to_the_hard_cap(self):
        """Flexible-hours employees have no scheduled end to measure from."""
        assert compute_cutoff_at(at("2026-09-17T09:00:00"), None) == at("2026-09-17T23:00:00")

    def test_hard_cap_wins_when_a_shift_would_allow_longer(self):
        """
        A misconfigured shift must not be able to hold a punch open
        indefinitely. A 06:00-23:59 shift plus 4h grace would run to
        03:59 the next day; the 14h cap from a 06:00 punch-in closes it
        at 20:00 instead.
        """
        shift = make_shift("06:00", "23:59")
        cutoff = compute_cutoff_at(at("2026-09-17T06:00:00"), shift)
        assert cutoff == at("2026-09-17T20:00:00")

    def test_shift_deadline_wins_when_it_is_earlier(self):
        shift = make_shift("09:00", "17:00")
        # 17:00 + 4h = 21:00, which is earlier than 09:00 + 14h = 23:00.
        assert compute_cutoff_at(at("2026-09-17T09:00:00"), shift) == at("2026-09-17T21:00:00")

    def test_cap_is_configurable(self):
        policy = CutoffPolicy(hard_cap_hours=10)
        assert compute_cutoff_at(at("2026-09-17T09:00:00"), None, policy) == at(
            "2026-09-17T19:00:00"
        )


class TestLateArrival:
    def test_punching_in_after_the_shift_already_ended_rolls_forward(self):
        """
        A 09:00-18:00 employee punching in at 19:00 (late evening
        catch-up) has no meaningful "end today" left. Rolling the end to
        the next day's 18:00 would give them 23 hours, so the hard cap
        takes over and closes them at 09:00 the next morning.
        """
        shift = make_shift("09:00", "18:00")
        assert compute_cutoff_at(at("2026-09-17T19:00:00"), shift) == at("2026-09-18T09:00:00")


class TestTheOriginalBug:
    def test_a_friday_evening_punch_cannot_still_be_open_on_monday(self):
        """
        The reported symptom: forget to check out on Friday, come back
        Monday to a timer reading 72 hours. Under any policy, a Friday
        punch must have a deadline inside the weekend.
        """
        shift = make_shift("09:00", "18:00")
        friday_punch = at("2026-09-18T09:00:00")
        monday_morning = at("2026-09-21T09:00:00")
        assert compute_cutoff_at(friday_punch, shift) < monday_morning

    @pytest.mark.parametrize(
        "shift",
        [
            None,
            make_shift("09:00", "18:00"),
            make_shift("22:00", "06:00", overnight=True),
            make_shift("00:00", "23:59"),
        ],
    )
    def test_no_shift_configuration_allows_a_punch_past_the_hard_cap(self, shift):
        """The cap is the invariant — it must hold for every shift shape."""
        punch_in = at("2026-09-17T08:00:00")
        assert compute_cutoff_at(punch_in, shift) <= punch_in.replace(hour=22)
