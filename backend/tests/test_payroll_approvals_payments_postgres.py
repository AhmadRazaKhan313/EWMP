"""
Regression tests for audit findings H-10 (payroll approval chain) and H-11
(payment reconciliation), through the real HTTP stack against a live
Postgres (TEST_DATABASE_URL, same convention as the other *_postgres tests).

H-10 before: whoever generated a run could approve it; one person could sign
off every level; levels were matched by "first one I qualify for", not "next
one waiting"; a rejection left the run stuck in REVIEW and the old approvals
kept counting; a level could require a permission that doesn't exist.

H-11 before: a payment could be marked paid on a cancelled run, or twice; the
batch never left PREPARED; zero/negative pay and missing bank accounts went
into the bank file; recording payments needed only the export permission; CSV
text cells could run as spreadsheet formulas.
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
    PayrollApprovalLevel, PayrollAuditLog, PayrollItemSettlement, PayrollRun, PayrollSettings, PayrollSnapshot,
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
        for model in (PaymentBatchItem, PaymentBatch, PayrollItemSettlement, PayslipLine, Payslip, PayrollApproval,
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


# ── H-10: approvals ─────────────────────────────────────────────────────────

class TestSegregationOfDuties:
    async def test_whoever_generated_the_run_cannot_approve_it(self, client, engine, org):
        run = await generated_run(client, org)
        assert (await decide(client, org, run, "processor")).status_code == 403
        assert (await decide(client, org, run, "hr")).status_code == 200
        assert await status_of(engine, run) == "approved"

    async def test_the_owner_may_approve_a_run_they_generated(self, client, engine, org):
        run = await generated_run(client, org, by="owner")
        assert (await decide(client, org, run, "owner")).status_code == 200
        assert await status_of(engine, run) == "approved"


class TestLevelsInOrder:
    async def test_each_level_by_its_own_person_in_order(self, client, engine, org):
        await add_levels(engine, org)
        run = await generated_run(client, org)

        first = await decide(client, org, run, "finance")          # takes the NEXT level: HR review
        assert first.status_code == 200 and first.json()["fully_approved"] is False
        again = await decide(client, org, run, "finance")          # same person, second level
        assert again.status_code == 403
        wrong = await decide(client, org, run, "hr")               # lacks payroll.finalize
        assert wrong.status_code == 403 and "Finance sign-off" in wrong.text
        last = await decide(client, org, run, "cfo")
        assert last.status_code == 200 and last.json()["fully_approved"] is True
        assert await status_of(engine, run) == "approved"


class TestRejection:
    async def test_reject_returns_to_draft_and_old_approvals_do_not_count(self, client, engine, org):
        await add_levels(engine, org)
        run = await generated_run(client, org)
        await decide(client, org, run, "hr")                        # HR review approved
        rej = await decide(client, org, run, "cfo", "rejected")     # finance rejects
        assert rej.status_code == 200
        assert await status_of(engine, run) == "draft"
        async with AsyncSession(engine) as s:
            assert (await s.execute(select(func.count()).select_from(PayrollApproval)
                                    .where(PayrollApproval.payroll_run_id == uuid.UUID(run)))).scalar_one() == 0

        # Corrected and regenerated: both levels have to approve again.
        assert (await client.post(f"/api/v1/payroll/runs/{run}/generate", headers=H(org, "processor"))).status_code == 200
        r = await decide(client, org, run, "cfo")
        assert r.json()["fully_approved"] is False                  # HR review again, not "already done"


class TestLevelConfiguration:
    async def test_a_level_needing_a_permission_that_does_not_exist_is_refused(self, client, org):
        r = await client.post("/api/v1/payroll/approval-levels", headers=H(org, "processor"),
                              json={"name": "Typo", "level_order": 1, "required_permission": "payroll.aprove"})
        assert r.status_code == 400

    async def test_two_levels_cannot_share_an_order(self, client, org):
        body = {"name": "A", "level_order": 1, "required_permission": "payroll.approve"}
        assert (await client.post("/api/v1/payroll/approval-levels", headers=H(org, "processor"), json=body)).status_code == 201
        r = await client.post("/api/v1/payroll/approval-levels", headers=H(org, "processor"), json={**body, "name": "B"})
        assert r.status_code == 409


# ── H-11: payments ──────────────────────────────────────────────────────────

async def approved_batch(client, org):
    run = await generated_run(client, org)
    assert (await decide(client, org, run, "hr")).status_code == 200
    b = await client.post(f"/api/v1/payroll/runs/{run}/payment-batch", headers=H(org, "processor"))
    assert b.status_code == 201, b.text
    detail = await client.get(f"/api/v1/payroll/payment-batches/{b.json()['id']}", headers=H(org, "processor"))
    return run, b.json(), detail.json()["items"]


def pay(client, org, batch_id, item_id, action, who="processor"):
    return client.post(f"/api/v1/payroll/payment-batches/{batch_id}/items/{item_id}/{action}",
                       headers=H(org, who), json={"payment_reference": "TX-1", "failure_reason": "bounced"})


class TestBatchContents:
    async def test_only_payable_payslips_go_in_and_the_rest_are_reported(self, client, org):
        _, batch, items = await approved_batch(client, org)
        assert batch["item_count"] == 1 and len(items) == 1
        assert Decimal(batch["total_amount"]) == Decimal(items[0]["amount"])
        assert batch["skipped"] == [{"employee_id": str(org["bina"]), "reason": "no bank account number"}]


class TestReconciliation:
    async def test_paid_is_final_and_the_batch_completes(self, client, engine, org):
        _, batch, items = await approved_batch(client, org)
        item = items[0]["id"]
        assert (await pay(client, org, batch["id"], item, "mark-paid")).status_code == 200
        assert (await pay(client, org, batch["id"], item, "mark-paid")).status_code == 409
        assert (await pay(client, org, batch["id"], item, "mark-failed")).status_code == 409
        async with AsyncSession(engine) as s:
            assert (await s.get(PaymentBatch, uuid.UUID(batch["id"]))).status.value == "completed"

    async def test_a_failed_transfer_can_be_retried_and_paid(self, client, engine, org):
        _, batch, items = await approved_batch(client, org)
        item = items[0]["id"]
        assert (await pay(client, org, batch["id"], item, "mark-failed")).status_code == 200
        async with AsyncSession(engine) as s:
            assert (await s.get(PaymentBatch, uuid.UUID(batch["id"]))).status.value == "failed"
        assert (await pay(client, org, batch["id"], item, "mark-paid")).status_code == 200

    async def test_recording_payments_needs_the_finalize_permission(self, client, org):
        _, batch, items = await approved_batch(client, org)
        assert (await pay(client, org, batch["id"], items[0]["id"], "mark-paid", who="exporter")).status_code == 403

    async def test_a_reversed_run_can_no_longer_be_paid(self, client, engine, org):
        run, batch, items = await approved_batch(client, org)
        rev = await client.post(f"/api/v1/payroll/runs/{run}/reverse", headers=H(org, "processor"),
                                json={"reason": "wrong month"})
        assert rev.status_code == 200, rev.text
        async with AsyncSession(engine) as s:
            item = await s.get(PaymentBatchItem, uuid.UUID(items[0]["id"]))
            assert item.status.value == "failed" and item.failure_reason == "Payroll run reversed"
        assert (await pay(client, org, batch["id"], items[0]["id"], "mark-paid")).status_code == 409


class TestBankFile:
    async def test_text_that_looks_like_a_formula_is_kept_as_text(self, client, org):
        _, batch, _ = await approved_batch(client, org)
        r = await client.get(f"/api/v1/payroll/payment-batches/{batch['id']}/csv", headers=H(org, "processor"))
        rows = list(csv.reader(io.StringIO(r.text)))
        title = rows[1][3]
        assert title.startswith("'=") and not title.startswith("=")
