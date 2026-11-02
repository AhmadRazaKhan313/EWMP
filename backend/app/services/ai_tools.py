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

import logging
from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezones import local_today, org_zone

from app.models.attendance import AttendanceRecord, AttendanceStatus, LeaveRequest, LeaveRequestStatus
from app.models.employee import Employee, EmploymentStatus
from app.models.organization_structure import Department
from app.models.payroll import PayrollRun

logger = logging.getLogger(__name__)

MAX_LISTED_PEOPLE = 50  # a list tool never returns more names than this


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
    cutoff = local_today(await org_zone(db, tenant_id)) - timedelta(days=days)
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
    cutoff = local_today(await org_zone(db, tenant_id)) - timedelta(days=days)
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
    today = local_today(await org_zone(db, tenant_id))
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


async def get_absent_today(db: AsyncSession, tenant_id: UUID) -> dict:
    """Who is absent today, using the same rules as the daily attendance sheet
    (shifts, holidays and approved leave are respected). Names are capped."""
    from app.services.attendance_daily import DayStatus, build_daily_sheet, summarize

    day, rows = await build_daily_sheet(db, tenant_id)
    absent = [r for r in rows if r.status == DayStatus.ABSENT]
    counts = summarize(rows)
    return {
        "date": str(day),
        "absent_count": len(absent),
        "on_leave_count": counts.get("on_leave", 0),
        "absent": [
            {"name": r.employee_name, "department": r.department_name, "shift": r.shift_name}
            for r in absent[:MAX_LISTED_PEOPLE]
        ],
        "truncated": len(absent) > MAX_LISTED_PEOPLE,
    }


async def get_leave_cancellations(db: AsyncSession, tenant_id: UUID, days: int = 30) -> dict:
    """Leave requests cancelled by the employee or revoked by HR in the window."""
    cutoff = local_today(await org_zone(db, tenant_id)) - timedelta(days=days)
    rows = (
        await db.execute(
            select(LeaveRequest.status, func.count())
            .where(
                LeaveRequest.tenant_id == tenant_id,
                LeaveRequest.is_deleted == False,  # noqa: E712
                LeaveRequest.status.in_([LeaveRequestStatus.CANCELLED, LeaveRequestStatus.REVOKED]),
                LeaveRequest.start_date >= cutoff,
            )
            .group_by(LeaveRequest.status)
        )
    ).all()
    by_status = {s.value: c for s, c in rows}
    return {"window_days": days, "cancelled": by_status.get("cancelled", 0), "revoked": by_status.get("revoked", 0)}


async def get_break_summary(db: AsyncSession, tenant_id: UUID) -> dict:
    """Who is on a break right now and how many breaks were started today."""
    from datetime import UTC, datetime

    from app.models.employee import Employee as Emp
    from app.models.user import User
    from app.models.work_session import BreakRecord, WorkSession

    zone = await org_zone(db, tenant_id)
    today = local_today(zone)
    start_of_day = datetime.combine(today, datetime.min.time(), tzinfo=zone).astimezone(UTC)
    taken_today = (
        await db.execute(
            select(func.count()).where(
                BreakRecord.tenant_id == tenant_id, BreakRecord.started_at >= start_of_day,
            )
        )
    ).scalar_one()
    on_break = (
        await db.execute(
            select(User.first_name, User.last_name, BreakRecord.started_at)
            .join(WorkSession, WorkSession.id == BreakRecord.work_session_id)
            .join(Emp, Emp.id == WorkSession.employee_id)
            .join(User, User.id == Emp.user_id)
            .where(BreakRecord.tenant_id == tenant_id, BreakRecord.ended_at.is_(None))
            .order_by(BreakRecord.started_at)
            .limit(MAX_LISTED_PEOPLE)
        )
    ).all()
    return {
        "breaks_started_today": taken_today,
        "on_break_now_count": len(on_break),
        "on_break_now": [
            {"name": f"{f or ''} {l or ''}".strip(), "since": started.isoformat()} for f, l, started in on_break
        ],
    }


async def get_onboarding_summary(db: AsyncSession, tenant_id: UUID) -> dict:
    """Open onboarding/offboarding checklists, overdue tasks and upcoming joiners."""
    from app.services.onboarding import OnboardingService

    data = await OnboardingService(db, tenant_id).dashboard()
    return {
        **data["totals"],
        "upcoming_joiners": [
            {"name": c["employee"]["name"], "joining_in_days": c["days_until"], "progress_percent": c["progress"]["percent"]}
            for c in data["upcoming_joiners"][:10]
        ],
    }


# ── Tool registry ────────────────────────────────────────────────────────────
# name -> (description, parameters schema, function). Shared shape so both
# the Anthropic and OpenAI branches in chat.py can build their own
# provider-specific tool payload from the same source of truth.
TOOL_REGISTRY: dict[str, dict] = {
    "get_headcount_summary": {
        "permission": "employees.view",
        "description": "Get total employee headcount, broken down by employment status and department.",
        "parameters": {"type": "object", "properties": {}},
        "fn": get_headcount_summary,
    },
    "get_attrition_summary": {
        "permission": "employees.view",
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
        "permission": "attendance.view",
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
        "permission": "leave.view",
        "description": "Get the count of pending leave requests and how many employees are on approved leave today.",
        "parameters": {"type": "object", "properties": {}},
        "fn": get_leave_summary,
    },
    "get_payroll_summary": {
        "permission": "payroll.view",
        "description": "Get totals (gross, deductions, net, employee count) from the most recent payroll run.",
        "parameters": {"type": "object", "properties": {}},
        "fn": get_payroll_summary,
    },
    "get_absent_today": {
        "permission": "attendance.view",
        "description": "List who is absent today (name, department, shift) and how many are on leave. Respects shifts, holidays and approved leave.",
        "parameters": {"type": "object", "properties": {}},
        "fn": get_absent_today,
    },
    "get_leave_cancellations": {
        "permission": "leave.view",
        "description": "Get how many leave requests were cancelled by employees or revoked by HR in a trailing window.",
        "parameters": {"type": "object", "properties": {"days": {"type": "integer", "description": "Trailing window size in days, default 30"}}},
        "fn": get_leave_cancellations,
    },
    "get_break_summary": {
        "permission": "attendance.view",
        "description": "Get who is on a break right now and how many breaks were started today.",
        "parameters": {"type": "object", "properties": {}},
        "fn": get_break_summary,
    },
    "get_onboarding_summary": {
        "permission": "onboarding.view",
        "description": "Get open onboarding/offboarding checklists, overdue tasks, and upcoming joiners.",
        "parameters": {"type": "object", "properties": {}},
        "fn": get_onboarding_summary,
    },
}


def tools_for_user(user) -> frozenset[str]:
    """Names of the tools this user is allowed to use.

    Each tool returns org-wide aggregates that would otherwise sit behind an
    RBAC permission (e.g. payroll totals -> `payroll.view`). The assistant must
    never be a side door around that, so a tool is offered to the model — and
    executed — only if the caller holds the permission the same data needs
    elsewhere in the API. Owners / platform admins pass via `has_permission`.
    """
    return frozenset(
        name
        for name, spec in TOOL_REGISTRY.items()
        if user.has_permission(spec["permission"])
    )


_MAX_DAYS_WINDOW = 365


def _sanitize_arguments(arguments: dict) -> dict:
    """Model-supplied arguments are untrusted: only pass through what the tool
    functions accept, with `days` coerced to a sane integer window."""
    clean: dict = {}
    if "days" in arguments:
        try:
            days = int(arguments["days"])
        except (TypeError, ValueError):
            days = None
        if days is not None:
            clean["days"] = max(1, min(days, _MAX_DAYS_WINDOW))
    return clean


async def execute_tool(
    name: str,
    arguments: dict,
    db: AsyncSession,
    tenant_id: UUID,
    *,
    allowed_tools: frozenset[str],
) -> dict:
    """Dispatch a tool call by name. Returns a plain dict, JSON-serializable.

    `allowed_tools` is required (keyword-only) so no caller can forget the
    permission check. Even if the model asks for a tool it was never offered
    (hallucinated or prompt-injected), it is refused here.
    """
    tool = TOOL_REGISTRY.get(name)
    if tool is None:
        return {"error": f"Unknown tool: {name}"}
    if name not in allowed_tools:
        return {"error": "You do not have permission to access this data."}
    fn = tool["fn"]
    # Every tool function takes (db, tenant_id, **rest). A failing query must
    # reach the model as a readable error, not take the whole chat down.
    try:
        return await fn(db, tenant_id, **_sanitize_arguments(arguments or {}))
    except Exception:  # noqa: BLE001
        logger.exception("AI tool %s failed", name)
        return {"error": "That data could not be loaded right now. Please try again."}