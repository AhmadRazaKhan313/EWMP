"""
The ONE seeded role in this entire system.

Every user must have an organization (organization_id is NOT NULL) — no
exceptions. Extending that same principle, the platform super admin
(created once via `manage.py seed --superadmin`) must also have a real
Role row, not just the `is_platform_admin` boolean — no user should be
"role-less" in the database, even the one whose access is really driven
by the boolean flag.

This is the only role ever created by seeding. Every organization that
signs up afterwards starts with ZERO roles — its owner has full access
to their own org via the owner-bypass in `User.has_permission`
(`organization.owner_id == user.id`), not because of any pre-created
role. Org admins build their own role list entirely through the Roles
API. Nothing here is duplicated per-org.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rbac import Role

SYSTEM_ROLE_SLUG = "platform-super-admin"


async def seed_platform_super_admin_role(db: AsyncSession, org_id: UUID) -> Role:
    """
    Create (or fetch, if already seeded) the single system role, scoped to
    the bootstrap "Platform Operations" organization. Idempotent — safe to
    call on every `manage.py seed --superadmin` run.
    """
    existing = (
        await db.execute(
            select(Role).where(
                Role.organization_id == org_id, Role.slug == SYSTEM_ROLE_SLUG
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    role = Role(
        organization_id=org_id,
        name="Platform Super Admin",
        slug=SYSTEM_ROLE_SLUG,
        description="The one seeded role in the system, held by the platform operator.",
        color="#7C3AED",
        is_system=True,
        is_super=True,
        display_order=0,
    )
    db.add(role)
    await db.flush()
    return role
