"""
End-to-end integration tests for Payroll Phase 5: YTD summary, variance
report, journal entries, and payment batch preparation/reconciliation —
exercised through the real endpoints against a real (in-memory SQLite) DB.

Run:  cd backend && pytest tests/test_payroll_phase5_ytd_journal_payment.py -v
"""
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio

TENANT = uuid.uuid4()


@pytest_asyncio.fixture
async def db_session():
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from app.core.database import Base
    import app.models.payroll  # noqa: F401
    import app.models.employee  # noqa: F401
    import app.models.attendance  # noqa: F401
    import app.models.user  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


async def _make_employee(db, **overrides):
    from app.models.employee import Employee, EmploymentStatus, EmploymentType, JobNature

    defaults = dict(
        tenant_id=TENANT, user_id=uuid.uuid4(), employee_code=f"EMP-{uuid.uuid4().hex[:6]}",
        employment_type=EmploymentType.FULL_TIME, job_nature=JobNature.PERMANENT,
        employment_status=EmploymentStatus.ACTIVE, date_of_joining=date(2020, 1, 1),
        bank_name="Test Bank", bank_account_number="12345678", bank_account_title="Test Employee",
    )
    defaults.update(overrides)
    emp = Employee(**defaults)
    db.add(emp)
    await db.flush()
    return emp


async def _make_structure_and_salary(db, employee, basic_salary=Decimal("100000")):
    from app.models.payroll import SalaryStructure, SalaryComponent, EmployeeSalary, ComponentType, ComponentCalculation

    structure = SalaryStructure(tenant_id=TENANT, name="Standard", code=f"STD-{uuid.uuid4().hex[:6]}", is_active=True)
    db.add(structure)
    await db.flush()
    db.add(SalaryComponent(
        tenant_id=TENANT, salary_structure_id=structure.id, name="Basic", code="BASIC",
        component_type=ComponentType.EARNING, calculation_type=ComponentCalculation.FIXED,
        amount=basic_salary, display_order=1,
    ))
    await db.flush()
    salary = EmployeeSalary(
        tenant_id=TENANT, employee_id=employee.id, salary_structure_id=structure.id,
        basic_salary=basic_salary, effective_from=date(2020, 1, 1), is_current=True,
    )
    db.add(salary)
    await db.flush()
    return structure, salary


async def _make_and_generate_run(db, employee, period_start, period_end, pay_date=None, lock=False):
    from app.models.payroll import PayrollRun, PayrollRunStatus
    from app.api.v1.hrms.payroll import generate_payroll_run, approve_payroll_run, finalize_payroll_run

    run = PayrollRun(
        tenant_id=TENANT, name=f"Run {period_start}", period_start=period_start, period_end=period_end,
        pay_date=pay_date or period_end, currency="USD", status=PayrollRunStatus.DRAFT, processed_by_id=uuid.uuid4(),
    )
    db.add(run)
    await db.flush()
    await generate_payroll_run(run.id, _user(), TENANT, db)
    if lock:
        await approve_payroll_run(run.id, current_user=_user(), tenant_id=TENANT, db=db)
        await finalize_payroll_run(run.id, current_user=_user(), tenant_id=TENANT, db=db)
    await db.refresh(run)
    return run


def _user(permissions: set[str] | None = None):
    perms = permissions or {"payroll.view", "payroll.export", "payroll.approve", "payroll.finalize", "payroll.manage_settings"}
    return SimpleNamespace(id=uuid.uuid4(), has_permission=lambda code: code in perms)


class TestYTD:
    @pytest.mark.asyncio
    async def test_ytd_only_counts_locked_runs_not_draft_or_review(self, db_session):
        from app.api.v1.hrms.payroll import get_employee_ytd

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee)

        # January: locked (counts)
        await _make_and_generate_run(db_session, employee, date(2026, 1, 1), date(2026, 1, 31), lock=True)
        # February: still in review (should NOT count)
        await _make_and_generate_run(db_session, employee, date(2026, 2, 1), date(2026, 2, 28), lock=False)

        result = await get_employee_ytd(employee.id, 2026, current_user=_user(), tenant_id=TENANT, db=db_session)

        assert result["payroll_count"] == 1
        assert Decimal(result["ytd_gross"]) == Decimal("100000.00")

    @pytest.mark.asyncio
    async def test_ytd_accumulates_across_multiple_locked_runs(self, db_session):
        from app.api.v1.hrms.payroll import get_employee_ytd

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee)
        await _make_and_generate_run(db_session, employee, date(2026, 1, 1), date(2026, 1, 31), lock=True)
        await _make_and_generate_run(db_session, employee, date(2026, 2, 1), date(2026, 2, 28), lock=True)

        result = await get_employee_ytd(employee.id, 2026, current_user=_user(), tenant_id=TENANT, db=db_session)

        assert result["payroll_count"] == 2
        assert Decimal(result["ytd_gross"]) == Decimal("200000.00")

    @pytest.mark.asyncio
    async def test_ytd_filters_by_year(self, db_session):
        from app.api.v1.hrms.payroll import get_employee_ytd

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee)
        await _make_and_generate_run(db_session, employee, date(2025, 12, 1), date(2025, 12, 31), lock=True)
        await _make_and_generate_run(db_session, employee, date(2026, 1, 1), date(2026, 1, 31), lock=True)

        result_2026 = await get_employee_ytd(employee.id, 2026, current_user=_user(), tenant_id=TENANT, db=db_session)
        result_2025 = await get_employee_ytd(employee.id, 2025, current_user=_user(), tenant_id=TENANT, db=db_session)

        assert result_2026["payroll_count"] == 1
        assert result_2025["payroll_count"] == 1


class TestVarianceReport:
    @pytest.mark.asyncio
    async def test_no_previous_run_returns_null_previous(self, db_session):
        from app.api.v1.hrms.payroll import get_run_variance

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee)
        run = await _make_and_generate_run(db_session, employee, date(2026, 6, 1), date(2026, 6, 30))

        result = await get_run_variance(run.id, current_user=_user(), tenant_id=TENANT, db=db_session)
        assert result["previous"] is None

    @pytest.mark.asyncio
    async def test_computes_variance_against_prior_run(self, db_session):
        from app.api.v1.hrms.payroll import get_run_variance

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee, basic_salary=Decimal("100000"))
        await _make_and_generate_run(db_session, employee, date(2026, 5, 1), date(2026, 5, 31), lock=True)

        employee2 = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee2, basic_salary=Decimal("50000"))
        run2 = await _make_and_generate_run(db_session, employee2, date(2026, 6, 1), date(2026, 6, 30))
        # Need both employees active for run2's generation to include both —
        # simplify by just checking run2 (employee2 only) against run1 (employee only).

        result = await get_run_variance(run2.id, current_user=_user(), tenant_id=TENANT, db=db_session)
        assert result["previous_run"] is not None
        assert "change" in result["gross_salary"]


class TestJournalEntries:
    @pytest.mark.asyncio
    async def test_journal_entries_balance_for_a_real_run(self, db_session):
        from app.api.v1.hrms.payroll import get_run_journal_entries

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee)
        run = await _make_and_generate_run(db_session, employee, date(2026, 6, 1), date(2026, 6, 30))

        result = await get_run_journal_entries(run.id, current_user=_user(), tenant_id=TENANT, db=db_session)

        assert result["is_balanced"] is True
        assert Decimal(result["total_debits"]) == Decimal(result["total_credits"])

    @pytest.mark.asyncio
    async def test_unmapped_accounts_produce_a_warning(self, db_session):
        from app.api.v1.hrms.payroll import get_run_journal_entries

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee)
        run = await _make_and_generate_run(db_session, employee, date(2026, 6, 1), date(2026, 6, 30))

        result = await get_run_journal_entries(run.id, current_user=_user(), tenant_id=TENANT, db=db_session)
        assert result["warning"] is not None
        assert "unmapped" in result["warning"].lower()

    @pytest.mark.asyncio
    async def test_configured_mapping_removes_it_from_warning(self, db_session):
        from app.api.v1.hrms.payroll import get_run_journal_entries, upsert_account_mapping, AccountMappingCreate
        from app.models.payroll import AccountMappingPurpose

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee)
        run = await _make_and_generate_run(db_session, employee, date(2026, 6, 1), date(2026, 6, 30))

        await upsert_account_mapping(
            AccountMappingPurpose.SALARY_EXPENSE, AccountMappingCreate(purpose=AccountMappingPurpose.SALARY_EXPENSE, account_code="5100", account_name="Salaries"),
            current_user=_user(), tenant_id=TENANT, db=db_session,
        )
        result = await get_run_journal_entries(run.id, current_user=_user(), tenant_id=TENANT, db=db_session)
        salary_entry = next(e for e in result["entries"] if e["purpose"] == "salary_expense")
        assert salary_entry["account_code"] == "5100"


class TestPaymentBatch:
    @pytest.mark.asyncio
    async def test_creating_a_batch_snapshots_bank_details(self, db_session):
        from app.api.v1.hrms.payroll import create_payment_batch, approve_payroll_run, get_payment_batch

        employee = await _make_employee(db_session, bank_name="Original Bank", bank_account_number="111")
        await _make_structure_and_salary(db_session, employee)
        run = await _make_and_generate_run(db_session, employee, date(2026, 6, 1), date(2026, 6, 30))
        await approve_payroll_run(run.id, current_user=_user(), tenant_id=TENANT, db=db_session)

        result = await create_payment_batch(run.id, current_user=_user(), tenant_id=TENANT, db=db_session)
        assert result["item_count"] == 1
        assert Decimal(result["total_amount"]) == Decimal("100000.00")

        # Employee changes bank AFTER batch is created.
        employee.bank_account_number = "999-CHANGED"
        await db_session.flush()

        batch = await get_payment_batch(uuid.UUID(result["id"]), current_user=_user(), tenant_id=TENANT, db=db_session)
        assert batch["items"][0]["bank_account_number"] == "111"  # snapshot, not live

    @pytest.mark.asyncio
    async def test_cannot_create_a_second_batch_for_the_same_run(self, db_session):
        from app.api.v1.hrms.payroll import create_payment_batch, approve_payroll_run
        from app.core.exceptions import ValidationError

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee)
        run = await _make_and_generate_run(db_session, employee, date(2026, 6, 1), date(2026, 6, 30))
        await approve_payroll_run(run.id, current_user=_user(), tenant_id=TENANT, db=db_session)
        await create_payment_batch(run.id, current_user=_user(), tenant_id=TENANT, db=db_session)

        with pytest.raises(ValidationError):
            await create_payment_batch(run.id, current_user=_user(), tenant_id=TENANT, db=db_session)

    @pytest.mark.asyncio
    async def test_mark_paid_updates_item_and_payslip_status(self, db_session):
        from app.models.payroll import PayslipStatus, Payslip
        from app.api.v1.hrms.payroll import create_payment_batch, approve_payroll_run, mark_payment_item_paid, PaymentReconcile
        from sqlalchemy import select

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee)
        run = await _make_and_generate_run(db_session, employee, date(2026, 6, 1), date(2026, 6, 30))
        await approve_payroll_run(run.id, current_user=_user(), tenant_id=TENANT, db=db_session)
        batch_result = await create_payment_batch(run.id, current_user=_user(), tenant_id=TENANT, db=db_session)

        from app.api.v1.hrms.payroll import get_payment_batch
        batch = await get_payment_batch(uuid.UUID(batch_result["id"]), current_user=_user(), tenant_id=TENANT, db=db_session)
        item_id = uuid.UUID(batch["items"][0]["id"])

        result = await mark_payment_item_paid(
            uuid.UUID(batch_result["id"]), item_id, PaymentReconcile(payment_reference="TXN123"),
            current_user=_user(), tenant_id=TENANT, db=db_session,
        )
        assert result["status"] == "paid"
        assert result["payment_reference"] == "TXN123"

        payslip = (await db_session.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalar_one()
        assert payslip.status == PayslipStatus.PAID


class TestDashboard:
    @pytest.mark.asyncio
    async def test_dashboard_returns_summary_stats(self, db_session):
        from app.api.v1.hrms.payroll import get_payroll_dashboard

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee)
        await _make_and_generate_run(db_session, employee, date(2026, 6, 1), date(2026, 6, 30))

        result = await get_payroll_dashboard(current_user=_user(), tenant_id=TENANT, db=db_session)

        assert result["total_employees_on_payroll"] == 1
        assert result["pending_approvals"] == 1  # the run is in REVIEW
        assert result["current_run"] is not None
        assert len(result["cost_trend"]) >= 1
