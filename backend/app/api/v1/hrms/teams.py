"""Teams API endpoints (with member management)."""
import uuid
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.core.database import get_db
from app.core.exceptions import NotFoundError, ConflictError
from app.models.employee import Employee
from app.models.organization_structure import Team
from app.models.user import User
from app.permissions.dependencies import get_current_user, get_tenant_id, require_permission

router = APIRouter(prefix="/teams", tags=["Teams"])


class TeamCreate(BaseModel):
    name: str
    description: str = ""
    color: str = "#3b82f6"
    department_id: uuid.UUID | None = None
    lead_employee_id: uuid.UUID | None = None
    member_ids: list[uuid.UUID] = []          # optional: add members at creation


class TeamUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    color: str | None = None
    is_active: bool | None = None
    lead_employee_id: uuid.UUID | None = None


class MembersBody(BaseModel):
    employee_ids: list[uuid.UUID]


# ── helpers ──────────────────────────────────────────────────────────────────
def _employee_dict(e: Employee) -> dict:
    u = e.user
    return {
        "id": str(e.id),
        "employee_code": e.employee_code,
        "full_name": u.full_name if u else e.employee_code,
        "email": u.email if u else None,
        "avatar_url": u.avatar_url if u else None,
        "employment_status": str(e.employment_status.value) if e.employment_status else None,
        "department_id": str(e.department_id) if e.department_id else None,
        "designation_id": str(e.designation_id) if e.designation_id else None,
    }


async def _get_team(db: AsyncSession, tenant_id: uuid.UUID, team_id: uuid.UUID) -> Team:
    team = (await db.execute(
        select(Team).where(Team.id == team_id, Team.tenant_id == tenant_id, Team.is_deleted == False)  # noqa: E712
    )).scalar_one_or_none()
    if not team:
        raise NotFoundError("Team not found")
    return team


async def _assign(db: AsyncSession, tenant_id: uuid.UUID, team_id: uuid.UUID, ids: list[uuid.UUID]) -> int:
    if not ids:
        return 0
    emps = (await db.execute(
        select(Employee).where(
            Employee.id.in_(ids), Employee.tenant_id == tenant_id, Employee.is_deleted == False  # noqa: E712
        )
    )).scalars().all()
    for e in emps:
        e.team_id = team_id
    await db.flush()
    return len(emps)


# ── list / create / update / delete ──────────────────────────────────────────
@router.get("")
async def list_teams(
    current_user: User = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    items = (await db.execute(
        select(Team).where(Team.tenant_id == tenant_id, Team.is_deleted == False).order_by(Team.name)  # noqa: E712
    )).scalars().all()

    # member counts in ONE query
    counts = dict((await db.execute(
        select(Employee.team_id, func.count(Employee.id))
        .where(Employee.tenant_id == tenant_id, Employee.is_deleted == False, Employee.team_id.isnot(None))  # noqa: E712
        .group_by(Employee.team_id)
    )).all())

    # lead names in ONE query
    lead_ids = [t.lead_employee_id for t in items if t.lead_employee_id]
    lead_names: dict = {}
    if lead_ids:
        leads = (await db.execute(
            select(Employee).options(selectinload(Employee.user)).where(Employee.id.in_(lead_ids))
        )).scalars().all()
        lead_names = {l.id: (l.user.full_name if l.user else l.employee_code) for l in leads}

    return {
        "items": [{
            "id": str(t.id), "name": t.name, "slug": t.slug, "description": t.description,
            "color": t.color, "is_active": t.is_active,
            "lead_employee_id": str(t.lead_employee_id) if t.lead_employee_id else None,
            "lead_name": lead_names.get(t.lead_employee_id),
            "department_id": str(t.department_id) if t.department_id else None,
            "member_count": counts.get(t.id, 0),
        } for t in items],
        "total": len(items),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_team(
    body: TeamCreate,
    current_user: User = Depends(require_permission("teams.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from slugify import slugify
    team = Team(
        tenant_id=tenant_id, name=body.name, slug=slugify(body.name),
        description=body.description or None, color=body.color,
        department_id=body.department_id, lead_employee_id=body.lead_employee_id, is_active=True,
    )
    db.add(team)
    await db.flush()

    ids = list(body.member_ids)
    if body.lead_employee_id and body.lead_employee_id not in ids:
        ids.append(body.lead_employee_id)          # lead is always a member
    added = await _assign(db, tenant_id, team.id, ids)
    return {"id": str(team.id), "name": team.name, "created": True, "members_added": added}


@router.patch("/{team_id}")
async def update_team(
    team_id: uuid.UUID,
    body: TeamUpdate,
    current_user: User = Depends(require_permission("teams.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    team = await _get_team(db, tenant_id, team_id)
    data = body.model_dump(exclude_unset=True)
    for field, val in data.items():
        setattr(team, field, val)
    if data.get("lead_employee_id"):
        await _assign(db, tenant_id, team.id, [data["lead_employee_id"]])
    await db.flush()
    return {"id": str(team.id), "updated": True}


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(
    team_id: uuid.UUID,
    current_user: User = Depends(require_permission("teams.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    team = await _get_team(db, tenant_id, team_id)
    active_count = (await db.execute(
        select(func.count()).select_from(Employee).where(
            Employee.team_id == team_id, Employee.tenant_id == tenant_id, Employee.is_deleted == False,  # noqa: E712
        )
    )).scalar_one()
    if active_count > 0:
        raise ConflictError(
            f"Cannot delete this team — {active_count} employee(s) are still assigned to it. Remove them first."
        )
    team.soft_delete()
    await db.flush()


# ── members ──────────────────────────────────────────────────────────────────
@router.get("/{team_id}/members")
async def list_members(
    team_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    team = await _get_team(db, tenant_id, team_id)
    emps = (await db.execute(
        select(Employee).options(selectinload(Employee.user)).where(
            Employee.team_id == team_id, Employee.tenant_id == tenant_id, Employee.is_deleted == False,  # noqa: E712
        )
    )).scalars().all()
    items = [{**_employee_dict(e), "is_lead": e.id == team.lead_employee_id} for e in emps]
    items.sort(key=lambda x: (not x["is_lead"], x["full_name"].lower()))
    return {"items": items, "total": len(items)}


@router.get("/{team_id}/available-employees")
async def available_employees(
    team_id: uuid.UUID,
    current_user: User = Depends(require_permission("teams.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Employees NOT already in this team (so the picker never needs employees.view)."""
    await _get_team(db, tenant_id, team_id)
    emps = (await db.execute(
        select(Employee).options(selectinload(Employee.user)).where(
            Employee.tenant_id == tenant_id, Employee.is_deleted == False,  # noqa: E712
            (Employee.team_id.is_(None)) | (Employee.team_id != team_id),
        )
    )).scalars().all()
    items = sorted((_employee_dict(e) for e in emps), key=lambda x: x["full_name"].lower())
    return {"items": items, "total": len(items)}


@router.post("/{team_id}/members")
async def add_members(
    team_id: uuid.UUID,
    body: MembersBody,
    current_user: User = Depends(require_permission("teams.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _get_team(db, tenant_id, team_id)
    added = await _assign(db, tenant_id, team_id, body.employee_ids)
    return {"added": added}


@router.delete("/{team_id}/members/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    team_id: uuid.UUID,
    employee_id: uuid.UUID,
    current_user: User = Depends(require_permission("teams.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    team = await _get_team(db, tenant_id, team_id)
    emp = (await db.execute(
        select(Employee).where(
            Employee.id == employee_id, Employee.team_id == team_id, Employee.tenant_id == tenant_id,
        )
    )).scalar_one_or_none()
    if not emp:
        raise NotFoundError("Employee is not in this team")
    emp.team_id = None
    if team.lead_employee_id == employee_id:
        team.lead_employee_id = None            # removed member can't stay lead
    await db.flush()