"""
Reports. Monthly attendance summary (JSON for the page, CSV for download).

`reports.view` opens the page; the CSV also needs `reports.export`.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.permissions.dependencies import get_tenant_id, require_permission
from app.services.attendance_report import build_monthly_report

router = APIRouter(prefix="/reports", tags=["Reports"])

from app.api.v1.reports.hub import router as _hub_router  # noqa: E402
router.include_router(_hub_router)

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _csv_text(value) -> str:
    """Text that a spreadsheet shows as text (a name like '=1+1' must not run)."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


def _parse_month(month: str | None) -> tuple[int, int]:
    """'YYYY-MM' -> (year, month); empty means the current month."""
    if not month:
        today = date.today()
        return today.year, today.month
    try:
        year_s, month_s = month.split("-")
        year, mon = int(year_s), int(month_s)
        date(year, mon, 1)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="month must look like 2026-10")
    return year, mon


@router.get("/attendance/monthly", summary="Monthly attendance summary, one row per employee")
async def monthly_attendance(
    month: str | None = Query(None, description="YYYY-MM, defaults to this month"),
    department_id: UUID | None = Query(None),
    branch_id: UUID | None = Query(None),
    search: str | None = Query(None, max_length=100),
    current_user: User = Depends(require_permission("reports.view")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    year, mon = _parse_month(month)
    return await build_monthly_report(
        db, tenant_id, year, mon,
        department_id=department_id, branch_id=branch_id, search=search,
    )


@router.get("/attendance/monthly/csv", summary="Download the monthly attendance summary as CSV")
async def monthly_attendance_csv(
    month: str | None = Query(None, description="YYYY-MM, defaults to this month"),
    department_id: UUID | None = Query(None),
    branch_id: UUID | None = Query(None),
    search: str | None = Query(None, max_length=100),
    current_user: User = Depends(require_permission("reports.export")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    year, mon = _parse_month(month)
    report = await build_monthly_report(
        db, tenant_id, year, mon,
        department_id=department_id, branch_id=branch_id, search=search,
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Employee Code", "Employee Name", "Department", "Present", "Late", "Half Day",
        "Missed Punch", "Absent", "On Leave", "Holiday", "Weekly Off", "Pending",
        "Days Worked", "Working Days", "Attendance %", "Worked Hours",
        "Late Minutes", "Overtime Hours",
    ])
    for r in report["items"]:
        writer.writerow([
            _csv_text(r["employee_code"]), _csv_text(r["employee_name"]),
            _csv_text(r["department_name"]), r["present"], r["late"], r["half_day"],
            r["missed_punch"], r["absent"], r["on_leave"], r["holiday"], r["weekly_off"],
            r["pending"], r["days_worked"], r["working_days"],
            "" if r["attendance_pct"] is None else r["attendance_pct"],
            r["worked_hours"], r["late_minutes"], r["overtime_hours"],
        ])
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=attendance-{year}-{mon:02d}.csv"},
    )
