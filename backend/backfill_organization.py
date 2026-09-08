"""
Run this ONCE, BEFORE applying the new migration that makes
users.organization_id NOT NULL.

Why: organization_id used to be nullable (only the platform super admin
used the NULL case). The new design requires every user — including the
platform super admin — to belong to a real organization. This script
finds any user with organization_id IS NULL, creates a "Platform
Operations" bootstrap org if one doesn't already exist, and points them
at it. Safe to run multiple times — it's a no-op once there's nothing
left to backfill.

Usage (from the backend/ folder, with your venv active):
    python backfill_organization.py
"""
import asyncio


async def main() -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.user import User
    from app.models.organization import Organization
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        orphans = (
            await db.execute(select(User).where(User.organization_id.is_(None)))
        ).scalars().all()

        if not orphans:
            print("✅ No users with a missing organization_id — nothing to backfill.")
            return

        print(f"Found {len(orphans)} user(s) with no organization_id:")
        for u in orphans:
            print(f"  - {u.email}")

        org_slug = "platform-operations"
        existing_org = (
            await db.execute(select(Organization).where(Organization.slug == org_slug))
        ).scalar_one_or_none()

        if existing_org is None:
            org = Organization(
                name="Platform Operations",
                slug=org_slug,
                email=orphans[0].email,
                is_active=True,
                is_trial=False,
            )
            db.add(org)
            await db.flush()
            print(f"Created bootstrap organization '{org.name}' ({org.id})")
        else:
            org = existing_org
            print(f"Using existing bootstrap organization '{org.name}' ({org.id})")

        for u in orphans:
            u.organization_id = org.id

        if org.owner_id is None:
            # Prefer a platform admin as the owner if one is among the orphans
            platform_admins = [u for u in orphans if u.is_platform_admin]
            org.owner_id = (platform_admins[0] if platform_admins else orphans[0]).id

        await db.commit()
        print(f"✅ Backfilled {len(orphans)} user(s) into '{org.name}'.")
        print("You can now safely run: alembic revision --autogenerate -m \"...\" && alembic upgrade head")


if __name__ == "__main__":
    asyncio.run(main())
