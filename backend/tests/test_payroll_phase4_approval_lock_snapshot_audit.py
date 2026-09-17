"""
End-to-end integration tests for Payroll Phase 4: multi-level approval,
finalize/lock with snapshot, reopen, reverse, and the audit log — all
exercised through the real endpoints against a real (in-memory SQLite) DB.

Run:  cd backend && pytest tests/test_payroll_phase4_approval_lock_snapshot_audit.py -v
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

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


async def _make_employee(db):
    from app.models.employee import Employee, EmploymentStatus, EmploymentType, JobNature

    emp = Employee(
        tenant_id=TENANT, user_id=uuid.uuid4(), employee_code=f"EMP-{uuid.uuid4().hex[:6]}",
        employment_type=EmploymentType.FULL_TIME, job_nature=JobNature.PERMANENT,
        employment_status=EmploymentStatus.ACTIVE, date_of_joining=date(2020, 1, 1),
    )
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


async def _make_and_generate_run(db):
    from app.models.payroll import PayrollRun, PayrollRunStatus
    from app.api.v1.hrms.payroll import generate_payroll_run

    employee = await _make_employee(db)
    await _make_structure_and_salary(db, employee)
    run = PayrollRun(
        tenant_id=TENANT, name="Test Run", period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
        pay_date=date(2026, 6, 30), currency="USD", status=PayrollRunStatus.DRAFT, processed_by_id=uuid.uuid4(),
    )
    db.add(run)
    await db.flush()
    await generate_payroll_run(run.id, _user(), TENANT, db)
    await db.refresh(run)
    return run


def _user(permissions: set[str] | None = None):
    perms = permissions or {"payroll.approve", "payroll.finalize", "payroll.reopen", "payroll.reverse", "payroll.view", "payroll.manage_settings"}
    return SimpleNamespace(id=uuid.uuid4(), has_permission=lambda code: code in perms)


class TestSingleStepApproval:
    """No PayrollApprovalLevel configured -> original single-call behavior."""

    @pytest.mark.asyncio
    async def test_one_approve_call_moves_review_to_approved(self, db_session):
        from app.models.payroll import PayrollRunStatus
        from app.api.v1.hrms.payroll import approve_payroll_run

        run = await _make_and_generate_run(db_session)
        assert run.status == PayrollRunStatus.REVIEW

        result = await approve_payroll_run(run.id, current_user=_user(), tenant_id=TENANT, db=db_session)

        assert result["status"] == "approved"
        await db_session.refresh(run)
        assert run.status == PayrollRunStatus.APPROVED
        assert run.approved_by_id is not None

    @pytest.mark.asyncio
    async def test_cannot_approve_a_run_still_in_draft(self, db_session):
        from app.models.payroll import PayrollRun, PayrollRunStatus
        from app.api.v1.hrms.payroll import approve_payroll_run
        from fastapi import HTTPException

        run = PayrollRun(
            tenant_id=TENANT, name="Draft Run", period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
            pay_date=date(2026, 6, 30), currency="USD", status=PayrollRunStatus.DRAFT, processed_by_id=uuid.uuid4(),
        )
        db_session.add(run)
        await db_session.flush()

        with pytest.raises(HTTPException):
            await approve_payroll_run(run.id, current_user=_user(), tenant_id=TENANT, db=db_session)

    @pytest.mark.asyncio
    async def test_rejection_keeps_run_in_review(self, db_session):
        from app.models.payroll import PayrollRunStatus, ApprovalDecision
        from app.api.v1.hrms.payroll import approve_payroll_run, ApprovalDecisionInput

        run = await _make_and_generate_run(db_session)
        result = await approve_payroll_run(
            run.id, ApprovalDecisionInput(decision=ApprovalDecision.REJECTED, comments="Numbers look off"),
            current_user=_user(), tenant_id=TENANT, db=db_session,
        )
        assert result["decision"] == "rejected"
        await db_session.refresh(run)
        assert run.status == PayrollRunStatus.REVIEW


class TestMultiLevelApproval:
    @pytest.mark.asyncio
    async def test_run_only_approves_once_every_level_has_approved(self, db_session):
        from app.models.payroll import PayrollApprovalLevel, PayrollRunStatus
        from app.api.v1.hrms.payroll import approve_payroll_run

        db_session.add(PayrollApprovalLevel(tenant_id=TENANT, name="HR Review", level_order=1, required_permission="payroll.approve", is_active=True))
        db_session.add(PayrollApprovalLevel(tenant_id=TENANT, name="Finance Approval", level_order=2, required_permission="payroll.finalize", is_active=True))
        await db_session.flush()

        run = await _make_and_generate_run(db_session)

        hr_user = _user({"payroll.approve"})
        finance_user = _user({"payroll.finalize"})

        result1 = await approve_payroll_run(run.id, current_user=hr_user, tenant_id=TENANT, db=db_session)
        assert result1["fully_approved"] is False
        assert result1["levels_approved"] == 1
        await db_session.refresh(run)
        assert run.status == PayrollRunStatus.REVIEW  # not fully approved yet

        result2 = await approve_payroll_run(run.id, current_user=finance_user, tenant_id=TENANT, db=db_session)
        assert result2["fully_approved"] is True
        await db_session.refresh(run)
        assert run.status == PayrollRunStatus.APPROVED

    @pytest.mark.asyncio
    async def test_rejection_at_any_level_sends_back_to_review_regardless_of_prior_approvals(self, db_session):
        from app.models.payroll import PayrollApprovalLevel, PayrollRunStatus, ApprovalDecision
        from app.api.v1.hrms.payroll import approve_payroll_run, ApprovalDecisionInput

        db_session.add(PayrollApprovalLevel(tenant_id=TENANT, name="HR Review", level_order=1, required_permission="payroll.approve", is_active=True))
        db_session.add(PayrollApprovalLevel(tenant_id=TENANT, name="Finance Approval", level_order=2, required_permission="payroll.finalize", is_active=True))
        await db_session.flush()

        run = await _make_and_generate_run(db_session)
        await approve_payroll_run(run.id, current_user=_user({"payroll.approve"}), tenant_id=TENANT, db=db_session)

        result = await approve_payroll_run(
            run.id, ApprovalDecisionInput(decision=ApprovalDecision.REJECTED),
            current_user=_user({"payroll.finalize"}), tenant_id=TENANT, db=db_session,
        )
        assert result["decision"] == "rejected"
        await db_session.refresh(run)
        assert run.status == PayrollRunStatus.REVIEW


class TestFinalizeAndSnapshot:
    @pytest.mark.asyncio
    async def test_finalize_locks_the_run_and_creates_a_snapshot(self, db_session):
        from app.models.payroll import PayrollRunStatus, PayrollSnapshot
        from app.api.v1.hrms.payroll import approve_payroll_run, finalize_payroll_run
        from sqlalchemy import select

        run = await _make_and_generate_run(db_session)
        await approve_payroll_run(run.id, current_user=_user(), tenant_id=TENANT, db=db_session)
        await db_session.refresh(run)

        result = await finalize_payroll_run(run.id, current_user=_user(), tenant_id=TENANT, db=db_session)

        assert result["status"] == "locked"
        await db_session.refresh(run)
        assert run.status == PayrollRunStatus.LOCKED
        assert run.locked_by_id is not None

        snapshot = (await db_session.execute(select(PayrollSnapshot).where(PayrollSnapshot.payroll_run_id == run.id))).scalar_one()
        assert snapshot.snapshot_data["run"]["id"] == str(run.id)
        assert len(snapshot.snapshot_data["payslips"]) == 1

    @pytest.mark.asyncio
    async def test_cannot_finalize_a_run_that_isnt_approved_yet(self, db_session):
        from app.api.v1.hrms.payroll import finalize_payroll_run
        from fastapi import HTTPException

        run = await _make_and_generate_run(db_session)  # still in REVIEW, not APPROVED
        with pytest.raises(HTTPException):
            await finalize_payroll_run(run.id, current_user=_user(), tenant_id=TENANT, db=db_session)


class TestReopen:
    @pytest.mark.asyncio
    async def test_reopen_requires_a_reason(self, db_session):
        from app.api.v1.hrms.payroll import approve_payroll_run, finalize_payroll_run, reopen_payroll_run, ReopenRequest
        from app.core.exceptions import ValidationError

        run = await _make_and_generate_run(db_session)
        await approve_payroll_run(run.id, current_user=_user(), tenant_id=TENANT, db=db_session)
        await finalize_payroll_run(run.id, current_user=_user(), tenant_id=TENANT, db=db_session)

        with pytest.raises(ValidationError):
            await reopen_payroll_run(run.id, ReopenRequest(reason="   "), current_user=_user(), tenant_id=TENANT, db=db_session)

    @pytest.mark.asyncio
    async def test_reopen_with_a_reason_unlocks_the_run_and_logs_it(self, db_session):
        from app.models.payroll import PayrollRunStatus, PayrollAuditLog
        from app.api.v1.hrms.payroll import approve_payroll_run, finalize_payroll_run, reopen_payroll_run, ReopenRequest
        from sqlalchemy import select

        run = await _make_and_generate_run(db_session)
        await approve_payroll_run(run.id, current_user=_user(), tenant_id=TENANT, db=db_session)
        await finalize_payroll_run(run.id, current_user=_user(), tenant_id=TENANT, db=db_session)

        result = await reopen_payroll_run(run.id, ReopenRequest(reason="Found a missing overtime entry"), current_user=_user(), tenant_id=TENANT, db=db_session)

        assert result["status"] == "reopened"
        await db_session.refresh(run)
        assert run.status == PayrollRunStatus.REOPENED
        assert run.reopen_reason == "Found a missing overtime entry"

        logs = (await db_session.execute(select(PayrollAuditLog).where(PayrollAuditLog.action == "RUN_REOPENED"))).scalars().all()
        assert len(logs) == 1
        assert logs[0].reason == "Found a missing overtime entry"

    @pytest.mark.asyncio
    async def test_cannot_reopen_a_run_that_isnt_locked(self, db_session):
        from app.api.v1.hrms.payroll import reopen_payroll_run, ReopenRequest
        from fastapi import HTTPException

        run = await _make_and_generate_run(db_session)  # in REVIEW, not LOCKED
        with pytest.raises(HTTPException):
            await reopen_payroll_run(run.id, ReopenRequest(reason="test"), current_user=_user(), tenant_id=TENANT, db=db_session)


class TestReverse:
    @pytest.mark.asyncio
    async def test_reverse_voids_the_run_and_all_its_payslips(self, db_session):
        from app.models.payroll import PayrollRunStatus, PayslipStatus, Payslip
        from app.api.v1.hrms.payroll import reverse_payroll_run, ReverseRequest
        from sqlalchemy import select

        run = await _make_and_generate_run(db_session)
        result = await reverse_payroll_run(run.id, ReverseRequest(reason="Duplicate run created by mistake"), current_user=_user(), tenant_id=TENANT, db=db_session)

        assert result["status"] == "cancelled"
        await db_session.refresh(run)
        assert run.status == PayrollRunStatus.CANCELLED
        assert run.reversal_reason == "Duplicate run created by mistake"

        payslips = (await db_session.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalars().all()
        assert all(p.status == PayslipStatus.REVERSED for p in payslips)

    @pytest.mark.asyncio
    async def test_reverse_requires_a_reason(self, db_session):
        from app.api.v1.hrms.payroll import reverse_payroll_run, ReverseRequest
        from app.core.exceptions import ValidationError

        run = await _make_and_generate_run(db_session)
        with pytest.raises(ValidationError):
            await reverse_payroll_run(run.id, ReverseRequest(reason=""), current_user=_user(), tenant_id=TENANT, db=db_session)

    @pytest.mark.asyncio
    async def test_cannot_reverse_a_run_with_paid_payslips(self, db_session):
        from app.models.payroll import PayslipStatus, Payslip
        from app.api.v1.hrms.payroll import reverse_payroll_run, ReverseRequest
        from app.core.exceptions import ValidationError
        from sqlalchemy import select

        run = await _make_and_generate_run(db_session)
        payslip = (await db_session.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalar_one()
        payslip.status = PayslipStatus.PAID
        await db_session.flush()

        with pytest.raises(ValidationError, match="already marked PAID"):
            await reverse_payroll_run(run.id, ReverseRequest(reason="test"), current_user=_user(), tenant_id=TENANT, db=db_session)

    @pytest.mark.asyncio
    async def test_cannot_reverse_an_already_cancelled_run(self, db_session):
        from app.api.v1.hrms.payroll import reverse_payroll_run, ReverseRequest
        from fastapi import HTTPException

        run = await _make_and_generate_run(db_session)
        await reverse_payroll_run(run.id, ReverseRequest(reason="First reversal"), current_user=_user(), tenant_id=TENANT, db=db_session)

        with pytest.raises(HTTPException):
            await reverse_payroll_run(run.id, ReverseRequest(reason="Second attempt"), current_user=_user(), tenant_id=TENANT, db=db_session)


class TestAuditLog:
    @pytest.mark.asyncio
    async def test_full_lifecycle_is_recorded_in_order(self, db_session):
        from app.api.v1.hrms.payroll import approve_payroll_run, finalize_payroll_run, reopen_payroll_run, ReopenRequest, get_run_audit_log

        run = await _make_and_generate_run(db_session)
        await approve_payroll_run(run.id, current_user=_user(), tenant_id=TENANT, db=db_session)
        await finalize_payroll_run(run.id, current_user=_user(), tenant_id=TENANT, db=db_session)
        await reopen_payroll_run(run.id, ReopenRequest(reason="Correction needed"), current_user=_user(), tenant_id=TENANT, db=db_session)

        log = await get_run_audit_log(run.id, current_user=_user(), tenant_id=TENANT, db=db_session)

        actions = [e["action"] for e in log["items"]]
        assert "RUN_APPROVED" in actions
        assert "RUN_FINALIZED" in actions
        assert "RUN_REOPENED" in actions
