"""Break-time lock API (K-01). Admin: break.manage / break.approve. Employee: self-scope."""
import uuid
from datetime import UTC, date, datetime, time

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import (
    ConflictError, EmployeeProfileNotLinkedError, NotFoundError, ValidationError,
)
from app.models.break_policy import (
    BreakOverride, BreakPolicy, BreakScope, BreakUnlockRequest, UnlockStatus,
)
from app.models.employee import Employee
from app.models.organization_structure import Department
from app.models.user import User
from app.permissions.dependencies import get_current_user, get_tenant_id, require_permission
from app.repositories.employee import EmployeeRepository
from app.services.break_lock import _instants, break_state, effective_break
from app.services.onboarding_common import notify, recipient_ids
from app.core.timezones import local_today, org_zone

router = APIRouter(prefix="/break", tags=["Break Lock"])


# ── schemas ───────────────────────────────────────────────────────────────────
class PolicyIn(BaseModel):
    scope: BreakScope = BreakScope.ORGANIZATION
    scope_id: uuid.UUID | None = None
    start_time: time
    duration_minutes: int = Field(60, ge=5, le=480)
    days: list[int] | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def _check(self):
        if self.scope == BreakScope.ORGANIZATION:
            self.scope_id = None
        elif self.scope_id is None:
            raise ValueError("scope_id is required for this scope")
        if self.days is not None and any(d < 0 or d > 6 for d in self.days):
            raise ValueError("days must be 0 (Mon) … 6 (Sun)")
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to is before valid_from")
        return self


class OverrideIn(BaseModel):
    employee_ids: list[uuid.UUID] = []
    department_id: uuid.UUID | None = None
    on_date: date
    start_time: time | None = None  # None => no break that day
    duration_minutes: int | None = Field(None, ge=5, le=480)
    reason: str | None = None

    @model_validator(mode="after")
    def _check(self):
        if not self.employee_ids and not self.department_id:
            raise ValueError("pick employee_ids or a department_id")
        if self.start_time is not None and self.duration_minutes is None:
            self.duration_minutes = 60
        return self


class UnlockIn(BaseModel):
    reason: str | None = Field(None, max_length=500)


def _policy_out(p: BreakPolicy) -> dict:
    return {"id": str(p.id), "scope": p.scope.value, "scope_id": str(p.scope_id) if p.scope_id else None,
            "start_time": p.start_time.strftime("%H:%M"), "duration_minutes": p.duration_minutes,
            "days": p.days, "valid_from": p.valid_from, "valid_to": p.valid_to, "is_active": p.is_active}


def _override_out(o: BreakOverride) -> dict:
    return {"id": str(o.id), "employee_id": str(o.employee_id) if o.employee_id else None,
            "department_id": str(o.department_id) if o.department_id else None, "on_date": o.on_date,
            "start_time": o.start_time.strftime("%H:%M") if o.start_time else None,
            "duration_minutes": o.duration_minutes, "reason": o.reason}


async def _own_employee(db, tenant_id, user: User) -> Employee:
    e = await EmployeeRepository(db, tenant_id).get_by_user_id(user.id)
    if e is None:
        raise EmployeeProfileNotLinkedError()
    return e


async def _check_scope_target(db, tenant_id, scope: BreakScope, scope_id):
    if scope == BreakScope.EMPLOYEE:
        ok = (await db.execute(select(Employee.id).where(Employee.id == scope_id, Employee.tenant_id == tenant_id))).first()
    elif scope == BreakScope.DEPARTMENT:
        ok = (await db.execute(select(Department.id).where(Department.id == scope_id, Department.tenant_id == tenant_id))).first()
    elif scope == BreakScope.SHIFT:
        from app.models.attendance import Shift
        ok = (await db.execute(select(Shift.id).where(Shift.id == scope_id, Shift.tenant_id == tenant_id))).first()
    else:
        return
    if not ok:
        raise NotFoundError("Target not found in your organization")


# ── policies (admin) ──────────────────────────────────────────────────────────
@router.get("/policy")
async def get_org_policy(db: AsyncSession = Depends(get_db), tenant_id: uuid.UUID = Depends(get_tenant_id),
                         _: User = Depends(require_permission("break.manage"))):
    p = (await db.execute(select(BreakPolicy).where(
        BreakPolicy.tenant_id == tenant_id, BreakPolicy.is_deleted == False,  # noqa: E712
        BreakPolicy.scope == BreakScope.ORGANIZATION).order_by(BreakPolicy.created_at.desc()))).scalars().first()
    return _policy_out(p) if p else None


@router.put("/policy")
async def put_org_policy(body: PolicyIn, db: AsyncSession = Depends(get_db), tenant_id: uuid.UUID = Depends(get_tenant_id),
                         _: User = Depends(require_permission("break.manage"))):
    p = (await db.execute(select(BreakPolicy).where(
        BreakPolicy.tenant_id == tenant_id, BreakPolicy.is_deleted == False,  # noqa: E712
        BreakPolicy.scope == BreakScope.ORGANIZATION).order_by(BreakPolicy.created_at.desc()))).scalars().first()
    data = body.model_dump(exclude={"scope", "scope_id"})
    if p is None:
        p = BreakPolicy(tenant_id=tenant_id, scope=BreakScope.ORGANIZATION, **data)
        db.add(p)
    else:
        for k, v in data.items():
            setattr(p, k, v)
    await db.flush()
    return _policy_out(p)


@router.get("/policies")
async def list_policies(db: AsyncSession = Depends(get_db), tenant_id: uuid.UUID = Depends(get_tenant_id),
                        _: User = Depends(require_permission("break.manage"))):
    rows = (await db.execute(select(BreakPolicy).where(
        BreakPolicy.tenant_id == tenant_id, BreakPolicy.is_deleted == False  # noqa: E712
    ).order_by(BreakPolicy.scope, BreakPolicy.created_at))).scalars().all()
    return [_policy_out(p) for p in rows]


@router.post("/policies", status_code=201)
async def create_policy(body: PolicyIn, db: AsyncSession = Depends(get_db), tenant_id: uuid.UUID = Depends(get_tenant_id),
                        _: User = Depends(require_permission("break.manage"))):
    await _check_scope_target(db, tenant_id, body.scope, body.scope_id)
    p = BreakPolicy(tenant_id=tenant_id, **body.model_dump())
    db.add(p)
    await db.flush()
    return _policy_out(p)


async def _get_policy(db, tenant_id, pid) -> BreakPolicy:
    p = (await db.execute(select(BreakPolicy).where(
        BreakPolicy.id == pid, BreakPolicy.tenant_id == tenant_id, BreakPolicy.is_deleted == False))).scalar_one_or_none()  # noqa: E712
    if p is None:
        raise NotFoundError("Break policy not found")
    return p


@router.put("/policies/{policy_id}")
async def update_policy(policy_id: uuid.UUID, body: PolicyIn, db: AsyncSession = Depends(get_db),
                        tenant_id: uuid.UUID = Depends(get_tenant_id),
                        _: User = Depends(require_permission("break.manage"))):
    p = await _get_policy(db, tenant_id, policy_id)
    await _check_scope_target(db, tenant_id, body.scope, body.scope_id)
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    await db.flush()
    return _policy_out(p)


@router.delete("/policies/{policy_id}", status_code=204)
async def delete_policy(policy_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                        tenant_id: uuid.UUID = Depends(get_tenant_id),
                        _: User = Depends(require_permission("break.manage"))):
    p = await _get_policy(db, tenant_id, policy_id)
    p.is_deleted = True
    p.deleted_at = datetime.now(UTC)


# ── overrides (admin) ─────────────────────────────────────────────────────────
@router.get("/overrides")
async def list_overrides(on_date: date | None = None, db: AsyncSession = Depends(get_db),
                         tenant_id: uuid.UUID = Depends(get_tenant_id),
                         _: User = Depends(require_permission("break.manage"))):
    q = select(BreakOverride).where(BreakOverride.tenant_id == tenant_id, BreakOverride.is_deleted == False)  # noqa: E712
    if on_date:
        q = q.where(BreakOverride.on_date == on_date)
    rows = (await db.execute(q.order_by(BreakOverride.on_date.desc()).limit(500))).scalars().all()
    return [_override_out(o) for o in rows]


@router.post("/overrides", status_code=201)
async def create_overrides(body: OverrideIn, db: AsyncSession = Depends(get_db),
                           tenant_id: uuid.UUID = Depends(get_tenant_id),
                           _: User = Depends(require_permission("break.manage"))):
    created: list[BreakOverride] = []
    if body.employee_ids:
        found = set((await db.execute(select(Employee.id).where(
            Employee.tenant_id == tenant_id, Employee.id.in_(body.employee_ids)))).scalars().all())
        if found != set(body.employee_ids):
            raise NotFoundError("Some employees were not found in your organization")
        targets = [(eid, None) for eid in body.employee_ids]
    else:
        await _check_scope_target(db, tenant_id, BreakScope.DEPARTMENT, body.department_id)
        targets = [(None, body.department_id)]
    for eid, did in targets:
        # one override per target per day: replace the old one
        old = (await db.execute(select(BreakOverride).where(
            BreakOverride.tenant_id == tenant_id, BreakOverride.is_deleted == False,  # noqa: E712
            BreakOverride.on_date == body.on_date,
            BreakOverride.employee_id == eid if eid else BreakOverride.department_id == did,
            *( [BreakOverride.employee_id.is_(None)] if not eid else [])))).scalars().all()
        for o in old:
            o.is_deleted = True
            o.deleted_at = datetime.now(UTC)
        o = BreakOverride(tenant_id=tenant_id, employee_id=eid, department_id=did, on_date=body.on_date,
                          start_time=body.start_time, duration_minutes=body.duration_minutes, reason=body.reason)
        db.add(o)
        created.append(o)
    await db.flush()
    return [_override_out(o) for o in created]


@router.delete("/overrides/{override_id}", status_code=204)
async def delete_override(override_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                          tenant_id: uuid.UUID = Depends(get_tenant_id),
                          _: User = Depends(require_permission("break.manage"))):
    o = (await db.execute(select(BreakOverride).where(
        BreakOverride.id == override_id, BreakOverride.tenant_id == tenant_id,
        BreakOverride.is_deleted == False))).scalar_one_or_none()  # noqa: E712
    if o is None:
        raise NotFoundError("Override not found")
    o.is_deleted = True
    o.deleted_at = datetime.now(UTC)


@router.get("/effective")
async def effective(employee_id: uuid.UUID, on_date: date | None = Query(None, alias="date"),
                    db: AsyncSession = Depends(get_db), tenant_id: uuid.UUID = Depends(get_tenant_id),
                    _: User = Depends(require_permission("break.manage"))):
    emp = (await db.execute(select(Employee).where(Employee.id == employee_id, Employee.tenant_id == tenant_id))).scalar_one_or_none()
    if emp is None:
        raise NotFoundError("Employee not found")
    zone = await org_zone(db, tenant_id)
    d = on_date or local_today(zone)
    w = await effective_break(db, tenant_id, emp, d)
    if w is None:
        return {"date": d, "has_break": False}
    s, e = _instants(d, w, zone)
    return {"date": d, "has_break": True, "start_time": w.start_time.strftime("%H:%M"),
            "duration_minutes": w.duration_minutes, "source": w.source, "start": s.isoformat(), "end": e.isoformat()}


# ── employee self-service ─────────────────────────────────────────────────────
@router.get("/me")
async def my_state(db: AsyncSession = Depends(get_db), tenant_id: uuid.UUID = Depends(get_tenant_id),
                   user: User = Depends(get_current_user)):
    emp = await _own_employee(db, tenant_id, user)
    return await break_state(db, tenant_id, emp)


@router.post("/unlock-requests", status_code=201)
async def request_unlock(body: UnlockIn, db: AsyncSession = Depends(get_db),
                         tenant_id: uuid.UUID = Depends(get_tenant_id), user: User = Depends(get_current_user)):
    emp = await _own_employee(db, tenant_id, user)
    st = await break_state(db, tenant_id, emp)
    if st["phase"] != "active":
        raise ValidationError("There is no break in progress to unlock")
    pending = (await db.execute(select(BreakUnlockRequest.id).where(
        BreakUnlockRequest.tenant_id == tenant_id, BreakUnlockRequest.employee_id == emp.id,
        BreakUnlockRequest.break_date == date.fromisoformat(st["date"]),
        BreakUnlockRequest.status == UnlockStatus.PENDING, BreakUnlockRequest.is_deleted == False))).first()  # noqa: E712
    if pending:
        raise ConflictError("You already have a pending unlock request")
    r = BreakUnlockRequest(tenant_id=tenant_id, employee_id=emp.id, break_date=date.fromisoformat(st["date"]),
                           reason=body.reason, status=UnlockStatus.PENDING)
    db.add(r)
    await db.flush()
    name = f"{user.first_name} {user.last_name}".strip()
    for uid in await recipient_ids(db, tenant_id, "break.approve"):
        notify(db, tenant_id, uid, title="Break unlock request",
               body=f"{name} ({emp.employee_code}) asked to keep working during the break.",
               type_="break_unlock", action_url="/settings?tab=break", icon="lock", meta={"request_id": str(r.id)})
    return {"id": str(r.id), "status": r.status.value}


# ── approvals (admin) ─────────────────────────────────────────────────────────
@router.get("/unlock-requests")
async def list_requests(status: UnlockStatus | None = None, db: AsyncSession = Depends(get_db),
                        tenant_id: uuid.UUID = Depends(get_tenant_id),
                        _: User = Depends(require_permission("break.approve"))):
    q = (select(BreakUnlockRequest, Employee, User)
         .join(Employee, Employee.id == BreakUnlockRequest.employee_id)
         .join(User, User.id == Employee.user_id)
         .where(BreakUnlockRequest.tenant_id == tenant_id, BreakUnlockRequest.is_deleted == False))  # noqa: E712
    if status:
        q = q.where(BreakUnlockRequest.status == status)
    rows = (await db.execute(q.order_by(BreakUnlockRequest.created_at.desc()).limit(200))).all()
    pending = (await db.execute(select(func.count()).select_from(BreakUnlockRequest).where(
        BreakUnlockRequest.tenant_id == tenant_id, BreakUnlockRequest.status == UnlockStatus.PENDING,
        BreakUnlockRequest.is_deleted == False))).scalar_one()  # noqa: E712
    return {"pending_count": pending, "items": [{
        "id": str(r.id), "employee_id": str(e.id), "employee_name": f"{u.first_name} {u.last_name}".strip(),
        "employee_code": e.employee_code, "break_date": r.break_date, "reason": r.reason,
        "status": r.status.value, "created_at": r.created_at, "decided_at": r.decided_at,
        "unlock_until": r.unlock_until} for r, e, u in rows]}


async def _decide(db, tenant_id, rid, user: User, approve: bool):
    r = (await db.execute(select(BreakUnlockRequest).where(
        BreakUnlockRequest.id == rid, BreakUnlockRequest.tenant_id == tenant_id,
        BreakUnlockRequest.is_deleted == False))).scalar_one_or_none()  # noqa: E712
    if r is None:
        raise NotFoundError("Request not found")
    if r.status != UnlockStatus.PENDING:
        raise ConflictError("This request was already decided")
    emp = (await db.execute(select(Employee).where(Employee.id == r.employee_id))).scalar_one()
    r.status = UnlockStatus.APPROVED if approve else UnlockStatus.DENIED
    r.decided_by, r.decided_at = user.id, datetime.now(UTC)
    if approve:
        zone = await org_zone(db, tenant_id)
        w = await effective_break(db, tenant_id, emp, r.break_date)
        # Unlocked for the rest of that break window.
        r.unlock_until = _instants(r.break_date, w, zone)[1] if w else r.decided_at
    notify(db, tenant_id, emp.user_id, title="Break unlock " + ("approved" if approve else "denied"),
           body="You can keep working." if approve else "Your computer stays locked until the break ends.",
           type_="break_unlock", icon="lock")
    await db.flush()
    return {"id": str(r.id), "status": r.status.value, "unlock_until": r.unlock_until}


@router.post("/unlock-requests/{request_id}/approve")
async def approve(request_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                  tenant_id: uuid.UUID = Depends(get_tenant_id), user: User = Depends(require_permission("break.approve"))):
    return await _decide(db, tenant_id, request_id, user, True)


@router.post("/unlock-requests/{request_id}/deny")
async def deny(request_id: uuid.UUID, db: AsyncSession = Depends(get_db),
               tenant_id: uuid.UUID = Depends(get_tenant_id), user: User = Depends(require_permission("break.approve"))):
    return await _decide(db, tenant_id, request_id, user, False)
