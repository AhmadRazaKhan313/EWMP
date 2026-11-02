"""
B-04 payroll summary report, B-05 reimbursement reject guard, B-06 approve with
every level already signed. Real HTTP stack + live Postgres.
"""

import csv
import io
import os
import uuid
from datetime import date
from decimal import Decimal

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
from app.models.payroll import (
    ComponentCalculation, ComponentType, EmployeeSalary, PaymentBatch, PaymentBatchItem, PayrollApproval,
    PayrollApprovalLevel, PayrollAuditLog, PayrollItemSettlement, PayrollReimbursement, PayrollRun, PayrollSettings, PayrollSnapshot,
    Payslip, PayslipLine, SalaryComponent, SalaryStructure,
)
from app.models.rbac import Permission, Role
from app.models.user import User

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp",
)

pytestmark = pytest.mark.asyncio

SEPT = {"name": "September", "period_start": "2026-09-01", "period_end": "2026-09-30", "pay_date": "2026-09-30"}
PEOPLE = {
    # who: permissions
    # The processor DOES hold payroll.approve — so only the "you generated
    # it" rule can stop them approving their own run.
    "processor": ["payroll.process", "payroll.approve", "payroll.export", "payroll.finalize", "payroll.reverse",
                  "payroll.view", "payroll.manage_settings"],
    "hr": ["payroll.approve"],
    "finance": ["payroll.approve", "payroll.finalize"],
    "cfo": ["payroll.approve", "payroll.finalize"],
    "exporter": ["payroll.export"],
    "owner": [],  # full access as the organisation owner
}


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


async def _permission(s, codename):
    perm = (await s.execute(select(Permission).where(Permission.codename == codename))).scalar_one_or_none()
    if perm is None:
        resource, action = codename.split(".", 1)
        perm = Permission(resource=resource, action=action, codename=codename, label=codename, category=resource)
        s.add(perm)
        await s.flush()
    return perm


@pytest_asyncio.fixture
async def org(engine):
    """Six people (see PEOPLE) and two salaried employees at 100,000: Ali has
    a bank account (with a formula-looking title), Bina has none."""
    org_id = uuid.uuid4()
    ids = {"org": org_id}
    async with AsyncSession(engine, expire_on_commit=False) as s:
        s.add(Organization(id=org_id, name="Approvals Co", slug=f"appr-{org_id.hex[:8]}",
                           email=f"appr-{org_id.hex[:8]}@example.com"))
        await s.flush()
        for who, perms in PEOPLE.items():
            role = Role(organization_id=org_id, name=who, slug=who, permissions=[await _permission(s, p) for p in perms])
            email = f"{who}-{uuid.uuid4().hex[:8]}@example.com"
            u = User(organization_id=org_id, email=email, email_normalized=email, password_hash="x",
                     first_name=who, last_name="T", is_active=True, is_email_verified=True, roles=[role])
            s.add_all([role, u])
            await s.flush()
            ids[who] = u.id
        (await s.get(Organization, org_id)).owner_id = ids["owner"]
        structure = SalaryStructure(tenant_id=org_id, name="Std", code=f"S-{uuid.uuid4().hex[:6]}", is_active=True)
        s.add(structure)
        await s.flush()
        s.add(SalaryComponent(tenant_id=org_id, salary_structure_id=structure.id, name="Basic", code="BASIC",
                              component_type=ComponentType.EARNING, calculation_type=ComponentCalculation.FIXED,
                              amount=Decimal("100000"), display_order=1))
        for name, account, title in (("ali", "PK00BANK0001", "=HYPERLINK(\"http://x\")"), ("bina", None, None)):
            email = f"{name}-{uuid.uuid4().hex[:8]}@example.com"
            u = User(organization_id=org_id, email=email, email_normalized=email, password_hash="x",
                     first_name=name, last_name="T", is_active=True)
            s.add(u)
            await s.flush()
            e = Employee(tenant_id=org_id, user_id=u.id, employee_code=f"E-{uuid.uuid4().hex[:6]}",
                         employment_type=EmploymentType.FULL_TIME, employment_status=EmploymentStatus.ACTIVE,
                         date_of_joining=date(2020, 1, 1), bank_name="Test Bank",
                         bank_account_number=account, bank_account_title=title)
            s.add(e)
            await s.flush()
            s.add(EmployeeSalary(tenant_id=org_id, employee_id=e.id, salary_structure_id=structure.id,
                                 basic_salary=Decimal("100000"), effective_from=date(2020, 1, 1), is_current=True))
            ids[name] = e.id
        await s.commit()
    yield ids
    async with AsyncSession(engine) as s:
        for model in (PayrollReimbursement, PaymentBatchItem, PaymentBatch, PayrollItemSettlement, PayslipLine, Payslip, PayrollApproval,
                      PayrollApprovalLevel, PayrollSnapshot, PayrollAuditLog, PayrollRun, EmployeeSalary,
                      SalaryComponent, SalaryStructure, PayrollSettings, Employee):
            await s.execute(delete(model).where(model.tenant_id == org_id))
        await s.execute(delete(User).where(User.organization_id == org_id))
        await s.execute(delete(Role).where(Role.organization_id == org_id))
        await s.execute(delete(Organization).where(Organization.id == org_id))
        await s.commit()


def H(org, who):
    return {"Authorization": f"Bearer {create_access_token(str(org[who]))}"}


async def generated_run(client, org, by="processor") -> str:
    r = await client.post("/api/v1/payroll/runs", headers=H(org, by), json=SEPT)
    assert r.status_code == 201, r.text
    g = await client.post(f"/api/v1/payroll/runs/{r.json()['id']}/generate", headers=H(org, by))
    assert g.status_code == 200, g.text
    return r.json()["id"]


async def decide(client, org, run_id, who, decision="approved"):
    return await client.post(f"/api/v1/payroll/runs/{run_id}/approve", headers=H(org, who),
                             json={"decision": decision})


async def status_of(engine, run_id):
    async with AsyncSession(engine) as s:
        return (await s.get(PayrollRun, uuid.UUID(run_id))).status.value


async def add_levels(engine, org):
    async with AsyncSession(engine) as s:
        s.add(PayrollApprovalLevel(tenant_id=org["org"], name="HR review", level_order=1,
                                   required_permission="payroll.approve", is_active=True))
        s.add(PayrollApprovalLevel(tenant_id=org["org"], name="Finance sign-off", level_order=2,
                                   required_permission="payroll.finalize", is_active=True))
        await s.commit()


# ── B-06 ────────────────────────────────────────────────────────────────────

class TestApproveWithEveryLevelAlreadySigned:
    async def _signed_but_still_in_review(self, client, engine, org):
        await add_levels(engine, org)
        run = await generated_run(client, org)
        assert (await decide(client, org, run, "hr")).status_code == 200
        # The last level is switched off after HR signed: nobody is "waiting" any more.
        async with AsyncSession(engine) as s:
            lvl = (await s.execute(select(PayrollApprovalLevel).where(
                PayrollApprovalLevel.tenant_id == org["org"], PayrollApprovalLevel.name == "Finance sign-off"))).scalar_one()
            lvl.is_active = False
            await s.commit()
        assert await status_of(engine, run) == "review"
        return run

    async def test_approving_completes_the_run_instead_of_crashing(self, client, engine, org):
        run = await self._signed_but_still_in_review(client, engine, org)
        r = await decide(client, org, run, "cfo")
        assert r.status_code == 200, r.text            # used to be an IndexError -> 500
        assert r.json()["fully_approved"] is True
        assert await status_of(engine, run) == "approved"

    async def test_rejecting_still_sends_it_back_to_draft(self, client, engine, org):
        run = await self._signed_but_still_in_review(client, engine, org)
        r = await decide(client, org, run, "cfo", "rejected")
        assert r.status_code == 200, r.text
        assert await status_of(engine, run) == "draft"


# ── B-05 ────────────────────────────────────────────────────────────────────

class TestReimbursementReject:
    async def _claim(self, client, org):
        r = await client.post("/api/v1/payroll/reimbursements", headers=H(org, "owner"),
                              json={"employee_id": str(org["ali"]), "category": "fuel", "amount": "500", "description": "petrol"})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    async def test_submitted_claim_can_be_rejected_once(self, client, org):
        rid = await self._claim(client, org)
        ok = await client.post(f"/api/v1/payroll/reimbursements/{rid}/reject", headers=H(org, "hr"), json={"reason": "no receipt"})
        assert ok.status_code == 200 and ok.json()["status"] == "rejected"
        again = await client.post(f"/api/v1/payroll/reimbursements/{rid}/reject", headers=H(org, "hr"), json={"reason": "again"})
        assert again.status_code == 409

    async def test_approved_claim_cannot_be_rejected(self, client, engine, org):
        rid = await self._claim(client, org)
        assert (await client.post(f"/api/v1/payroll/reimbursements/{rid}/approve", headers=H(org, "hr"))).status_code == 200
        r = await client.post(f"/api/v1/payroll/reimbursements/{rid}/reject", headers=H(org, "hr"), json={"reason": "oops"})
        assert r.status_code == 409
        async with AsyncSession(engine) as s:
            assert (await s.get(PayrollReimbursement, uuid.UUID(rid))).status.value == "approved"

    async def test_paid_or_included_claim_cannot_be_rejected(self, client, engine, org):
        rid = await self._claim(client, org)
        for status in ("included_in_payroll", "paid"):
            async with AsyncSession(engine) as s:
                row = await s.get(PayrollReimbursement, uuid.UUID(rid))
                row.status = status
                await s.commit()
            r = await client.post(f"/api/v1/payroll/reimbursements/{rid}/reject", headers=H(org, "hr"), json={"reason": "x"})
            assert r.status_code == 409, status


# ── B-04 ────────────────────────────────────────────────────────────────────

class TestPayrollSummary:
    async def test_summary_totals_components_and_departments(self, client, org):
        run = await generated_run(client, org)
        r = await client.get(f"/api/v1/payroll/runs/{run}/summary", headers=H(org, "processor"))
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["run"]["name"] == "September" and d["run"]["status"] == "review"
        t = d["totals"]
        assert t["employee_count"] == 2
        assert Decimal(t["gross"]) == Decimal("200000")
        assert Decimal(t["net"]) == Decimal(t["gross"]) - Decimal(t["deductions"])
        basic = next(c for c in d["by_component"] if c["code"] == "BASIC")
        assert basic["type"] == "earning" and Decimal(basic["total"]) == Decimal("200000") and basic["employee_count"] == 2
        assert d["by_department"][0]["department_name"] == "No department" and d["by_department"][0]["employee_count"] == 2
        assert d["matches_run_totals"] is True
        assert set(d["attendance"]) == {"absent_days", "leave_days", "unpaid_leave_days", "overtime_hours"}

    async def test_summary_needs_payroll_view_and_csv_needs_export(self, client, org):
        run = await generated_run(client, org)
        assert (await client.get(f"/api/v1/payroll/runs/{run}/summary", headers=H(org, "exporter"))).status_code == 403
        assert (await client.get(f"/api/v1/payroll/runs/{run}/summary/csv", headers=H(org, "hr"))).status_code == 403
        ok = await client.get(f"/api/v1/payroll/runs/{run}/summary/csv", headers=H(org, "exporter"))
        assert ok.status_code == 200 and ok.headers["content-type"].startswith("text/csv")
        rows = list(csv.reader(io.StringIO(ok.text)))
        assert rows[0] == ["Payroll Summary", "September"]
        assert ["Employees", "2"] in rows and any(r[:1] == ["BASIC"] or (len(r) > 1 and r[1] == "BASIC") for r in rows)

    async def test_unknown_run_is_404(self, client, org):
        r = await client.get(f"/api/v1/payroll/runs/{uuid.uuid4()}/summary", headers=H(org, "processor"))
        assert r.status_code == 404
