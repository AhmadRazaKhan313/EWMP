"""
Monthly attendance report (app.services.attendance_report + /reports/attendance/monthly).

The per-day sheet is faked (monkeypatched), so these need NO database. They check
the adding-up: which statuses count as worked / absent / pending, that days after
today are not walked, the percentage, and the CSV (header, formula-safe cells).

Run:  cd backend && pytest tests/test_attendance_monthly_report.py -v
"""

import asyncio
import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.api.v1.reports.router as router_mod
import app.services.attendance_report as rep
from app.services.attendance_daily import DayStatus, SheetRow

TENANT = uuid.uuid4()
ALI, SARA = uuid.uuid4(), uuid.uuid4()
NOW = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)


def _row(emp_id, name, status, *, minutes=None, late=None, ot=None, code="E1"):
    return SheetRow(
        employee_id=emp_id, employee_code=code, employee_name=name,
        department_name="Ops", shift_name=None, shift_start=None, shift_end=None,
        status=status, check_in=None, check_out=None, total_minutes=minutes,
        late_minutes=late, overtime_minutes=ot, record_id=None,
        is_regularized=False, detail=None,
    )


@pytest.fixture
def fake_days(monkeypatch):
    """status plan per day number -> {emp: status}; records which days were asked for."""
    calls = []
    plan = {}

    async def fake_sheet(db, tenant_id, day, **kw):
        calls.append(day)
        rows = []
        for emp, name, code in ((ALI, "Ali Raza", "E1"), (SARA, "Sara Khan", "E2")):
            status, minutes, late, ot = plan.get((day.day, emp), (DayStatus.PRESENT, 480, 0, 0))
            rows.append(_row(emp, name, status, minutes=minutes, late=late, ot=ot, code=code))
        return day, rows

    async def fake_zone(db, tenant_id):
        return None

    monkeypatch.setattr(rep, "build_daily_sheet", fake_sheet)
    monkeypatch.setattr(rep, "org_zone", fake_zone)
    monkeypatch.setattr(rep, "local_today", lambda zone, now: date(2026, 10, 10))
    return SimpleNamespace(calls=calls, plan=plan)


def _run(coro):
    return asyncio.run(coro)


def test_only_days_up_to_today_are_walked(fake_days):
    out = _run(rep.build_monthly_report(None, TENANT, 2026, 10, now=NOW))
    assert fake_days.calls[0] == date(2026, 10, 1)
    assert fake_days.calls[-1] == date(2026, 10, 10)
    assert len(fake_days.calls) == 10
    assert out["period"]["counted_through"] == "2026-10-10"
    assert out["period"]["to"] == "2026-10-31"


def test_future_month_is_empty(fake_days):
    out = _run(rep.build_monthly_report(None, TENANT, 2026, 12, now=NOW))
    assert fake_days.calls == []
    assert out["items"] == []
    assert out["period"]["counted_through"] is None
    assert out["totals"]["attendance_pct"] is None


def test_past_month_is_walked_in_full(fake_days):
    _run(rep.build_monthly_report(None, TENANT, 2026, 9, now=NOW))
    assert len(fake_days.calls) == 30


def test_counts_and_percentage(fake_days):
    p = fake_days.plan
    p[1, ALI] = (DayStatus.LATE, 470, 20, 0)
    p[2, ALI] = (DayStatus.ABSENT, None, None, None)
    p[3, ALI] = (DayStatus.ON_LEAVE, None, None, None)
    p[4, ALI] = (DayStatus.HOLIDAY, None, None, None)
    p[5, ALI] = (DayStatus.WEEKLY_OFF, None, None, None)
    p[6, ALI] = (DayStatus.HALF_DAY, 240, 0, 0)
    p[7, ALI] = (DayStatus.MISSED_PUNCH, 0, 0, 0)
    p[8, ALI] = (DayStatus.WORK_FROM_HOME, 480, 0, 60)
    p[10, ALI] = (DayStatus.NOT_CHECKED_IN, None, None, None)

    out = _run(rep.build_monthly_report(None, TENANT, 2026, 10, now=NOW))
    ali = next(r for r in out["items"] if r["employee_name"] == "Ali Raza")

    assert ali["late"] == 1
    assert ali["absent"] == 1
    assert ali["on_leave"] == 1
    assert ali["holiday"] == 1
    assert ali["weekly_off"] == 1
    assert ali["half_day"] == 1
    assert ali["missed_punch"] == 1
    assert ali["pending"] == 1               # today, not decided: never absent
    assert ali["present"] == 2               # day 8 (work from home) + day 9 (default)
    assert ali["days_worked"] == 5           # 2 present + late + half day + missed punch
    assert ali["working_days"] == 7          # + 1 absent + 1 on leave
    assert ali["attendance_pct"] == 71.4
    assert ali["late_minutes"] == 20
    assert ali["overtime_hours"] == 1.0
    # worked minutes: 470 + 240 + 0 + 480 + 480 (day 9) = 1670 -> 27.8 h
    assert ali["worked_hours"] == round(1670 / 60, 1)


def test_items_sorted_by_name_and_totals(fake_days):
    out = _run(rep.build_monthly_report(None, TENANT, 2026, 10, now=NOW))
    assert [r["employee_name"] for r in out["items"]] == ["Ali Raza", "Sara Khan"]
    assert out["totals"]["employees"] == 2
    assert out["totals"]["present"] == 20          # 2 people x 10 days
    assert out["totals"]["attendance_pct"] == 100.0


def test_bad_month_is_rejected():
    for bad in ("2026-13", "abc", "2026", "2026-00"):
        with pytest.raises(HTTPException) as e:
            router_mod._parse_month(bad)
        assert e.value.status_code == 422
    assert router_mod._parse_month("2026-10") == (2026, 10)


def test_csv_header_rows_and_formula_safety(monkeypatch):
    async def fake_report(db, tenant_id, year, month, **kw):
        return {"items": [{
            "employee_code": "E1", "employee_name": "=HYPERLINK(\"x\")", "department_name": None,
            "present": 5, "late": 1, "half_day": 0, "missed_punch": 0, "absent": 2,
            "on_leave": 0, "holiday": 0, "weekly_off": 2, "pending": 0, "days_worked": 6,
            "working_days": 8, "attendance_pct": 75.0, "worked_hours": 40.5,
            "late_minutes": 20, "overtime_hours": 0.0,
        }]}

    monkeypatch.setattr(router_mod, "build_monthly_report", fake_report)

    async def body():
        resp = await router_mod.monthly_attendance_csv(
            month="2026-10", department_id=None, branch_id=None, search=None,
            current_user=None, tenant_id=TENANT, db=None,
        )
        chunks = [c async for c in resp.body_iterator]
        return resp, "".join(c if isinstance(c, str) else c.decode() for c in chunks)

    resp, text = _run(body())
    lines = text.strip().splitlines()
    assert lines[0].startswith("Employee Code,Employee Name,Department,Present,Late")
    assert "'=HYPERLINK" in lines[1]                       # formula neutralised
    assert "attendance-2026-10.csv" in resp.headers["content-disposition"]
    assert resp.media_type == "text/csv"
