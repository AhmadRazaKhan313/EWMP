"""
Tools the AI Assistant can call to answer questions with real tenant data.

Before this module existed, /ai/chat was a plain LLM wrapper — the system
prompt literally said "note that you would normally query the live
database" because it never did. These functions are what closes that gap:
each one runs a real, tenant-scoped query and returns a small JSON-able
summary the model can reason over and cite numbers from.

Kept intentionally read-only and aggregate-only (counts/averages, not raw
employee rows) — the assistant should never be able to dump a full PII
table through a tool call.
"""

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance import AttendanceRecord, AttendanceStatus, LeaveRequest, LeaveRequestStatus
from app.models.employee import Employee, EmploymentStatus
from app.models.organization_structure import Department
from app.models.payroll import PayrollRun


async def get_headcount_summary(db: AsyncSession, tenant_id: UUID) -> dict:
    """Total headcount, by employment status, and by department."""
    status_rows = (
        await db.execute(
            select(Employee.employment_status, func.count())
            .where(Employee.tenant_id == tenant_id, Employee.is_deleted == False)  # noqa: E712
            .group_by(Employee.employment_status)
        )
    ).all()
    by_status = {s.value: c for s, c in status_rows}

    dept_rows = (
        await db.execute(
            select(Department.name, func.count(Employee.id))
            .join(Employee, Employee.department_id == Department.id)
            .where(Employee.tenant_id == tenant_id, Employee.is_deleted == False)  # noqa: E712
            .group_by(Department.name)
        )
    ).all()
    by_department = {name: c for name, c in dept_rows}

    return {
        "total_headcount": sum(by_status.values()),
        "by_employment_status": by_status,
        "by_department": by_department,
    }


async def get_attrition_summary(db: AsyncSession, tenant_id: UUID, days: int = 90) -> dict:
    """Offboarded employees in the trailing window — the closest thing to
    attrition we can compute without a dedicated termination-reason field."""
    cutoff = date.today() - timedelta(days=days)
    terminated = (
        await db.execute(
            select(func.count()).where(
                Employee.tenant_id == tenant_id,
                Employee.employment_status == EmploymentStatus.TERMINATED,
                Employee.date_of_leaving.is_not(None),
                Employee.date_of_leaving >= cutoff,
            )
        )
    ).scalar_one()
    total_active_ish = (
        await db.execute(
            select(func.count()).where(
                Employee.tenant_id == tenant_id, Employee.is_deleted == False  # noqa: E712
            )
        )
    ).scalar_one()
    rate = round((terminated / total_active_ish) * 100, 1) if total_active_ish else 0.0
    return {
        "window_days": days,
        "employees_offboarded": terminated,
        "approx_attrition_rate_percent": rate,
    }


async def get_attendance_summary(db: AsyncSession, tenant_id: UUID, days: int = 30) -> dict:
    """Present/late/absent rates over the trailing window."""
    cutoff = date.today() - timedelta(days=days)
    rows = (
        await db.execute(
            select(AttendanceRecord.status, func.count())
            .where(
                AttendanceRecord.tenant_id == tenant_id,
                AttendanceRecord.date >= cutoff,
            )
            .group_by(AttendanceRecord.status)
        )
    ).all()
    by_status = {s.value: c for s, c in rows}
    total = sum(by_status.values())
    late_count = by_status.get(AttendanceStatus.LATE.value, 0)
    return {
        "window_days": days,
        "total_records": total,
        "by_status": by_status,
        "late_rate_percent": round((late_count / total) * 100, 1) if total else 0.0,
    }


async def get_leave_summary(db: AsyncSession, tenant_id: UUID) -> dict:
    """Pending leave requests and how many employees are on approved leave right now."""
    pending = (
        await db.execute(
            select(func.count()).where(
                LeaveRequest.tenant_id == tenant_id,
                LeaveRequest.status == LeaveRequestStatus.PENDING,
            )
        )
    ).scalar_one()
    today = date.today()
    on_leave_today = (
        await db.execute(
            select(func.count()).where(
                LeaveRequest.tenant_id == tenant_id,
                LeaveRequest.status == LeaveRequestStatus.APPROVED,
                LeaveRequest.start_date <= today,
                LeaveRequest.end_date >= today,
            )
        )
    ).scalar_one()
    return {"pending_requests": pending, "employees_on_leave_today": on_leave_today}


async def get_payroll_summary(db: AsyncSession, tenant_id: UUID) -> dict:
    """Totals from the most recently generated payroll run."""
    run = (
        await db.execute(
            select(PayrollRun)
            .where(PayrollRun.tenant_id == tenant_id)
            .order_by(PayrollRun.period_end.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if run is None:
        return {"has_data": False, "message": "No payroll runs generated yet"}
    return {
        "has_data": True,
        "run_name": run.name,
        "period_start": str(run.period_start),
        "period_end": str(run.period_end),
        "status": run.status.value,
        "employee_count": run.employee_count,
        "total_gross": str(run.total_gross) if run.total_gross is not None else None,
        "total_deductions": str(run.total_deductions) if run.total_deductions is not None else None,
        "total_net": str(run.total_net) if run.total_net is not None else None,
        "currency": run.currency,
    }


# ── Tool registry ────────────────────────────────────────────────────────────
# name -> (description, parameters schema, function). Shared shape so both
# the Anthropic and OpenAI branches in chat.py can build their own
# provider-specific tool payload from the same source of truth.
TOOL_REGISTRY: dict[str, dict] = {
    "get_headcount_summary": {
        "description": "Get total employee headcount, broken down by employment status and department.",
        "parameters": {"type": "object", "properties": {}},
        "fn": get_headcount_summary,
    },
    "get_attrition_summary": {
        "description": "Get how many employees were offboarded recently and the approximate attrition rate.",
        "parameters": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Trailing window size in days, default 90"},
            },
        },
        "fn": get_attrition_summary,
    },
    "get_attendance_summary": {
        "description": "Get present/late/absent attendance rates over a trailing window.",
        "parameters": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Trailing window size in days, default 30"},
            },
        },
        "fn": get_attendance_summary,
    },
    "get_leave_summary": {
        "description": "Get the count of pending leave requests and how many employees are on approved leave today.",
        "parameters": {"type": "object", "properties": {}},
        "fn": get_leave_summary,
    },
    "get_payroll_summary": {
        "description": "Get totals (gross, deductions, net, employee count) from the most recent payroll run.",
        "parameters": {"type": "object", "properties": {}},
        "fn": get_payroll_summary,
    },
}


async def execute_tool(name: str, arguments: dict, db: AsyncSession, tenant_id: UUID) -> dict:
    """Dispatch a tool call by name. Returns a plain dict, JSON-serializable."""
    tool = TOOL_REGISTRY.get(name)
    if tool is None:
        return {"error": f"Unknown tool: {name}"}
    fn = tool["fn"]
    # Every tool function takes (db, tenant_id, **rest)
    return await fn(db, tenant_id, **{k: v for k, v in arguments.items() if k != "tenant_id"})
