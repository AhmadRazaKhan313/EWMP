"""Shifts API endpoints."""
import uuid
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models.attendance import Shift
from app.models.user import User
from app.permissions.dependencies import get_current_user, get_tenant_id, require_permission

router = APIRouter(prefix="/shifts", tags=["Shifts"])


class ShiftCreate(BaseModel):
    name: str
    code: str
    start_time: str
    end_time: str
    work_days: list[str] | None = None
    is_overnight: bool = False
    late_grace_minutes: int = 10
    break_duration_minutes: int = 60
    color: str = "#3b82f6"


class ShiftUpdate(BaseModel):
    name: str | None = None
    color: str | None = None
    is_active: bool | None = None
    late_grace_minutes: int | None = None


class AssignShiftRequest(BaseModel):
    employee_id: uuid.UUID


@router.get("")
async def list_shifts(
    current_user: User = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    items = (await db.execute(select(Shift).where(Shift.tenant_id == tenant_id, Shift.is_deleted == False).order_by(Shift.name))).scalars().all()
    return {"items": [{"id": str(s.id), "name": s.name, "code": s.code, "color": s.color,
                       "start_time": str(s.start_time), "end_time": str(s.end_time),
                       "is_overnight": s.is_overnight, "late_grace_minutes": s.late_grace_minutes,
                       "break_duration_minutes": s.break_duration_minutes,
                       "work_days": s.work_days, "weekly_hours": str(s.weekly_hours),
                       "is_active": s.is_active} for s in items], "total": len(items)}

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_shift(
    body: ShiftCreate,
    current_user: User = Depends(require_permission("attendance.view")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from datetime import time as dtime
    h, m = map(int, body.start_time.split(":"))
    st = dtime(h, m)
    h2, m2 = map(int, body.end_time.split(":"))
    et = dtime(h2, m2)
    shift = Shift(tenant_id=tenant_id, name=body.name, code=body.code, start_time=st, end_time=et,
                  work_days=body.work_days or ["mon","tue","wed","thu","fri"],
                  is_overnight=body.is_overnight, late_grace_minutes=body.late_grace_minutes,
                  break_duration_minutes=body.break_duration_minutes, color=body.color, is_active=True)
    db.add(shift)
    await db.flush()
    return {"id": str(shift.id), "name": shift.name, "created": True}

@router.patch("/{shift_id}")
async def update_shift(
    shift_id: uuid.UUID,
    body: ShiftUpdate,
    current_user: User = Depends(require_permission("attendance.view")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(Shift).where(Shift.id == shift_id, Shift.tenant_id == tenant_id))
    shift = result.scalar_one_or_none()
    if not shift:
        raise NotFoundError("Shift not found")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(shift, field, val)
    await db.flush()
    return {"id": str(shift.id), "updated": True}

@router.post("/{shift_id}/assign", summary="Assign this shift as an employee's default shift")
async def assign_shift(
    shift_id: uuid.UUID,
    body: AssignShiftRequest,
    current_user: User = Depends(require_permission("attendance.regularize")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.models.employee import Employee

    shift = (
        await db.execute(select(Shift).where(Shift.id == shift_id, Shift.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if not shift:
        raise NotFoundError("Shift not found")

    employee = (
        await db.execute(
            select(Employee).where(Employee.id == body.employee_id, Employee.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if not employee:
        raise NotFoundError("Employee not found")

    employee.default_shift_id = shift_id
    await db.flush()
    return {"employee_id": str(body.employee_id), "shift_id": str(shift_id), "assigned": True}


@router.delete("/{shift_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shift(
    shift_id: uuid.UUID,
    current_user: User = Depends(require_permission("attendance.view")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(select(Shift).where(Shift.id == shift_id, Shift.tenant_id == tenant_id))
    shift = result.scalar_one_or_none()
    if not shift:
        raise NotFoundError("Shift not found")
    shift.soft_delete()
    await db.flush()
