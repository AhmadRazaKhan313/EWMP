"""E-04: pay items can be recurring or one-time and have effective dates."""
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.employee import CompensationItemIn, _normalise
from app.services.payroll_pay_items import applies_in_period, resolve_pay_items

JUNE = (date(2026, 6, 1), date(2026, 6, 30))


def item(**kw):
    return {"id": kw.pop("id", "abc"), "name": "Medical", "kind": "earning", "calculation": "fixed",
            "amount": "1000", "percentage": "0", "is_taxable": True, **kw}


def names(items, period=JUNE):
    earnings, deductions = resolve_pay_items(items, Decimal("50000"), *period)
    return [e.name for e in earnings], [d.name for d in deductions]


def test_items_without_dates_keep_working_exactly_as_before():
    assert applies_in_period(item(), *JUNE)
    assert names([item()]) == (["Medical"], [])
    # callers that pass no period are unaffected
    assert resolve_pay_items([item()], Decimal("50000"))[0][0].amount == Decimal("1000.00")


@pytest.mark.parametrize("start,end,expected", [
    ("2026-06-15", None, True),    # starts mid-period -> counts that period
    ("2026-07-01", None, False),   # starts after the period
    (None, "2026-05-31", False),   # ended before the period
    (None, "2026-06-01", True),    # ends on the first day -> still counts
    ("2026-01-01", "2026-12-31", True),
    ("2026-07-01", "2026-12-31", False),
])
def test_recurring_window(start, end, expected):
    assert applies_in_period(item(effective_from=start, effective_to=end), *JUNE) is expected


@pytest.mark.parametrize("when,expected", [
    ("2026-06-01", True), ("2026-06-30", True), ("2026-05-31", False), ("2026-07-01", False), (None, False),
])
def test_one_time_applies_only_in_its_own_period(when, expected):
    assert applies_in_period(item(frequency="one_time", effective_from=when), *JUNE) is expected


def test_deductions_follow_the_same_rules_and_garbage_dates_do_not_crash():
    rows = [item(name="Loan", kind="deduction", effective_to="2026-05-01"),
            item(name="Advance", kind="deduction", frequency="one_time", effective_from="2026-06-10"),
            item(name="Odd", effective_from="not-a-date")]
    assert names(rows) == (["Odd"], ["Advance"])


def test_schema_rules():
    ok = CompensationItemIn(name="Bonus", kind="earning", amount=500, frequency="one_time", effective_from="2026-06-10", effective_to="2030-01-01")
    assert ok.effective_to is None  # a one-time item has no end
    with pytest.raises(ValidationError):
        CompensationItemIn(name="Bonus", kind="earning", amount=500, frequency="one_time")
    with pytest.raises(ValidationError):
        CompensationItemIn(name="Fuel", kind="earning", amount=5, effective_from="2026-06-10", effective_to="2026-06-09")
    stored = _normalise(CompensationItemIn, [{"name": "Fuel", "kind": "earning", "amount": 5, "effective_from": "2026-06-01"}], 50, "pay items")[0]
    assert stored["effective_from"] == "2026-06-01" and stored["frequency"] == "recurring" and stored["effective_to"] is None
    # an old stored row (no new keys) validates and round-trips
    old = _normalise(CompensationItemIn, [{"name": "Old", "kind": "deduction", "amount": 5}], 50, "pay items")[0]
    assert old["frequency"] == "recurring" and old["effective_from"] is None
