"""Holidays API endpoints.

BACKGROUND: the `Holiday` model (app/models/attendance.py) and the
desktop/web clients' `GET /holidays` calls have existed for a while, but
no router ever exposed the model over the API — there was no
`app/api/v1/hrms/holidays.py` file and nothing registered in
`_register_routers()` in app/main.py. Every client-side call to
`GET /holidays` has therefore been hitting a 404 the whole time, which is
why the dashboard's "Upcoming holidays" widget and the leave-request cost
preview always rendered as empty rather than actually being wrong about
anything. This file is the missing piece; see app/main.py for the
one-line registration that goes with it.
"""
import datetime
import uuid
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.core.timezones import local_today, org_zone
from app.models.attendance import Holiday
from app.models.user import User
from app.permissions.dependencies import get_current_user, get_tenant_id, require_permission
from app.repositories.employee import EmployeeRepository

router = APIRouter(prefix="/holidays", tags=["Holidays"])


class HolidayCreate(BaseModel):
    name: str
    date: datetime.date
    description: str | None = None
    is_optional: bool = False
    # NULL = applies to every branch in the org.
    branch_id: uuid.UUID | None = None


class HolidayUpdate(BaseModel):
    name: str | None = None
    # Qualified as datetime.date, not bare `date`, because the field is
    # also named `date` — under Python 3.14's lazy annotation evaluation
    # (PEP 649), a bare `date | None` here resolves the name `date`
    # against the field itself instead of the datetime type and raises
    # TypeError: unsupported operand type(s) for |: 'NoneType' and
    # 'NoneType'. See https://github.com/pydantic/pydantic/issues/10854.
    date: datetime.date | None = None
    description: str | None = None
    is_optional: bool | None = None
    branch_id: uuid.UUID | None = None


def _serialize(h: Holiday) -> dict:
    return {
        "id": str(h.id),
        "name": h.name,
        "date": h.date.isoformat(),
        "description": h.description,
        "is_optional": h.is_optional,
        "branch_id": str(h.branch_id) if h.branch_id else None,
    }


@router.get("", summary="List the org's holiday calendar")
async def list_holidays(
    upcoming: bool = Query(False, description="Only holidays from today onward, soonest first"),
    year: int | None = Query(None, description="Restrict to a single calendar year"),
    current_user: User = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # No permission gate — this is the org's public holiday calendar, not
    # sensitive data, and every employee (self-service or otherwise) needs
    # it to plan leave. Same "open to any authenticated user" shape as
    # GET /shifts.
    filters = [Holiday.tenant_id == tenant_id, Holiday.is_deleted == False]  # noqa: E712

    # Branch-scoped: an org-wide holiday (branch_id IS NULL) always shows;
    # a branch-specific one only shows to employees at that branch. A user
    # with no employee profile (e.g. an admin account with no HR record)
    # sees only the org-wide ones, which is the safe default.
    own_employee = await EmployeeRepository(db, tenant_id).get_by_user_id(current_user.id)
    if own_employee is not None and own_employee.branch_id is not None:
        filters.append((Holiday.branch_id == None) | (Holiday.branch_id == own_employee.branch_id))  # noqa: E711
    else:
        filters.append(Holiday.branch_id == None)  # noqa: E711

    if upcoming:
        # "Upcoming" from the organisation's today, not the server's (audit H-1).
        filters.append(Holiday.date >= local_today(await org_zone(db, tenant_id)))
    if year:
        filters.append(Holiday.date >= datetime.date(year, 1, 1))
        filters.append(Holiday.date <= datetime.date(year, 12, 31))

    stmt = select(Holiday).where(*filters).order_by(Holiday.date.asc())
    items = (await db.execute(stmt)).scalars().all()
    return {"items": [_serialize(h) for h in items], "total": len(items)}


@router.post("", status_code=status.HTTP_201_CREATED, summary="Add a holiday to the calendar")
async def create_holiday(
    body: HolidayCreate,
    current_user: User = Depends(require_permission("holidays.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    holiday = Holiday(
        tenant_id=tenant_id,
        name=body.name,
        date=body.date,
        description=body.description,
        is_optional=body.is_optional,
        branch_id=body.branch_id,
    )
    db.add(holiday)
    await db.flush()
    return _serialize(holiday)


@router.patch("/{holiday_id}", summary="Edit a holiday")
async def update_holiday(
    holiday_id: uuid.UUID,
    body: HolidayUpdate,
    current_user: User = Depends(require_permission("holidays.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Holiday).where(Holiday.id == holiday_id, Holiday.tenant_id == tenant_id, Holiday.is_deleted == False)  # noqa: E712
    )
    holiday = result.scalar_one_or_none()
    if not holiday:
        raise NotFoundError("Holiday not found")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(holiday, field, val)
    await db.flush()
    return _serialize(holiday)


@router.delete("/{holiday_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a holiday")
async def delete_holiday(
    holiday_id: uuid.UUID,
    current_user: User = Depends(require_permission("holidays.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(Holiday).where(Holiday.id == holiday_id, Holiday.tenant_id == tenant_id, Holiday.is_deleted == False)  # noqa: E712
    )
    holiday = result.scalar_one_or_none()
    if not holiday:
        raise NotFoundError("Holiday not found")
    holiday.soft_delete()
    await db.flush()