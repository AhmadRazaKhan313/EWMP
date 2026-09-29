"""
Regression tests for audit finding C-1: privilege escalation through the
employee endpoints.

Before the fix:
  * POST /employees needed only `employees.create` and accepted ANY role of
    the org — including the seeded Owner role (is_super=True). The creator got
    the new account's temporary password in the response, i.e. a full-access
    login of their own.
  * PATCH /employees/{id} with role_id needed `roles.manage` but skipped the
    `is_super` / "can't grant what you don't hold" guards that
    POST /roles/{id}/users/{uid} enforces, and could silently strip a super
    role from a higher-privileged user.

These go through the real HTTP stack (auth dependency, permission checks,
router, service) against a live Postgres — same TEST_DATABASE_URL convention
as the other *_postgres tests in this folder (migrations must be applied).
Permission rows are created if missing (a fresh DB has none until
`python manage.py seed`), and left in place — they are global reference data.
"""

import os
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.employee import Employee
from app.models.organization import Organization
from app.models.rbac import Permission, Role
from app.models.user import User

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp",
)

pytestmark = pytest.mark.asyncio

HR_PERMISSIONS = ["employees.view", "employees.create", "employees.update", "roles.manage"]


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(DATABASE_URL)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def client(engine):
    """The real app, with get_db bound to the test database (same
    commit-at-end / rollback-on-error behavior as app.core.database.get_db)."""

    async def _get_db():
        async with AsyncSession(engine, expire_on_commit=False, autoflush=False) as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _get_db
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


async def _permission(session: AsyncSession, codename: str) -> Permission:
    perm = (
        await session.execute(select(Permission).where(Permission.codename == codename))
    ).scalar_one_or_none()
    if perm is None:
        resource, action = codename.split(".", 1)
        perm = Permission(
            resource=resource, action=action, codename=codename,
            label=codename, category=resource,
        )
        session.add(perm)
        await session.flush()
    return perm


def _user(org_id, roles, email_prefix):
    email = f"{email_prefix}-{uuid.uuid4().hex[:8]}@example.com"
    return User(
        organization_id=org_id, email=email, email_normalized=email,
        password_hash="x", first_name=email_prefix, last_name="Test",
        is_active=True, is_email_verified=True, roles=roles,
    )


@pytest_asyncio.fixture
async def org(engine):
    """An org with: owner, an HR delegate, a second super-user ("cofounder"),
    and roles Owner (super) / HR / Staff (subset of HR) / Payroll Approver
    (a permission HR does NOT hold)."""
    org_id = uuid.uuid4()
    ids = {"org": org_id}
    async with AsyncSession(engine, expire_on_commit=False) as s:
        s.add(Organization(
            id=org_id, name="Escalation Test Org", slug=f"esc-{org_id.hex[:8]}",
            email=f"esc-{org_id.hex[:8]}@example.com",
        ))
        await s.flush()

        hr_perms = [await _permission(s, c) for c in HR_PERMISSIONS]
        owner_role = Role(organization_id=org_id, name="Owner", slug="owner",
                          is_system=True, is_super=True)
        hr_role = Role(organization_id=org_id, name="HR", slug="hr", permissions=hr_perms)
        staff_role = Role(organization_id=org_id, name="Staff", slug="staff",
                          permissions=[await _permission(s, "employees.view")])
        payroll_role = Role(organization_id=org_id, name="Payroll Approver", slug="payroll-approver",
                            permissions=[await _permission(s, "payroll.approve")])
        s.add_all([owner_role, hr_role, staff_role, payroll_role])
        await s.flush()

        owner = _user(org_id, [owner_role], "owner")
        hr = _user(org_id, [hr_role], "hr")
        cofounder = _user(org_id, [owner_role], "cofounder")
        s.add_all([owner, hr, cofounder])
        await s.flush()
        (await s.get(Organization, org_id)).owner_id = owner.id

        ids.update(
            owner=owner.id, hr=hr.id, cofounder=cofounder.id,
            owner_role=owner_role.id, hr_role=hr_role.id,
            staff_role=staff_role.id, payroll_role=payroll_role.id,
        )
        await s.commit()

    yield ids

    async with AsyncSession(engine) as s:
        await s.execute(delete(Employee).where(Employee.tenant_id == org_id))
        await s.execute(delete(User).where(User.organization_id == org_id))
        await s.execute(delete(Role).where(Role.organization_id == org_id))
        await s.execute(delete(Organization).where(Organization.id == org_id))
        await s.commit()


def _auth(user_id) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


def _new_employee(role_id) -> dict:
    return {
        "first_name": "New", "last_name": "Hire",
        "email": f"new-{uuid.uuid4().hex[:8]}@example.com",
        "date_of_joining": "2026-01-01", "role_id": str(role_id),
    }


async def _user_count(engine, org_id) -> int:
    async with AsyncSession(engine) as s:
        return (await s.execute(
            select(func.count()).select_from(User).where(User.organization_id == org_id)
        )).scalar_one()


async def _employee_for(engine, user_id) -> uuid.UUID:
    """Create an Employee row for an existing user (owner-authored setup)."""
    async with AsyncSession(engine) as s:
        from datetime import date

        from app.models.employee import EmploymentStatus, EmploymentType
        emp = Employee(
            tenant_id=(await s.get(User, user_id)).organization_id, user_id=user_id,
            employee_code=f"T-{uuid.uuid4().hex[:6]}",
            employment_type=EmploymentType.FULL_TIME,
            employment_status=EmploymentStatus.ACTIVE, date_of_joining=date(2026, 1, 1),
        )
        s.add(emp)
        await s.flush()
        emp_id = emp.id  # capture before commit expires the ORM object's attributes
        await s.commit()
        return emp_id


async def _role_ids_of(engine, user_id) -> set[uuid.UUID]:
    async with AsyncSession(engine) as s:
        from app.repositories.user import UserRepository
        user = await UserRepository(s).get_with_roles(user_id)
        return {r.id for r in user.roles}


# ── POST /employees ──────────────────────────────────────────────────────────

class TestCreateEmployeeRoleGuards:
    async def test_delegate_cannot_create_an_owner_account(self, client, engine, org):
        """THE escalation: HR creating a login that holds the super Owner role."""
        before = await _user_count(engine, org["org"])
        r = await client.post("/api/v1/employees", json=_new_employee(org["owner_role"]),
                              headers=_auth(org["hr"]))
        assert r.status_code == 403, r.text
        assert await _user_count(engine, org["org"]) == before, "no account may be left behind"

    async def test_delegate_cannot_grant_permissions_they_lack(self, client, org):
        r = await client.post("/api/v1/employees", json=_new_employee(org["payroll_role"]),
                              headers=_auth(org["hr"]))
        assert r.status_code == 403, r.text
        assert "payroll.approve" in r.text

    async def test_delegate_can_assign_a_role_within_their_own_permissions(self, client, org):
        r = await client.post("/api/v1/employees", json=_new_employee(org["staff_role"]),
                              headers=_auth(org["hr"]))
        assert r.status_code == 201, r.text
        assert r.json()["temporary_password"]

    async def test_owner_can_create_an_owner_account(self, client, org):
        r = await client.post("/api/v1/employees", json=_new_employee(org["owner_role"]),
                              headers=_auth(org["owner"]))
        assert r.status_code == 201, r.text


# ── PATCH /employees/{id} ────────────────────────────────────────────────────

class TestUpdateEmployeeRoleGuards:
    async def test_delegate_cannot_promote_to_super(self, client, engine, org):
        emp_id = await _employee_for(engine, org["hr"])  # HR editing their own record
        r = await client.patch(f"/api/v1/employees/{emp_id}",
                               json={"role_id": str(org["owner_role"])}, headers=_auth(org["hr"]))
        assert r.status_code == 403, r.text
        assert await _role_ids_of(engine, org["hr"]) == {org["hr_role"]}

    async def test_delegate_cannot_promote_to_role_with_unheld_permissions(self, client, engine, org):
        emp_id = await _employee_for(engine, org["hr"])
        r = await client.patch(f"/api/v1/employees/{emp_id}",
                               json={"role_id": str(org["payroll_role"])}, headers=_auth(org["hr"]))
        assert r.status_code == 403, r.text

    async def test_delegate_cannot_strip_a_super_role(self, client, engine, org):
        """Replacing the cofounder's Owner role with Staff is a demotion of a
        full-access user — as privileged as granting one."""
        emp_id = await _employee_for(engine, org["cofounder"])
        r = await client.patch(f"/api/v1/employees/{emp_id}",
                               json={"role_id": str(org["staff_role"])}, headers=_auth(org["hr"]))
        assert r.status_code == 403, r.text
        assert await _role_ids_of(engine, org["cofounder"]) == {org["owner_role"]}

    async def test_delegate_can_change_between_roles_they_may_grant(self, client, engine, org):
        created = await client.post("/api/v1/employees", json=_new_employee(org["staff_role"]),
                                    headers=_auth(org["owner"]))
        emp_id = created.json()["id"]
        r = await client.patch(f"/api/v1/employees/{emp_id}",
                               json={"role_id": str(org["hr_role"])}, headers=_auth(org["hr"]))
        assert r.status_code == 200, r.text

    async def test_owner_can_demote_a_super_user(self, client, engine, org):
        emp_id = await _employee_for(engine, org["cofounder"])
        r = await client.patch(f"/api/v1/employees/{emp_id}",
                               json={"role_id": str(org["staff_role"])}, headers=_auth(org["owner"]))
        assert r.status_code == 200, r.text
        assert await _role_ids_of(engine, org["cofounder"]) == {org["staff_role"]}


# ── /roles endpoints still guarded after the helpers moved ──────────────────

class TestRolesEndpointUnchanged:
    async def test_delegate_still_cannot_assign_super_via_roles_api(self, client, org):
        r = await client.post(f"/api/v1/roles/{org['owner_role']}/users/{org['hr']}",
                              headers=_auth(org["hr"]))
        assert r.status_code == 403, r.text

    async def test_delegate_still_cannot_grant_unheld_permissions_via_roles_api(self, client, org):
        r = await client.post(f"/api/v1/roles/{org['payroll_role']}/users/{org['hr']}",
                              headers=_auth(org["hr"]))
        assert r.status_code == 403, r.text
