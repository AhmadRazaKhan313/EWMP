"""
Regression tests for audit finding H-16: reimbursement claims could be filed
for ANY employee by ANY logged-in user.

POST /payroll/reimbursements used to take `employee_id` straight from the
request body with only `get_current_user` — no self-scope, no permission,
not even a tenant check. Anyone could create money claims in a colleague's
name (or reference another organisation's employee), and once approved they
flowed into net pay. Employees also had no way to list their own claims.

These go through the real HTTP stack against a live Postgres — same
TEST_DATABASE_URL convention as the other *_postgres tests (migrations must
be applied). Permission rows are created if missing and left in place.
"""

import os
import uuid
from datetime import date

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.employee import Employee, EmploymentStatus, EmploymentType
from app.models.organization import Organization
from app.models.payroll import PayrollReimbursement
from app.models.rbac import Permission, Role
from app.models.user import User

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp",
)

pytestmark = pytest.mark.asyncio

URL = "/api/v1/payroll/reimbursements"


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(DATABASE_URL)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def client(engine):
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
        perm = Permission(resource=resource, action=action, codename=codename,
                          label=codename, category=resource)
        session.add(perm)
        await session.flush()
    return perm


async def _person(s, org_id, name, roles, with_employee=True):
    email = f"{name}-{uuid.uuid4().hex[:8]}@example.com"
    user = User(organization_id=org_id, email=email, email_normalized=email, password_hash="x",
                first_name=name, last_name="Test", is_active=True, is_email_verified=True, roles=roles)
    s.add(user)
    await s.flush()
    emp_id = None
    if with_employee:
        emp = Employee(tenant_id=org_id, user_id=user.id, employee_code=f"E-{uuid.uuid4().hex[:6]}",
                       employment_type=EmploymentType.FULL_TIME,
                       employment_status=EmploymentStatus.ACTIVE, date_of_joining=date(2026, 1, 1))
        s.add(emp)
        await s.flush()
        emp_id = emp.id
    return user.id, emp_id


async def _make_org(engine, label):
    org_id = uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        s.add(Organization(id=org_id, name=f"Reimb {label}", slug=f"reimb-{label}-{org_id.hex[:8]}",
                           email=f"reimb-{org_id.hex[:8]}@example.com"))
        await s.flush()
        payroll_admin = Role(organization_id=org_id, name="Payroll Admin", slug="payroll-admin",
                             permissions=[await _permission(s, "payroll.manage_structure")])
        s.add(payroll_admin)
        await s.flush()
        ids = {"org": org_id}
        ids["alice"], ids["alice_emp"] = await _person(s, org_id, "alice", [])
        ids["bob"], ids["bob_emp"] = await _person(s, org_id, "bob", [])
        ids["admin"], ids["admin_emp"] = await _person(s, org_id, "admin", [payroll_admin])
        ids["nolink"], _ = await _person(s, org_id, "nolink", [], with_employee=False)
        await s.commit()
    return ids


async def _drop_org(engine, org_id):
    async with AsyncSession(engine) as s:
        await s.execute(delete(PayrollReimbursement).where(PayrollReimbursement.tenant_id == org_id))
        await s.execute(delete(Employee).where(Employee.tenant_id == org_id))
        await s.execute(delete(User).where(User.organization_id == org_id))
        await s.execute(delete(Role).where(Role.organization_id == org_id))
        await s.execute(delete(Organization).where(Organization.id == org_id))
        await s.commit()


@pytest_asyncio.fixture
async def orgs(engine):
    a = await _make_org(engine, "a")
    b = await _make_org(engine, "b")
    yield a, b
    await _drop_org(engine, a["org"])
    await _drop_org(engine, b["org"])


def _auth(user_id) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


def _claim(**overrides) -> dict:
    body = {"category": "travel", "amount": "1500.00", "description": "Client visit"}
    body.update(overrides)
    return body


async def _claims_for(engine, employee_id) -> int:
    async with AsyncSession(engine) as s:
        return (await s.execute(
            select(func.count()).select_from(PayrollReimbursement)
            .where(PayrollReimbursement.employee_id == employee_id)
        )).scalar_one()


class TestWhoCanFileAClaim:
    async def test_employee_cannot_file_for_a_colleague(self, client, engine, orgs):
        """THE bug: Alice filing money claims in Bob's name."""
        a, _ = orgs
        r = await client.post(URL, json=_claim(employee_id=str(a["bob_emp"])), headers=_auth(a["alice"]))
        assert r.status_code == 403, r.text
        assert await _claims_for(engine, a["bob_emp"]) == 0

    async def test_employee_cannot_file_for_another_organisations_employee(self, client, engine, orgs):
        a, b = orgs
        r = await client.post(URL, json=_claim(employee_id=str(b["bob_emp"])), headers=_auth(a["alice"]))
        assert r.status_code == 403, r.text
        assert await _claims_for(engine, b["bob_emp"]) == 0

    async def test_even_a_payroll_admin_cannot_reach_another_organisation(self, client, engine, orgs):
        a, b = orgs
        r = await client.post(URL, json=_claim(employee_id=str(b["bob_emp"])), headers=_auth(a["admin"]))
        assert r.status_code == 404, r.text
        assert await _claims_for(engine, b["bob_emp"]) == 0

    async def test_employee_files_for_themselves_without_sending_an_id(self, client, orgs):
        a, _ = orgs
        r = await client.post(URL, json=_claim(), headers=_auth(a["alice"]))
        assert r.status_code == 201, r.text
        assert r.json()["employee_id"] == str(a["alice_emp"])

    async def test_employee_may_send_their_own_id(self, client, orgs):
        a, _ = orgs
        r = await client.post(URL, json=_claim(employee_id=str(a["alice_emp"])), headers=_auth(a["alice"]))
        assert r.status_code == 201, r.text

    async def test_payroll_admin_can_file_on_behalf_of_a_colleague(self, client, orgs):
        """The admin compensation page's flow keeps working."""
        a, _ = orgs
        r = await client.post(URL, json=_claim(employee_id=str(a["bob_emp"])), headers=_auth(a["admin"]))
        assert r.status_code == 201, r.text
        assert r.json()["employee_id"] == str(a["bob_emp"])

    async def test_user_without_employee_profile_gets_a_clear_error(self, client, orgs):
        a, _ = orgs
        r = await client.post(URL, json=_claim(), headers=_auth(a["nolink"]))
        assert r.status_code == 404, r.text
        assert r.json()["error"] == "EMPLOYEE_PROFILE_NOT_LINKED"


class TestClaimValidation:
    # These send the caller's own employee_id explicitly so they exercise the
    # URL/amount checks themselves (not the "which employee" rules above).

    @pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,<script>1</script>", "ftp://x/y"])
    async def test_receipt_url_must_be_http(self, client, orgs, url):
        a, _ = orgs
        r = await client.post(URL, json=_claim(employee_id=str(a["alice_emp"]), receipt_url=url), headers=_auth(a["alice"]))
        assert r.status_code == 422, r.text

    async def test_https_receipt_url_is_accepted(self, client, orgs):
        a, _ = orgs
        r = await client.post(URL, json=_claim(employee_id=str(a["alice_emp"]), receipt_url="https://drive.example.com/r.pdf"),
                              headers=_auth(a["alice"]))
        assert r.status_code == 201, r.text

    async def test_amount_too_large_for_the_column_is_a_422_not_a_500(self, client, orgs):
        a, _ = orgs
        r = await client.post(URL, json=_claim(employee_id=str(a["alice_emp"]), amount="99999999999999"), headers=_auth(a["alice"]))
        assert r.status_code == 422, r.text

    async def test_non_positive_amount_rejected(self, client, orgs):
        a, _ = orgs
        r = await client.post(URL, json=_claim(employee_id=str(a["alice_emp"]), amount="0"), headers=_auth(a["alice"]))
        assert r.status_code == 400, r.text


class TestMyReimbursements:
    async def test_lists_only_the_callers_own_claims(self, client, orgs):
        a, _ = orgs
        await client.post(URL, json=_claim(), headers=_auth(a["alice"]))
        await client.post(URL, json=_claim(), headers=_auth(a["bob"]))
        r = await client.get(f"{URL}/me", headers=_auth(a["alice"]))
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) == 1 and items[0]["employee_id"] == str(a["alice_emp"])

    async def test_admin_list_still_requires_payroll_view(self, client, orgs):
        a, _ = orgs
        r = await client.get(URL, headers=_auth(a["alice"]))
        assert r.status_code == 403, r.text
