"""
GET /dashboard/stats — the six numbers behind the Dashboard page's stat
cards. See app.services.dashboard for what each number means and why this
is one aggregate endpoint instead of six.

Open to any authenticated user (like /ai/chat) rather than gated by a
specific permission: it's the landing page every org member sees, self-
service employees included, and returns only aggregate counts — no
per-employee or otherwise sensitive rows.
"""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.permissions.dependencies import get_current_user, get_tenant_id
from app.core.exceptions import PermissionDeniedError
from app.models.employee import Employee
from app.services.dashboard import get_absent_today, get_dashboard_stats, get_weekly_hours
from app.services.tenant_guard import require_employee

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/stats", summary="Aggregate counts for the dashboard stat cards")
async def dashboard_stats(
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await get_dashboard_stats(db, tenant_id)

@router.get("/absent", summary="Employees absent / not yet checked in today")
async def dashboard_absent(
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Names of other people -> needs the org-wide attendance view.
    if not current_user.has_permission("attendance.view"):
        raise PermissionDeniedError("attendance.view is required")
    return await get_absent_today(db, tenant_id)


@router.get("/weekly-hours", summary="Hours worked per day (Mon-Sun) for one week")
async def dashboard_weekly_hours(
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    scope: Annotated[str, Query(pattern="^(me|team)$")] = "me",
    week_start: Annotated[date | None, Query()] = None,
    employee_id: Annotated[UUID | None, Query()] = None,
) -> dict:
    """scope=me (default): the caller's own week. scope=team or an explicit
    employee_id needs attendance.view."""
    org_wide = scope == "team" or employee_id is not None
    if org_wide and not current_user.has_permission("attendance.view"):
        raise PermissionDeniedError("attendance.view is required")
    target_id = None
    if scope == "me" or employee_id is not None:
        if employee_id is not None:
            await require_employee(db, tenant_id, employee_id)
            target_id = employee_id
        else:
            target_id = (
                await db.execute(
                    select(Employee.id).where(
                        Employee.user_id == current_user.id,
                        Employee.tenant_id == tenant_id,
                        Employee.is_deleted == False,  # noqa: E712
                    )
                )
            ).scalar_one_or_none()
            if target_id is None:  # a user with no employee profile has no hours
                return await get_weekly_hours(db, tenant_id, employee_id=UUID(int=0), week_start=week_start)
    return await get_weekly_hours(db, tenant_id, employee_id=target_id, week_start=week_start)
