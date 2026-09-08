"""
Roles & Permissions API.

Every role here is a custom role an org admin created — there is no
default/seeded role list. Access is gated behind `roles.manage`, which
org owners always have (see User.has_permission's owner-bypass), so a
brand-new org's owner can start creating roles from their very first
login without needing anyone to grant them anything first.
"""

import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.models.rbac import Permission, Role
from app.models.user import User, user_roles
from app.permissions.dependencies import get_tenant_id, require_permission

router = APIRouter(prefix="/roles", tags=["Roles & Permissions"])


# ── Schemas ────────────────────────────────────────────────────────────────
class PermissionSchema(BaseModel):
    id: uuid.UUID
    codename: str
    label: str
    description: str | None
    resource: str
    action: str
    category: str
    is_sensitive: bool

    model_config = {"from_attributes": True}


class RoleCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    color: str | None = Field(default=None, max_length=7)
    is_super: bool = False
    permission_codenames: list[str] = Field(default_factory=list)


class RoleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    color: str | None = Field(default=None, max_length=7)
    is_super: bool | None = None
    permission_codenames: list[str] | None = None


class RoleResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    color: str | None
    is_super: bool
    display_order: int
    permission_codenames: list[str]
    user_count: int

    model_config = {"from_attributes": True}


def _slugify(name: str) -> str:
    return "-".join(name.strip().lower().split()) or "role"


async def _role_response(db: AsyncSession, role: Role) -> RoleResponse:
    user_count = (
        await db.execute(
            select(func.count())
            .select_from(user_roles)
            .where(user_roles.c.role_id == role.id)
        )
    ).scalar_one()
    return RoleResponse(
        id=role.id,
        name=role.name,
        slug=role.slug,
        description=role.description,
        color=role.color,
        is_super=role.is_super,
        display_order=role.display_order,
        permission_codenames=sorted(role.permission_codenames),
        user_count=user_count,
    )


async def _resolve_permissions(
    db: AsyncSession, codenames: list[str]
) -> list[Permission]:
    if not codenames:
        return []
    result = await db.execute(
        select(Permission).where(Permission.codename.in_(codenames))
    )
    found = result.scalars().all()
    found_codenames = {p.codename for p in found}
    unknown = set(codenames) - found_codenames
    if unknown:
        raise NotFoundError(f"Unknown permission codename(s): {', '.join(sorted(unknown))}")
    return list(found)


@router.get("/users/list", summary="List this organization's users (for role assignment)")
async def list_organization_users(
    current_user: User = Depends(require_permission("roles.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Deliberately minimal — just enough for a role-assignment picker in the
    UI. Full user/employee management lives under /employees.
    """
    result = await db.execute(
        select(User)
        .where(User.organization_id == tenant_id, User.is_deleted == False)  # noqa: E712
        .order_by(User.first_name, User.last_name)
    )
    users = result.scalars().all()
    return {
        "items": [
            {
                "id": str(u.id),
                "email": u.email,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "role_names": [r.name for r in u.roles],
            }
            for u in users
        ],
        "total": len(users),
    }


# ── Permission catalog ───────────────────────────────────────────────────────
@router.get(
    "/permissions",
    summary="List the full permission catalog, grouped by category",
)
async def list_permissions(
    current_user: User = Depends(require_permission("roles.manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(Permission).order_by(Permission.category, Permission.label))
    permissions = result.scalars().all()

    grouped: dict[str, list[PermissionSchema]] = defaultdict(list)
    for p in permissions:
        grouped[p.category].append(PermissionSchema.model_validate(p))

    return {
        "categories": [
            {"category": category, "permissions": perms}
            for category, perms in grouped.items()
        ],
        "total": len(permissions),
    }


# ── Roles CRUD ────────────────────────────────────────────────────────────
@router.get("", summary="List this organization's custom roles")
async def list_roles(
    current_user: User = Depends(require_permission("roles.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Role)
        .where(Role.organization_id == tenant_id)
        .order_by(Role.display_order, Role.name)
    )
    roles = result.scalars().all()
    return {"items": [await _role_response(db, r) for r in roles], "total": len(roles)}


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a custom role")
async def create_role(
    body: RoleCreateRequest,
    current_user: User = Depends(require_permission("roles.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> RoleResponse:
    slug = _slugify(body.name)
    existing = (
        await db.execute(
            select(Role).where(Role.organization_id == tenant_id, Role.slug == slug)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(f"A role named '{body.name}' already exists")

    permissions = await _resolve_permissions(db, body.permission_codenames)

    role = Role(
        organization_id=tenant_id,
        name=body.name,
        slug=slug,
        description=body.description,
        color=body.color,
        is_system=False,  # nothing created through this API is ever a system role
        is_super=body.is_super,
    )
    db.add(role)
    await db.flush()
    # Same reasoning as the seed script / AuthService fix: `role` was
    # just constructed and flushed, never queried, so its `permissions`
    # collection is unloaded. Appending to it would trigger an implicit
    # lazy-load outside an awaited context (`MissingGreenlet`). Insert
    # into the association table directly instead.
    if permissions:
        from app.models.rbac import role_permissions
        await db.execute(
            role_permissions.insert(),
            [{"role_id": role.id, "permission_id": p.id} for p in permissions],
        )
    await db.flush()
    # The raw insert() above bypasses the ORM, so SQLAlchemy has no idea
    # `role.permissions` changed — an explicit refresh is needed or the
    # collection stays "unloaded", and the first read of it (in
    # `_role_response` -> `role.permission_codenames`) lazy-loads outside
    # an awaited context, same class of bug as above.
    await db.refresh(role, attribute_names=["permissions"])
    return await _role_response(db, role)


@router.get("/{role_id}", summary="Get a role's detail")
async def get_role(
    role_id: uuid.UUID,
    current_user: User = Depends(require_permission("roles.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> RoleResponse:
    role = (
        await db.execute(
            select(Role).where(Role.id == role_id, Role.organization_id == tenant_id)
        )
    ).scalar_one_or_none()
    if role is None:
        raise NotFoundError("Role not found")
    return await _role_response(db, role)


@router.patch("/{role_id}", summary="Update a role's name, color, or permissions")
async def update_role(
    role_id: uuid.UUID,
    body: RoleUpdateRequest,
    current_user: User = Depends(require_permission("roles.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> RoleResponse:
    role = (
        await db.execute(
            select(Role).where(Role.id == role_id, Role.organization_id == tenant_id)
        )
    ).scalar_one_or_none()
    if role is None:
        raise NotFoundError("Role not found")

    if body.name is not None and body.name != role.name:
        new_slug = _slugify(body.name)
        clash = (
            await db.execute(
                select(Role).where(
                    Role.organization_id == tenant_id,
                    Role.slug == new_slug,
                    Role.id != role.id,
                )
            )
        ).scalar_one_or_none()
        if clash is not None:
            raise ConflictError(f"A role named '{body.name}' already exists")
        role.name = body.name
        role.slug = new_slug

    if body.description is not None:
        role.description = body.description
    if body.color is not None:
        role.color = body.color
    if body.is_super is not None:
        role.is_super = body.is_super
    if body.permission_codenames is not None:
        permissions = await _resolve_permissions(db, body.permission_codenames)
        role.permissions = permissions

    await db.flush()
    return await _role_response(db, role)


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a role")
async def delete_role(
    role_id: uuid.UUID,
    current_user: User = Depends(require_permission("roles.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    role = (
        await db.execute(
            select(Role).where(Role.id == role_id, Role.organization_id == tenant_id)
        )
    ).scalar_one_or_none()
    if role is None:
        raise NotFoundError("Role not found")

    user_count = (
        await db.execute(
            select(func.count())
            .select_from(user_roles)
            .where(user_roles.c.role_id == role.id)
        )
    ).scalar_one()
    if user_count > 0:
        raise ConflictError(
            f"Cannot delete this role — {user_count} user(s) are still assigned to it. "
            "Unassign them first."
        )

    await db.delete(role)
    await db.flush()


# ── User ↔ Role assignment ───────────────────────────────────────────────────
@router.post(
    "/{role_id}/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Assign a role to a user",
)
async def assign_role(
    role_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(require_permission("roles.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    role = (
        await db.execute(
            select(Role).where(Role.id == role_id, Role.organization_id == tenant_id)
        )
    ).scalar_one_or_none()
    if role is None:
        raise NotFoundError("Role not found")

    target = (
        await db.execute(
            select(User).where(User.id == user_id, User.organization_id == tenant_id)
        )
    ).scalar_one_or_none()
    if target is None:
        raise NotFoundError("User not found in this organization")

    if role not in target.roles:
        target.roles.append(role)
        await db.flush()


@router.delete(
    "/{role_id}/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a role from a user",
)
async def unassign_role(
    role_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(require_permission("roles.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    role = (
        await db.execute(
            select(Role).where(Role.id == role_id, Role.organization_id == tenant_id)
        )
    ).scalar_one_or_none()
    if role is None:
        raise NotFoundError("Role not found")

    target = (
        await db.execute(
            select(User).where(User.id == user_id, User.organization_id == tenant_id)
        )
    ).scalar_one_or_none()
    if target is None:
        raise NotFoundError("User not found in this organization")

    if role in target.roles:
        target.roles.remove(role)
        await db.flush()


@router.get("/{role_id}/users", summary="List users assigned to a role")
async def list_role_users(
    role_id: uuid.UUID,
    current_user: User = Depends(require_permission("roles.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    role = (
        await db.execute(
            select(Role).where(Role.id == role_id, Role.organization_id == tenant_id)
        )
    ).scalar_one_or_none()
    if role is None:
        raise NotFoundError("Role not found")

    return {
        "items": [
            {
                "id": str(u.id),
                "email": u.email,
                "first_name": u.first_name,
                "last_name": u.last_name,
            }
            for u in role.users
        ],
        "total": len(role.users),
    }
