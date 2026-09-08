#!/usr/bin/env python3
"""
EWMP Management CLI.

Usage:
    python manage.py seed --permissions   # Seed all permissions
    python manage.py seed --superadmin    # Create platform super admin
    python manage.py seed --all           # Seed everything
"""

import asyncio
import argparse
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

# Windows uses ProactorEventLoop by default, which asyncpg (especially on
# newer Python builds) doesn't reliably support for connection teardown —
# it surfaces as "RuntimeError: Event loop is closed" / "'NoneType' object
# has no attribute 'send'" right when a query tries to open a connection.
# SelectorEventLoop doesn't have this problem and is what asyncpg expects.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def seed_permissions() -> None:
    """Seed all permission records from the registry."""
    from app.core.database import AsyncSessionLocal
    from app.models.rbac import Permission
    from app.database.seeds.permissions import PERMISSION_REGISTRY, get_codename
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        for perm_data in PERMISSION_REGISTRY:
            codename = get_codename(perm_data["resource"], perm_data["action"])
            existing = await db.execute(select(Permission).where(Permission.codename == codename))
            if existing.scalar_one_or_none():
                continue
            perm = Permission(
                resource=perm_data["resource"],
                action=perm_data["action"],
                codename=codename,
                label=perm_data["label"],
                category=perm_data["category"],
                is_sensitive=perm_data.get("is_sensitive", False),
            )
            db.add(perm)
        await db.commit()
        print(f"✅ Seeded {len(PERMISSION_REGISTRY)} permissions")


async def seed_superadmin() -> None:
    """
    Create the platform super admin user, inside its own bootstrap org,
    with the one seeded system role assigned.

    "No user without a role": is_platform_admin=True already bypasses
    every permission check, but the super admin still gets a real Role
    row too — this is the ONE role ever created by seeding, and this is
    the only user it's ever assigned to.
    """
    from app.core.database import AsyncSessionLocal
    from app.core.config import settings
    from app.core.security import hash_password
    from app.models.user import User
    from app.models.organization import Organization
    from app.database.seeds.default_roles import seed_platform_super_admin_role
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        existing = await db.execute(
            select(User).where(User.email_normalized == settings.SUPER_ADMIN_EMAIL.lower())
        )
        if existing.scalar_one_or_none():
            print("ℹ️  Super admin already exists")
            return

        # organization_id is NOT NULL on every user — even the platform
        # super admin belongs to a real org (their own "Platform
        # Operations" org), rather than floating outside any tenant.
        org_slug = "platform-operations"
        existing_org = await db.execute(
            select(Organization).where(Organization.slug == org_slug)
        )
        org = existing_org.scalar_one_or_none()
        if org is None:
            org = Organization(
                name="Platform Operations",
                slug=org_slug,
                email=settings.SUPER_ADMIN_EMAIL,
                is_active=True,
                is_trial=False,
            )
            db.add(org)
            await db.flush()

        admin = User(
            organization_id=org.id,
            email=settings.SUPER_ADMIN_EMAIL,
            email_normalized=settings.SUPER_ADMIN_EMAIL.lower(),
            password_hash=hash_password(settings.SUPER_ADMIN_PASSWORD),
            first_name="Platform",
            last_name="Admin",
            is_active=True,
            is_email_verified=True,
            is_platform_admin=True,
        )
        db.add(admin)
        await db.flush()

        system_role = await seed_platform_super_admin_role(db, org.id)

        # NOTE: deliberately NOT `admin.roles.append(system_role)` here.
        # `admin` was just flushed (not committed), so its `roles`
        # collection is unloaded; appending to it triggers an implicit
        # lazy-load, which AsyncSession cannot service outside an awaited
        # context and raises `sqlalchemy.exc.MissingGreenlet`. Inserting
        # into the association table directly sidesteps the relationship
        # loader entirely — this is the standard pattern for async
        # SQLAlchemy relationships that aren't configured with an
        # async-safe eager loader (e.g. `lazy="selectin"`).
        from app.models.user import user_roles as user_roles_table
        await db.execute(
            user_roles_table.insert().values(user_id=admin.id, role_id=system_role.id)
        )
        await db.flush()

        org.owner_id = admin.id
        await db.commit()
        print(f"✅ Super admin created: {settings.SUPER_ADMIN_EMAIL}")


def main() -> None:
    parser = argparse.ArgumentParser(description="EWMP Management CLI")
    parser.add_argument("command", choices=["seed"])
    parser.add_argument("--permissions", action="store_true")
    parser.add_argument("--superadmin", action="store_true")
    parser.add_argument("--all", action="store_true", dest="all_")

    args = parser.parse_args()

    if args.command == "seed":
        async def _run_seeds() -> None:
            # Both seed steps must share the SAME event loop: the global
            # async engine's connection pool is tied to whichever loop
            # first opened a connection. Two separate asyncio.run() calls
            # each spin up a brand-new loop, and the second call then tries
            # to reuse a pooled asyncpg connection that belongs to the
            # first (now-closed) loop -> "attached to a different loop".
            if args.all_ or args.permissions:
                await seed_permissions()
            if args.all_ or args.superadmin:
                await seed_superadmin()

        if args.all_ or args.permissions or args.superadmin:
            asyncio.run(_run_seeds())
        else:
            print("Specify --permissions, --superadmin, or --all")


if __name__ == "__main__":
    main()
