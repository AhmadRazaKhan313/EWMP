"""
Admin setup endpoint - assign platform admin to an organization.
This is called once during initial setup.
"""
import uuid
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, EmailStr

from app.core.database import get_db
from app.core.security import hash_password
from app.models.user import User
from app.models.organization import Organization
from app.permissions.dependencies import get_current_user, require_platform_admin

router = APIRouter(prefix="/admin", tags=["Platform Admin"])


class CreateOrgWithAdmin(BaseModel):
    org_name: str
    org_slug: str
    email: str
    timezone: str = "UTC"
    country: str = ""


class CreateOrganizationRequest(BaseModel):
    """Unlike CreateOrgWithAdmin above (bootstrap-only: assigns the
    *calling* platform admin as the org's user), this creates an
    independent organization that needs its own, separate login — so it
    needs the new owner's name/email to actually create that account."""
    org_name: str
    org_slug: str
    owner_first_name: str
    owner_last_name: str
    owner_email: EmailStr
    timezone: str = "UTC"
    country: str = ""


@router.post("/setup-org", summary="Create org and assign platform admin to it")
async def setup_organization(
    data: CreateOrgWithAdmin,
    current_user: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Platform admin creates their first organization and gets assigned to it.
    Call this once after first login to set up the workspace.

    Guarded against re-runs: without this check, calling it a second time
    created a *second* Organization and silently reassigned the admin to
    it — every employee created under the first org would vanish from the
    admin's view (they'd still exist, just under an org nothing points to
    anymore), while email-uniqueness checks are global and would still
    correctly report "already exists" for those same employees. That
    mismatch — empty list vs. "already added" — is exactly what re-running
    this endpoint produces.
    """
    from datetime import UTC, datetime, timedelta
    from app.core.exceptions import ConflictError, SlugAlreadyExistsError

    if current_user.organization_id is not None:
        raise ConflictError(
            "This admin account is already assigned to an organization. "
            "Re-running setup would orphan your existing data under it. "
            "If you need a second organization, use the org switcher "
            "(X-Tenant-ID) instead of admin setup."
        )

    # Check slug uniqueness
    existing = await db.execute(select(Organization).where(Organization.slug == data.org_slug))
    if existing.scalar_one_or_none():
        raise SlugAlreadyExistsError(f"Slug '{data.org_slug}' already taken")

    # Create org
    org = Organization(
        name=data.org_name,
        slug=data.org_slug,
        email=data.email,
        timezone=data.timezone,
        country=data.country or None,
        is_trial=True,
        trial_ends_at=datetime.now(UTC) + timedelta(days=365),
        is_active=True,
    )
    db.add(org)
    await db.flush()

    # Assign admin to this org
    current_user.organization_id = org.id
    org.owner_id = current_user.id
    await db.flush()

    # No role is created here — there is no seeded/default role anywhere
    # in this system. current_user.is_platform_admin already bypasses
    # every check, and org.owner_id also grants them full access to this
    # specific org via the owner-bypass in User.has_permission.

    return {
        "message": "Organization created and admin assigned",
        "org_id": str(org.id),
        "org_slug": org.slug,
        "org_name": org.name,
    }


@router.post("/organizations", summary="Create a new organization (platform admin only)")
async def create_organization(
    data: CreateOrganizationRequest,
    current_user: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Onboard a brand-new tenant organization — WITH an actual owner account,
    not just an empty Organization row.

    Bug fix: this used to create only the Organization and leave
    `owner_id` NULL forever. That org then had no user who could ever log
    into it — `require_platform_admin` correctly keeps every other
    endpoint on this router restricted to the one platform-admin account,
    but that same admin's own login is permanently tied to their own org
    (see /admin/setup-org and /admin/switch-organization above); nothing
    else was ever created that a human could actually sign in as for the
    *new* org. This now creates that owner User in the same transaction,
    the same way a self-service /auth/register signup gets one, and
    returns a one-time temporary password (mirrors
    /auth/register-employee's pattern in onboarding.py) for the platform
    admin to hand off out-of-band. The owner logs in normally via
    POST /auth/login with owner_email + that password, same as any other
    user — nothing special about this account beyond how it was created.

    Unlike `/admin/setup-org` above — which exists purely to bootstrap the
    platform admin's *own* org once, and reassigns them into it — this does
    NOT touch `current_user.organization_id`. The platform admin stays put
    in their own org (e.g. "Platform Operations") and can call this
    endpoint any number of times to spin up additional tenant orgs, each
    with its own independent owner login. Gated by `require_platform_admin`
    the same as every endpoint on this router, so — matching the "no user
    is ever outside an organization" rule — this is never reachable by a
    regular org's Owner, only by the one platform-admin account.
    """
    from datetime import UTC, datetime, timedelta
    from app.core.exceptions import EmailAlreadyExistsError, SlugAlreadyExistsError
    from app.core.security import generate_password_reset_token
    from app.services.auth import AuthService
    from app.models.user import user_roles as user_roles_table

    existing_slug = await db.execute(select(Organization).where(Organization.slug == data.org_slug))
    if existing_slug.scalar_one_or_none():
        raise SlugAlreadyExistsError(f"Slug '{data.org_slug}' already taken")

    existing_email = await db.execute(
        select(User).where(User.email_normalized == data.owner_email.lower())
    )
    if existing_email.scalar_one_or_none():
        raise EmailAlreadyExistsError(f"An account with email {data.owner_email} already exists")

    # Create the new tenant
    org = Organization(
        name=data.org_name,
        slug=data.org_slug,
        email=data.owner_email,
        timezone=data.timezone,
        country=data.country or None,
        is_trial=True,
        trial_ends_at=datetime.now(UTC) + timedelta(days=365),
        is_active=True,
    )
    db.add(org)
    await db.flush()

    # Same four system roles a self-service /auth/register signup gets
    # (Owner/Admin/HR Manager/Employee) — this org's owner needs a real
    # "Owner" (is_super) Role row like any other org's owner, since it
    # doesn't have the platform-wide `is_platform_admin` bypass (that
    # stays unique to the org-1 account).
    owner_role = await AuthService(db)._seed_default_roles(org.id)

    temp_password = generate_password_reset_token()[:12] + "Aa1!"
    owner = User(
        organization_id=org.id,
        email=data.owner_email,
        email_normalized=data.owner_email.lower().strip(),
        password_hash=hash_password(temp_password),
        first_name=data.owner_first_name,
        last_name=data.owner_last_name,
        is_active=True,
        is_email_verified=False,
    )
    db.add(owner)
    await db.flush()

    await db.execute(
        user_roles_table.insert().values(user_id=owner.id, role_id=owner_role.id)
    )

    org.owner_id = owner.id
    await db.flush()

    return {
        "message": f'Organization "{org.name}" created',
        "org_id": str(org.id),
        "org_slug": org.slug,
        "org_name": org.name,
        "owner_email": owner.email,
        "owner_temporary_password": temp_password,
    }


@router.get("/organizations", summary="List all organizations (platform admin only)")
async def list_organizations(
    current_user: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Recovery/visibility tool: if setup-org was ever called more than once
    before the guard above existed, this is how to find the organization
    your actual data (employees, etc.) is sitting under, and how many
    employees each org has so you can tell which one is the "real" one.
    """
    from app.models.employee import Employee

    orgs = (await db.execute(select(Organization).order_by(Organization.created_at))).scalars().all()
    result = []
    for org in orgs:
        count = (
            await db.execute(
                select(func.count()).select_from(Employee).where(
                    Employee.tenant_id == org.id, Employee.is_deleted == False  # noqa: E712
                )
            )
        ).scalar_one()
        result.append({
            "id": str(org.id),
            "name": org.name,
            "slug": org.slug,
            "created_at": str(org.created_at),
            "is_current": org.id == current_user.organization_id,
            "employee_count": count,
        })
    return {"organizations": result}


@router.post("/switch-organization/{org_id}", summary="Reassign this admin account to a different organization")
async def switch_organization(
    org_id: uuid.UUID,
    current_user: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The actual fix for the empty-employee-list problem: point the admin
    back at whichever organization its employees actually live under."""
    org = (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    if org is None:
        from app.core.exceptions import NotFoundError
        raise NotFoundError(f"Organization {org_id} not found")

    current_user.organization_id = org.id
    await db.flush()
    return {"organization_id": str(org.id), "organization_name": org.name}


@router.get("/me", summary="Platform admin info")
async def admin_info(
    current_user: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    org = None
    if current_user.organization_id:
        result = await db.execute(select(Organization).where(Organization.id == current_user.organization_id))
        org = result.scalar_one_or_none()
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "is_platform_admin": True,
        "organization_id": str(current_user.organization_id) if current_user.organization_id else None,
        "organization_name": org.name if org else None,
        "organization_slug": org.slug if org else None,
        "has_organization": current_user.organization_id is not None,
    }