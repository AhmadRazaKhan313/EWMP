"""Departments API endpoints."""

import uuid
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundError, ConflictError
from app.models.organization_structure import Department
from app.models.user import User
from app.permissions.dependencies import get_current_user, get_tenant_id, require_permission

router = APIRouter(prefix="/departments", tags=["Departments"])


class DepartmentCreate(BaseModel):
    name: str
    code: str = ""
    description: str = ""
    parent_id: uuid.UUID | None = None


class DepartmentUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    description: str | None = None
    is_active: bool | None = None


@router.get("", summary="List all departments")
async def list_departments(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    filters = [Department.tenant_id == tenant_id, Department.is_deleted == False]  # noqa: E712
    offset = (page - 1) * page_size
    stmt = select(Department).where(*filters).order_by(Department.display_order, Department.name).offset(offset).limit(page_size)
    count_stmt = select(func.count()).select_from(Department).where(*filters)
    items = (await db.execute(stmt)).scalars().all()
    total = (await db.execute(count_stmt)).scalar_one()
    return {
        "items": [
            {
                "id": str(d.id),
                "name": d.name,
                "code": d.code,
                "description": d.description,
                "parent_id": str(d.parent_id) if d.parent_id else None,
                "head_employee_id": str(d.head_employee_id) if d.head_employee_id else None,
                "is_active": d.is_active,
                "display_order": d.display_order,
                "created_at": d.created_at.isoformat(),
            }
            for d in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, -(-total // page_size)),
    }


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create department")
async def create_department(
    body: DepartmentCreate,
    current_user: User = Depends(require_permission("departments.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    dept = Department(
        tenant_id=tenant_id,
        name=body.name,
        code=body.code.upper() if body.code else None,
        description=body.description or None,
        parent_id=body.parent_id,
        is_active=True,
    )
    db.add(dept)
    await db.flush()
    return {"id": str(dept.id), "name": dept.name, "created": True}


@router.patch("/{dept_id}", summary="Update department")
async def update_department(
    dept_id: uuid.UUID,
    body: DepartmentUpdate,
    current_user: User = Depends(require_permission("departments.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Department).where(Department.id == dept_id, Department.tenant_id == tenant_id)
    )
    dept = result.scalar_one_or_none()
    if not dept:
        raise NotFoundError("Department not found")
    if body.name is not None:
        dept.name = body.name
    if body.code is not None:
        dept.code = body.code.upper()
    if body.description is not None:
        dept.description = body.description
    if body.is_active is not None:
        dept.is_active = body.is_active
    await db.flush()
    return {"id": str(dept.id), "updated": True}


@router.delete("/{dept_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete department")
async def delete_department(
    dept_id: uuid.UUID,
    current_user: User = Depends(require_permission("departments.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(Department).where(Department.id == dept_id, Department.tenant_id == tenant_id)
    )
    dept = result.scalar_one_or_none()
    if not dept:
        raise NotFoundError("Department not found")

    from app.models.employee import Employee
    active_count = (
        await db.execute(
            select(func.count()).select_from(Employee).where(
                Employee.department_id == dept_id,
                Employee.tenant_id == tenant_id,
                Employee.is_deleted == False,  # noqa: E712
            )
        )
    ).scalar_one()
    if active_count > 0:
        raise ConflictError(
            f"Cannot delete this department — {active_count} employee(s) are still "
            "assigned to it. Reassign them first."
        )

    dept.soft_delete()
    await db.flush()
