"""Teams API endpoints."""
import uuid
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.exceptions import NotFoundError, ConflictError
from app.models.organization_structure import Team
from app.models.user import User
from app.permissions.dependencies import get_current_user, get_tenant_id, require_permission

router = APIRouter(prefix="/teams", tags=["Teams"])


class TeamCreate(BaseModel):
    name: str
    description: str = ""
    color: str = "#3b82f6"
    department_id: uuid.UUID | None = None


class TeamUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    color: str | None = None
    is_active: bool | None = None


@router.get("")
async def list_teams(
    current_user: User = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    items = (await db.execute(select(Team).where(Team.tenant_id == tenant_id, Team.is_deleted == False).order_by(Team.name))).scalars().all()
    return {"items": [{"id": str(t.id), "name": t.name, "slug": t.slug, "description": t.description,
                       "color": t.color, "is_active": t.is_active,
                       "lead_employee_id": str(t.lead_employee_id) if t.lead_employee_id else None,
                       "department_id": str(t.department_id) if t.department_id else None} for t in items], "total": len(items)}

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_team(
    body: TeamCreate,
    current_user: User = Depends(require_permission("teams.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Correct import is `from slugify import slugify` — the pip package is
    # named python-slugify but the importable module is just `slugify`.
    # `from python_slugify import slugify` (the old code) always raised
    # ModuleNotFoundError, so team creation crashed even after fixing the
    # request-body issue.
    from slugify import slugify
    slug = slugify(body.name)
    team = Team(tenant_id=tenant_id, name=body.name, slug=slug, description=body.description or None,
                color=body.color, department_id=body.department_id, is_active=True)
    db.add(team)
    await db.flush()
    return {"id": str(team.id), "name": team.name, "created": True}

@router.patch("/{team_id}")
async def update_team(
    team_id: uuid.UUID,
    body: TeamUpdate,
    current_user: User = Depends(require_permission("teams.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(Team).where(Team.id == team_id, Team.tenant_id == tenant_id))
    team = result.scalar_one_or_none()
    if not team:
        raise NotFoundError("Team not found")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(team, field, val)
    await db.flush()
    return {"id": str(team.id), "updated": True}

@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(
    team_id: uuid.UUID,
    current_user: User = Depends(require_permission("teams.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(select(Team).where(Team.id == team_id, Team.tenant_id == tenant_id))
    team = result.scalar_one_or_none()
    if not team:
        raise NotFoundError("Team not found")

    from app.models.employee import Employee
    active_count = (
        await db.execute(
            select(func.count()).select_from(Employee).where(
                Employee.team_id == team_id,
                Employee.tenant_id == tenant_id,
                Employee.is_deleted == False,  # noqa: E712
            )
        )
    ).scalar_one()
    if active_count > 0:
        raise ConflictError(
            f"Cannot delete this team — {active_count} employee(s) are still "
            "assigned to it. Reassign them first."
        )

    team.soft_delete()
    await db.flush()
