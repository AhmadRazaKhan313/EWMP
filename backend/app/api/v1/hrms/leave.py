"""Leave Types & Balance API."""
import uuid
from datetime import date as ddate
from decimal import Decimal, InvalidOperation
from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.models.attendance import LeaveType, LeaveBalance, LeaveRequest, LeaveRequestStatus
from app.models.employee import Employee
from app.models.organization import Organization
from app.models.user import User
from app.permissions.dependencies import get_current_user, get_tenant_id, require_permission
from app.repositories.employee import EmployeeRepository

router = APIRouter(prefix="/leave", tags=["Leave"])

DEFAULT_WORK_HOURS_PER_DAY = Decimal("8.0")


class LeaveTypeCreate(BaseModel):
    name: str
    code: str
    days_per_year: float = 0
    is_paid: bool = True
    requires_approval: bool = True
    requires_document: bool = False
    is_carry_forward: bool = False
    color: str = "#3b82f6"


class LeaveTypeUpdate(BaseModel):
    name: str | None = None
    days_per_year: float | None = None
    is_active: bool | None = None
    color: str | None = None


class LeaveApplyRequest(BaseModel):
    employee_id: uuid.UUID | None = None
    leave_type_id: uuid.UUID
    start_date: str
    end_date: str
    reason: str = ""
    duration_type: Literal["full_day", "half_day", "hourly"] = "full_day"
    half_day_period: Literal["morning", "afternoon"] | None = None
    hours: float | None = None

    @model_validator(mode="after")
    def _check_duration_fields(self) -> "LeaveApplyRequest":
        if self.duration_type == "half_day" and self.half_day_period is None:
            raise ValueError("half_day_period is required when duration_type is 'half_day'")
        if self.duration_type == "hourly" and self.hours is None:
            raise ValueError("hours is required when duration_type is 'hourly'")
        return self


class LeaveRejectRequest(BaseModel):
    reason: str = "Not approved"


# ── Duration / balance helpers (bugs C2, H6) ────────────────────────────────

async def _hours_per_day(db: AsyncSession, tenant_id: uuid.UUID) -> Decimal:
    """Org-configurable standard work day length, from `organizations.settings`
    (e.g. {"standard_work_hours_per_day": 8}); falls back to 8h if unset/invalid.
    Used to convert hourly leave requests into day-equivalents for balance math.
    """
    org = (
        await db.execute(select(Organization).where(Organization.id == tenant_id))
    ).scalar_one_or_none()
    raw = (org.settings or {}).get("standard_work_hours_per_day") if org else None
    if raw is not None:
        try:
            val = Decimal(str(raw))
            if val > 0:
                return val
        except (InvalidOperation, TypeError, ValueError):
            pass
    return DEFAULT_WORK_HOURS_PER_DAY


def _compute_total_days(
    duration_type: str,
    start: ddate,
    end: ddate,
    half_day_period: str | None,
    hours: float | None,
    hours_per_day: Decimal,
) -> Decimal:
    """Translate a leave request's duration into day-equivalents for balance
    accounting. Raises ValidationError on anything inconsistent."""
    if duration_type == "full_day":
        return Decimal((end - start).days + 1)

    if duration_type == "half_day":
        if start != end:
            raise ValidationError("Half-day leave must be a single day (start_date must equal end_date)")
        if half_day_period not in ("morning", "afternoon"):
            raise ValidationError("half_day_period must be 'morning' or 'afternoon' for half-day leave")
        return Decimal("0.5")

    if duration_type == "hourly":
        if start != end:
            raise ValidationError("Hourly leave must be a single day (start_date must equal end_date)")
        if hours is None or hours <= 0:
            raise ValidationError("hours must be a positive number for hourly leave")
        hours_dec = Decimal(str(hours))
        if hours_dec > hours_per_day:
            raise ValidationError(
                f"hours ({hours_dec}) cannot exceed the standard work day "
                f"({hours_per_day}h) for a single hourly request — use full_day or half_day instead"
            )
        return (hours_dec / hours_per_day).quantize(Decimal("0.01"))

    raise ValidationError("duration_type must be 'full_day', 'half_day', or 'hourly'")


async def _get_or_create_balance(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
    leave_type: LeaveType,
    year: int,
) -> LeaveBalance:
    """Fetch this employee's balance row for (leave_type, year), creating a
    fresh one (entitled_days = leave_type.days_per_year, everything else 0)
    the first time they touch this leave type in this year. This is the
    piece that was entirely missing before (bug C2): `LeaveBalance` was
    imported but never read from or written to anywhere."""
    result = await db.execute(
        select(LeaveBalance).where(
            LeaveBalance.tenant_id == tenant_id,
            LeaveBalance.employee_id == employee_id,
            LeaveBalance.leave_type_id == leave_type.id,
            LeaveBalance.year == year,
        )
    )
    balance = result.scalar_one_or_none()
    if balance is None:
        balance = LeaveBalance(
            tenant_id=tenant_id,
            employee_id=employee_id,
            leave_type_id=leave_type.id,
            year=year,
            entitled_days=leave_type.days_per_year,
            carried_forward_days=Decimal("0"),
            used_days=Decimal("0"),
            pending_days=Decimal("0"),
        )
        db.add(balance)
        await db.flush()
    return balance


@router.get("/types")
async def list_leave_types(
    current_user: User = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    items = (await db.execute(select(LeaveType).where(LeaveType.tenant_id == tenant_id, LeaveType.is_deleted == False).order_by(LeaveType.name))).scalars().all()
    return {"items": [{"id": str(t.id), "name": t.name, "code": t.code, "color": t.color,
                       "days_per_year": str(t.days_per_year), "is_paid": t.is_paid,
                       "requires_approval": t.requires_approval, "requires_document": t.requires_document,
                       "is_carry_forward": t.is_carry_forward, "is_active": t.is_active} for t in items], "total": len(items)}

@router.post("/types", status_code=status.HTTP_201_CREATED)
async def create_leave_type(
    body: LeaveTypeCreate,
    current_user: User = Depends(require_permission("leave.manage_types")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    lt = LeaveType(tenant_id=tenant_id, name=body.name, code=body.code.upper(),
                   days_per_year=body.days_per_year, is_paid=body.is_paid,
                   requires_approval=body.requires_approval, requires_document=body.requires_document,
                   is_carry_forward=body.is_carry_forward, color=body.color, is_active=True)
    db.add(lt)
    await db.flush()
    return {"id": str(lt.id), "name": lt.name, "created": True}

@router.patch("/types/{type_id}")
async def update_leave_type(
    type_id: uuid.UUID,
    body: LeaveTypeUpdate,
    current_user: User = Depends(require_permission("leave.manage_types")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(LeaveType).where(LeaveType.id == type_id, LeaveType.tenant_id == tenant_id))
    lt = result.scalar_one_or_none()
    if not lt:
        raise NotFoundError("Leave type not found")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(lt, field, val)
    await db.flush()
    return {"id": str(lt.id), "updated": True}

@router.get("/requests")
async def list_leave_requests(
    leave_status: str | None = Query(None, alias="status"),
    employee_id: uuid.UUID | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from sqlalchemy import func

    # Two tiers, same shape as attendance's view/view_own split: `leave.view`
    # sees the whole org and may filter by any employee_id (unchanged).
    # `leave.apply`-only holders (plain self-service employees — they can
    # file leave but were never granted the broad `leave.view` permission)
    # see only their own requests — employee_id is forced to their own
    # employee id, ignoring whatever was requested in the query string.
    if not current_user.has_permission("leave.view"):
        if not current_user.has_permission("leave.apply"):
            raise PermissionDeniedError(
                "Viewing leave requests requires the 'leave.view' permission "
                "(or 'leave.apply' to see your own)."
            )
        repo = EmployeeRepository(db, tenant_id)
        own = await repo.get_by_user_id(current_user.id)
        if own is None:
            raise NotFoundError("Employee profile not found for this user")
        employee_id = own.id

    filters = [LeaveRequest.tenant_id == tenant_id, LeaveRequest.is_deleted == False]
    if leave_status:
        filters.append(LeaveRequest.status == leave_status)
    if employee_id:
        filters.append(LeaveRequest.employee_id == employee_id)
    offset = (page - 1) * page_size

    # Joined so the response carries real employee/leave-type names instead
    # of a literal "Employee" placeholder and a raw leave_type UUID.
    stmt = (
        select(LeaveRequest, User, LeaveType)
        .join(Employee, Employee.id == LeaveRequest.employee_id)
        .join(User, User.id == Employee.user_id)
        .join(LeaveType, LeaveType.id == LeaveRequest.leave_type_id)
        .where(*filters)
        .order_by(LeaveRequest.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    count_stmt = select(func.count()).select_from(LeaveRequest).where(*filters)
    rows = (await db.execute(stmt)).all()
    total = (await db.execute(count_stmt)).scalar_one()
    return {
        "items": [
            {
                "id": str(r.id),
                "employee_id": str(r.employee_id),
                "employee_name": u.full_name,
                "leave_type": lt.name,
                "leave_type_color": lt.color,
                "start_date": str(r.start_date),
                "end_date": str(r.end_date),
                "total_days": float(r.total_days),
                "duration_type": r.duration_type,
                "half_day_period": r.half_day_period,
                "hours": float(r.hours) if r.hours is not None else None,
                "reason": r.reason,
                "status": r.status.value,
                "created_at": r.created_at.isoformat(),
            }
            for r, u, lt in rows
        ],
        "total": total, "page": page, "page_size": page_size,
        "total_pages": max(1, -(-total // page_size)),
    }

@router.post("/requests/{request_id}/approve")
async def approve_leave(
    request_id: uuid.UUID,
    current_user: User = Depends(require_permission("leave.approve")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from datetime import UTC, datetime
    result = await db.execute(select(LeaveRequest).where(LeaveRequest.id == request_id, LeaveRequest.tenant_id == tenant_id))
    req = result.scalar_one_or_none()
    if not req:
        raise NotFoundError("Leave request not found")
    if req.status != LeaveRequestStatus.PENDING:
        raise ConflictError(f"Only pending requests can be approved (this one is '{req.status.value}')")

    # Move the hold from pending -> used now that it's committed (bug C2).
    leave_type = (
        await db.execute(select(LeaveType).where(LeaveType.id == req.leave_type_id, LeaveType.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if leave_type is not None:
        balance = await _get_or_create_balance(db, tenant_id, req.employee_id, leave_type, req.start_date.year)
        balance.pending_days = max(Decimal("0"), balance.pending_days - req.total_days)
        balance.used_days = balance.used_days + req.total_days

    # approver_id is a FK to employees.id, not users.id (bug H5). Resolve the
    # approving user's own employee record; if they don't have one (e.g. a
    # pure account owner with no HR profile), leave it null rather than
    # writing a User id into an employees FK.
    approver_employee = await EmployeeRepository(db, tenant_id).get_by_user_id(current_user.id)
    req.approver_id = approver_employee.id if approver_employee is not None else None

    req.status = LeaveRequestStatus.APPROVED
    req.approved_at = datetime.now(UTC)
    await db.flush()
    return {"id": str(req.id), "status": req.status.value, "message": "Leave approved"}

@router.post("/requests/{request_id}/reject")
async def reject_leave(
    request_id: uuid.UUID,
    body: LeaveRejectRequest,
    current_user: User = Depends(require_permission("leave.approve")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(LeaveRequest).where(LeaveRequest.id == request_id, LeaveRequest.tenant_id == tenant_id))
    req = result.scalar_one_or_none()
    if not req:
        raise NotFoundError("Leave request not found")
    if req.status != LeaveRequestStatus.PENDING:
        raise ConflictError(f"Only pending requests can be rejected (this one is '{req.status.value}')")

    # Release the pending hold — a rejected request never fabricates a
    # balance row that didn't already exist (apply_leave always creates one).
    balance = (
        await db.execute(
            select(LeaveBalance).where(
                LeaveBalance.tenant_id == tenant_id,
                LeaveBalance.employee_id == req.employee_id,
                LeaveBalance.leave_type_id == req.leave_type_id,
                LeaveBalance.year == req.start_date.year,
            )
        )
    ).scalar_one_or_none()
    if balance is not None:
        balance.pending_days = max(Decimal("0"), balance.pending_days - req.total_days)

    req.status = LeaveRequestStatus.REJECTED
    req.rejection_reason = body.reason
    await db.flush()
    return {"id": str(req.id), "status": req.status.value, "message": "Leave rejected"}

async def _resolve_leave_employee(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    current_user: User,
    employee_id: uuid.UUID | None,
) -> uuid.UUID:
    """Resolve whose leave is being applied for (self-scope gate for bug C2).

    Self-service by default: a ``leave.apply`` holder files leave for their
    OWN employee record. Filing on behalf of a *different* employee requires
    the manager/HR ``leave.approve`` permission. Without this gate any
    applicant could file (or silently exhaust) leave as any other employee
    just by passing an arbitrary ``employee_id``.
    """
    repo = EmployeeRepository(db, tenant_id)
    own = await repo.get_by_user_id(current_user.id)

    # No target, or explicitly targeting self → the caller's own record.
    if employee_id is None or (own is not None and employee_id == own.id):
        if own is None:
            raise NotFoundError("Employee profile not found for this user")
        return own.id

    # Applying on behalf of someone else → manager/HR only.
    if not current_user.has_permission("leave.approve"):
        raise PermissionDeniedError(
            "You can only apply for your own leave; applying on behalf of "
            "another employee requires the 'leave.approve' permission."
        )
    target = await repo.get(employee_id)  # tenant-scoped: cross-tenant id → None
    if target is None:
        raise NotFoundError("Employee not found")
    return target.id


@router.post("/requests", status_code=status.HTTP_201_CREATED)
async def apply_leave(
    body: LeaveApplyRequest,
    current_user: User = Depends(require_permission("leave.apply")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    sd = ddate.fromisoformat(body.start_date)
    ed = ddate.fromisoformat(body.end_date)
    if ed < sd:
        raise ValidationError("end_date cannot be before start_date")

    employee_id = await _resolve_leave_employee(
        db, tenant_id, current_user, body.employee_id
    )

    leave_type = (
        await db.execute(
            select(LeaveType).where(LeaveType.id == body.leave_type_id, LeaveType.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if leave_type is None:
        raise NotFoundError("Leave type not found")
    if not leave_type.is_active:
        raise ValidationError(f"'{leave_type.name}' is no longer an active leave type")

    hours_per_day = await _hours_per_day(db, tenant_id)
    total_days = _compute_total_days(body.duration_type, sd, ed, body.half_day_period, body.hours, hours_per_day)

    # min_days_per_request is meant for full-day requests (default 1) — a
    # half-day/hourly request is inherently "less than a day" by design, so
    # it doesn't make sense to reject it against that floor.
    if body.duration_type == "full_day" and total_days < leave_type.min_days_per_request:
        raise ValidationError(
            f"'{leave_type.name}' requires a minimum of {leave_type.min_days_per_request} day(s) per request"
        )
    if leave_type.max_days_per_request is not None and total_days > leave_type.max_days_per_request:
        raise ValidationError(
            f"'{leave_type.name}' allows a maximum of {leave_type.max_days_per_request} day(s) per request"
        )

    balance = await _get_or_create_balance(db, tenant_id, employee_id, leave_type, sd.year)
    if total_days > balance.remaining_days:
        raise ConflictError(
            f"Insufficient '{leave_type.name}' balance: {balance.remaining_days} day(s) remaining, "
            f"{total_days} day(s) requested"
        )

    req = LeaveRequest(
        tenant_id=tenant_id,
        employee_id=employee_id,
        leave_type_id=leave_type.id,
        start_date=sd,
        end_date=ed,
        total_days=total_days,
        duration_type=body.duration_type,
        hours=Decimal(str(body.hours)) if body.duration_type == "hourly" and body.hours is not None else None,
        is_half_day=(body.duration_type == "half_day"),
        half_day_period=body.half_day_period if body.duration_type == "half_day" else None,
        reason=body.reason or None,
        status=LeaveRequestStatus.PENDING,
    )
    db.add(req)
    balance.pending_days = balance.pending_days + total_days
    await db.flush()
    return {
        "id": str(req.id),
        "employee_id": str(employee_id),
        "total_days": float(total_days),
        "duration_type": req.duration_type,
        "status": req.status.value,
        "created": True,
    }


@router.get("/balances")
async def get_leave_balances(
    employee_id: uuid.UUID | None = Query(None),
    year: int | None = Query(None),
    current_user: User = Depends(require_permission("leave.view")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Per-leave-type balance for one employee (bug C2 — this endpoint plus
    the balance math in apply/approve/reject is what was entirely missing).

    Self-scoped like /leave/requests apply: no employee_id (or your own) is
    always allowed; another employee's balance requires leave.approve,
    reusing the same gate as filing leave on someone else's behalf.
    """
    target_employee_id = await _resolve_leave_employee(db, tenant_id, current_user, employee_id)
    target_year = year or ddate.today().year

    leave_types = (
        await db.execute(
            select(LeaveType).where(LeaveType.tenant_id == tenant_id, LeaveType.is_active == True)  # noqa: E712
        )
    ).scalars().all()

    existing = {
        b.leave_type_id: b
        for b in (
            await db.execute(
                select(LeaveBalance).where(
                    LeaveBalance.tenant_id == tenant_id,
                    LeaveBalance.employee_id == target_employee_id,
                    LeaveBalance.year == target_year,
                )
            )
        ).scalars().all()
    }

    items = []
    for lt in leave_types:
        bal = existing.get(lt.id)
        if bal is not None:
            entitled, carried, used, pending = bal.entitled_days, bal.carried_forward_days, bal.used_days, bal.pending_days
        else:
            # Not yet touched this year — show the entitlement as-if, without
            # writing a row (rows are only ever created by an actual apply).
            entitled, carried, used, pending = lt.days_per_year, Decimal("0"), Decimal("0"), Decimal("0")
        items.append({
            "leave_type_id": str(lt.id),
            "leave_type_name": lt.name,
            "leave_type_color": lt.color,
            "year": target_year,
            "entitled_days": float(entitled),
            "carried_forward_days": float(carried),
            "used_days": float(used),
            "pending_days": float(pending),
            "remaining_days": float(entitled + carried - used - pending),
        })

    return {"employee_id": str(target_employee_id), "year": target_year, "items": items}