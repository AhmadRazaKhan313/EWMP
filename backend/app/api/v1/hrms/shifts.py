"""Shifts API endpoints."""
import uuid
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
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


class SetShiftRosterRequest(BaseModel):
    """The complete list of employees who work this shift."""
    employee_ids: list[uuid.UUID] = Field(default_factory=list, max_length=2000)


@router.get("")
async def list_shifts(
    current_user: User = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.models.employee import Employee, EmploymentStatus

    items = (await db.execute(select(Shift).where(Shift.tenant_id == tenant_id, Shift.is_deleted == False).order_by(Shift.name))).scalars().all()
    # How many (current) employees work each shift.
    counts = dict(
        (
            await db.execute(
                select(Employee.default_shift_id, func.count())
                .where(
                    Employee.tenant_id == tenant_id,
                    Employee.is_deleted == False,  # noqa: E712
                    Employee.default_shift_id.isnot(None),
                    Employee.employment_status.notin_([EmploymentStatus.TERMINATED, EmploymentStatus.RESIGNED]),
                )
                .group_by(Employee.default_shift_id)
            )
        ).all()
    )
    return {"items": [{"id": str(s.id), "name": s.name, "code": s.code, "color": s.color,
                       "employee_count": counts.get(s.id, 0),
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


_LEFT = ("terminated", "resigned")


async def _require_shift(db: AsyncSession, tenant_id: uuid.UUID, shift_id: uuid.UUID) -> Shift:
    shift = (
        await db.execute(
            select(Shift).where(Shift.id == shift_id, Shift.tenant_id == tenant_id, Shift.is_deleted == False)  # noqa: E712
        )
    ).scalar_one_or_none()
    if shift is None:
        raise NotFoundError("Shift not found")
    return shift


@router.get("/{shift_id}/employees", summary="Who works this shift, and who could be added")
async def shift_roster(
    shift_id: uuid.UUID,
    search: str | None = Query(None, max_length=100),
    current_user: User = Depends(require_permission("attendance.view")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """`assigned` = employees on this shift; `others` = every other current
    employee, each with the shift they are on now (if any), so the "assign
    employees" dialog can show what moving someone would replace."""
    from sqlalchemy.orm import aliased
    from app.models.employee import Employee, EmploymentStatus
    from app.models.organization_structure import Department

    shift = await _require_shift(db, tenant_id, shift_id)
    current = aliased(Shift)
    stmt = (
        select(Employee, User, Department.name, current.id, current.name)
        .join(User, Employee.user_id == User.id)
        .outerjoin(Department, Employee.department_id == Department.id)
        .outerjoin(current, Employee.default_shift_id == current.id)
        .where(
            Employee.tenant_id == tenant_id,
            Employee.is_deleted == False,  # noqa: E712
            Employee.employment_status.notin_([EmploymentStatus.TERMINATED, EmploymentStatus.RESIGNED]),
        )
        .order_by(User.first_name, User.last_name)
        .limit(1000)
    )
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(or_(
            User.first_name.ilike(like), User.last_name.ilike(like), User.email.ilike(like),
            Employee.employee_code.ilike(like),
            func.concat(User.first_name, " ", User.last_name).ilike(like),
        ))

    assigned, others = [], []
    for emp, user, dept, cur_id, cur_name in (await db.execute(stmt)).all():
        row = {
            "id": str(emp.id),
            "employee_code": emp.employee_code,
            "name": (user.display_name or f"{user.first_name} {user.last_name}").strip(),
            "department_name": dept,
            "current_shift_id": str(cur_id) if cur_id else None,
            "current_shift_name": cur_name,
        }
        (assigned if cur_id == shift.id else others).append(row)
    return {
        "shift": {"id": str(shift.id), "name": shift.name, "code": shift.code},
        "assigned": assigned,
        "others": others,
    }


@router.put("/{shift_id}/employees", summary="Set exactly which employees work this shift")
async def set_shift_roster(
    shift_id: uuid.UUID,
    body: SetShiftRosterRequest,
    current_user: User = Depends(require_permission("attendance.regularize")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Everyone in `employee_ids` is put on this shift (leaving whatever shift
    they had); anyone currently on it who is NOT in the list is taken off it.
    Ids from another organization are refused outright."""
    from app.models.employee import Employee

    await _require_shift(db, tenant_id, shift_id)
    wanted = set(body.employee_ids)

    if wanted:
        found = set(
            (
                await db.execute(
                    select(Employee.id).where(
                        Employee.tenant_id == tenant_id,
                        Employee.is_deleted == False,  # noqa: E712
                        Employee.id.in_(wanted),
                    )
                )
            ).scalars().all()
        )
        if found != wanted:
            raise NotFoundError("One or more employees were not found in this organization")

    cleared = (
        await db.execute(
            update(Employee)
            .where(
                Employee.tenant_id == tenant_id,
                Employee.default_shift_id == shift_id,
                Employee.id.notin_(wanted) if wanted else True,
            )
            .values(default_shift_id=None)
        )
    ).rowcount or 0
    assigned = 0
    if wanted:
        assigned = (
            await db.execute(
                update(Employee)
                .where(Employee.tenant_id == tenant_id, Employee.id.in_(wanted))
                .values(default_shift_id=shift_id)
            )
        ).rowcount or 0
    await db.flush()
    return {"shift_id": str(shift_id), "assigned": assigned, "cleared": cleared}


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
