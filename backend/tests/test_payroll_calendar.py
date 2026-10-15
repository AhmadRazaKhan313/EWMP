"""
Rules for how much of a pay period an employee is paid (audit C-7 / H-9) —
app.services.payroll_calendar.compute_payable_days, no database needed.

September 2026: 30 days, starts on a Tuesday; 22 Mon–Fri days, 26 Mon–Sat.
"""
from datetime import date
from decimal import Decimal

from app.models.payroll import WorkingDaysMethod
from app.services.payroll_calendar import DayInputs, compute_payable_days, work_weekdays_from

MON_FRI = {0, 1, 2, 3, 4}
MON_SAT = {0, 1, 2, 3, 4, 5}


def sept(method=WorkingDaysMethod.WORKING_DAYS, **kw) -> DayInputs:
    base = dict(period_start=date(2026, 9, 1), period_end=date(2026, 9, 30), method=method,
                fixed_divisor=None, work_weekdays=MON_FRI, holidays=set(), joined=date(2020, 1, 1), left=None)
    base.update(kw)
    return DayInputs(**base)


class TestNoCliff:
    def test_no_attendance_data_is_full_pay(self):
        assert compute_payable_days(sept()).factor == 1

    def test_some_attendance_data_is_still_full_pay(self):
        """THE C-7 bug: one attendance record used to mean ~1/22 of the salary."""
        r = compute_payable_days(sept())  # a PRESENT day adds nothing to deduct
        assert r.factor == 1


class TestWhatReducesPay:
    def test_a_recorded_absence_is_one_day(self):
        r = compute_payable_days(sept(absent={date(2026, 9, 7): Decimal("1")}))
        assert r.factor == Decimal(21) / Decimal(22)

    def test_a_half_day_is_half_a_day(self):
        r = compute_payable_days(sept(absent={date(2026, 9, 7): Decimal("0.5")}))
        assert r.factor == Decimal("21.5") / Decimal(22)

    def test_unpaid_leave_reduces_paid_leave_does_not(self):
        r = compute_payable_days(sept(unpaid_leave={date(2026, 9, 7): Decimal("1")},
                                      paid_leave={date(2026, 9, 8): Decimal("1")}))
        assert r.factor == Decimal(21) / Decimal(22)
        assert (r.unpaid_leave_days, r.paid_leave_days) == (1, 1)

    def test_a_day_is_never_docked_twice(self):
        d = date(2026, 9, 7)
        r = compute_payable_days(sept(absent={d: Decimal("1")}, unpaid_leave={d: Decimal("1")}))
        assert r.factor == Decimal(21) / Decimal(22)


class TestWhatNeverReducesPay:
    def test_a_public_holiday(self):
        r = compute_payable_days(sept(holidays={date(2026, 9, 14)}))
        assert r.factor == 1 and r.working_days == 21 and r.holiday_days == 1

    def test_unpaid_leave_over_a_weekend_only_counts_the_work_days(self):
        # Fri 11 → Mon 14: two work days, not four calendar days.
        leave = {date(2026, 9, d): Decimal("1") for d in (11, 12, 13, 14)}
        r = compute_payable_days(sept(unpaid_leave=leave))
        assert r.unpaid_leave_days == 2


class TestWorkWeekAndMethods:
    def test_a_six_day_work_week(self):
        r = compute_payable_days(sept(work_weekdays=MON_SAT, absent={date(2026, 9, 12): Decimal("1")}))  # a Saturday
        assert r.working_days == 26
        assert r.factor == Decimal(25) / Decimal(26)

    def test_calendar_days(self):
        r = compute_payable_days(sept(WorkingDaysMethod.CALENDAR_DAYS, absent={date(2026, 9, 7): Decimal("1")}))
        assert r.factor == Decimal(29) / Decimal(30)

    def test_fixed_divisor(self):
        r = compute_payable_days(sept(WorkingDaysMethod.FIXED_DIVISOR, fixed_divisor=Decimal(30),
                                      absent={date(2026, 9, 7): Decimal("1"), date(2026, 9, 8): Decimal("1")}))
        assert r.factor == Decimal(28) / Decimal(30)

    def test_org_work_week_setting(self):
        assert work_weekdays_from({"work_days": ["mon", "tue", "wed", "thu", "fri", "sat"]}) == MON_SAT
        assert work_weekdays_from({}) == MON_FRI
        assert work_weekdays_from(None) == MON_FRI


class TestJoinersAndLeavers:
    def test_joining_mid_month_calendar(self):
        r = compute_payable_days(sept(WorkingDaysMethod.CALENDAR_DAYS, joined=date(2026, 9, 16)))
        assert r.factor == Decimal(15) / Decimal(30) and r.not_employed_days == 15

    def test_leaving_mid_month_working_days(self):
        # Last day Fri 11 Sept: 9 work days (1–4, 7–11) out of 22.
        r = compute_payable_days(sept(left=date(2026, 9, 11)))
        assert r.factor == Decimal(9) / Decimal(22)

    def test_absence_after_leaving_is_not_double_counted(self):
        r = compute_payable_days(sept(left=date(2026, 9, 11), absent={date(2026, 9, 21): Decimal("1")}))
        assert r.factor == Decimal(9) / Decimal(22)
