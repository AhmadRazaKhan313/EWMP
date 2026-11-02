"""
Reports hub: one catalogue, one set of endpoints for every report.

  GET /reports/catalog                    reports this user may open
  GET /reports/hub/{key}                  the report as JSON (what the page shows)
  GET /reports/hub/{key}/csv              the same report as CSV
  GET /reports/hub/{key}/xlsx             the same report as a designed Excel sheet

Opening a report needs `reports.view` plus the report's own permission (payroll
reports also need `payroll.view`). Downloading also needs `reports.export`.
Adding a report = add a function that returns a ReportResult and one line in REPORTS.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import PermissionDeniedError
from app.models.organization import Organization
from app.models.user import User
from app.permissions.dependencies import get_current_user, get_tenant_id
from app.services import payroll_reports as pr
from app.services.report_engine import INT, MONEY, PERCENT, HOURS, Column, ReportResult, to_csv, to_xlsx

router = APIRouter(tags=["Reports"])


@dataclass(frozen=True)
class Filters:
    year: int
    month: int
    department_id: uuid.UUID | None
    branch_id: uuid.UUID | None
    search: str | None


@dataclass(frozen=True)
class ReportDef:
    key: str
    title: str
    category: str
    description: str
    run: Callable[[AsyncSession, uuid.UUID, Filters], Awaitable[ReportResult]]
    permissions: tuple[str, ...] = ("reports.view",)
    uses_search: bool = False


async def _attendance_monthly(db, tenant_id, f: Filters) -> ReportResult:
    from app.services.attendance_report import build_monthly_report
    data = await build_monthly_report(db, tenant_id, f.year, f.month, department_id=f.department_id,
                                      branch_id=f.branch_id, search=f.search)
    cols = [Column("employee_code", "Code"), Column("employee_name", "Employee"), Column("department_name", "Department")]
    cols += [Column(k, label, INT) for k, label in (
        ("present", "Present"), ("late", "Late"), ("half_day", "Half day"), ("missed_punch", "Missed punch"),
        ("absent", "Absent"), ("on_leave", "Leave"), ("holiday", "Holiday"), ("weekly_off", "Weekly off"),
        ("days_worked", "Days worked"), ("working_days", "Working days"))]
    cols += [Column("attendance_pct", "Attendance %", PERCENT), Column("worked_hours", "Worked hours", HOURS),
             Column("late_minutes", "Late minutes", INT), Column("overtime_hours", "Overtime hours", HOURS)]
    t = data["totals"]
    return ReportResult(
        key="attendance-monthly", title="Monthly Attendance Summary",
        subtitle=f"{pr.month_label(f.year, f.month)} · counted through {data['period']['counted_through'] or 'n/a'}",
        columns=cols, rows=data["items"],
        summary=[{"label": "Employees", "value": t["employees"], "type": INT},
                 {"label": "Attendance", "value": t["attendance_pct"], "type": PERCENT},
                 {"label": "Absent days", "value": t["absent"], "type": INT},
                 {"label": "Leave days", "value": t["on_leave"], "type": INT}],
    )


def _payroll(fn):
    async def run(db, tenant_id, f: Filters):
        return await fn(db, tenant_id, f.year, f.month, department_id=f.department_id, branch_id=f.branch_id)
    return run


async def _register(db, tenant_id, f: Filters):
    return await pr.payroll_register(db, tenant_id, f.year, f.month, department_id=f.department_id,
                                     branch_id=f.branch_id, search=f.search)


async def _expenses(db, tenant_id, f: Filters):
    return await pr.payroll_expenses(db, tenant_id, f.year, f.month, department_id=f.department_id,
                                     branch_id=f.branch_id)


REPORTS: dict[str, ReportDef] = {r.key: r for r in [
    ReportDef("payroll-expenses", "Monthly Payroll Expenses", "Payroll",
              "Salary cost, reimbursements and total paid out, month by month.", _expenses,
              ("reports.view", "payroll.view")),
    ReportDef("payroll-department-cost", "Payroll Cost by Department", "Payroll",
              "What each department costs for the month.", _payroll(pr.payroll_department_cost),
              ("reports.view", "payroll.view")),
    ReportDef("payroll-register", "Payroll Register", "Payroll",
              "One row per employee: earnings, tax, contributions, deductions and net.", _register,
              ("reports.view", "payroll.view"), uses_search=True),
    ReportDef("payroll-components", "Payroll Component Breakdown", "Payroll",
              "Totals for basic, allowances, tax, contributions and every other component.",
              _payroll(pr.payroll_components), ("reports.view", "payroll.view")),
    ReportDef("payroll-payment-status", "Payroll Payment Status", "Payroll",
              "Which payslips are paid, pending or failed, per payroll run.",
              _payroll(pr.payroll_payment_status), ("reports.view", "payroll.view")),
    ReportDef("attendance-monthly", "Monthly Attendance Summary", "Attendance",
              "Present, late, absent and leave days for every employee.", _attendance_monthly,
              ("reports.view",), uses_search=True),
]}


def _can(user: User, perms: tuple[str, ...]) -> bool:
    return bool(user.is_platform_admin) or all(user.has_permission(p) for p in perms)


def _require(user: User, perms: tuple[str, ...]) -> None:
    for p in perms:
        if not (user.is_platform_admin or user.has_permission(p)):
            raise PermissionDeniedError(f"Permission '{p}' is required for this action")


def _month(value: str | None) -> tuple[int, int]:
    if not value:
        t = date.today()
        return t.year, t.month
    try:
        y, m = value.split("-")
        date(int(y), int(m), 1)
        return int(y), int(m)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="month must look like 2026-10")


def _get(key: str) -> ReportDef:
    d = REPORTS.get(key)
    if d is None:
        raise HTTPException(status_code=404, detail="Unknown report")
    return d


@router.get("/catalog", summary="Reports the current user can open")
async def catalog(current_user: User = Depends(get_current_user)) -> dict:
    _require(current_user, ("reports.view",))
    items = [
        {"key": d.key, "title": d.title, "category": d.category, "description": d.description,
         "uses_search": d.uses_search}
        for d in REPORTS.values() if _can(current_user, d.permissions)
    ]
    return {"items": items, "can_export": _can(current_user, ("reports.export",))}


async def _build(key, month, department_id, branch_id, search, user, tenant_id, db, *, export: bool):
    d = _get(key)
    _require(user, d.permissions + (("reports.export",) if export else ()))
    y, m = _month(month)
    return await d.run(db, tenant_id, Filters(y, m, department_id, branch_id, (search or "").strip() or None))


@router.get("/hub/{key}", summary="Run a report (JSON)")
async def run_report(
    key: str, month: str | None = Query(None), department_id: uuid.UUID | None = Query(None),
    branch_id: uuid.UUID | None = Query(None), search: str | None = Query(None, max_length=100),
    current_user: User = Depends(get_current_user), tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return (await _build(key, month, department_id, branch_id, search, current_user, tenant_id, db, export=False)).as_dict()


@router.get("/hub/{key}/csv", summary="Download a report as CSV")
async def report_csv(
    key: str, month: str | None = Query(None), department_id: uuid.UUID | None = Query(None),
    branch_id: uuid.UUID | None = Query(None), search: str | None = Query(None, max_length=100),
    current_user: User = Depends(get_current_user), tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    rep = await _build(key, month, department_id, branch_id, search, current_user, tenant_id, db, export=True)
    return Response(to_csv(rep), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={_filename(key, month)}.csv"})


@router.get("/hub/{key}/xlsx", summary="Download a report as an Excel sheet")
async def report_xlsx(
    key: str, month: str | None = Query(None), department_id: uuid.UUID | None = Query(None),
    branch_id: uuid.UUID | None = Query(None), search: str | None = Query(None, max_length=100),
    current_user: User = Depends(get_current_user), tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    rep = await _build(key, month, department_id, branch_id, search, current_user, tenant_id, db, export=True)
    company = (await db.execute(select(Organization.name).where(Organization.id == tenant_id))).scalar() or ""
    return Response(
        to_xlsx(rep, company=company),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={_filename(key, month)}.xlsx"},
    )


def _filename(key: str, month: str | None) -> str:
    y, m = _month(month)
    return f"{key}-{y}-{m:02d}"
