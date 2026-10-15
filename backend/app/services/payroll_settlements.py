"""
Payroll item settlements — what a payroll run takes from loans, advances,
bonuses, arrears, commissions and reimbursements (audit finding C-6).

  generate  → record_settlement()   ledger rows only; sources untouched
  finalize  → apply_run()           sources change (balance down, PAID, …)
  reverse   → undo_run()            sources restored exactly
  reopen    → undo_run()            same, then the run can be regenerated

While a run is not finalized its rows are a RESERVATION: another live run
generated meanwhile sees them (reserved_amount / is_reserved) and does not
take the same money again. Cancelled runs reserve nothing.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.models.payroll import (
    AdvanceStatus,
    ArrearStatus,
    BonusStatus,
    CommissionStatus,
    LoanStatus,
    PayrollAdvance,
    PayrollArrear,
    PayrollBonus,
    PayrollCommission,
    PayrollItemSettlement,
    PayrollLoan,
    PayrollReimbursement,
    PayrollRun,
    PayrollRunStatus,
    ReimbursementStatus,
    SettlementSource,
)

# source type → (model, status enum, status it must have when applied, status after applying)
_ONE_OFF = {
    SettlementSource.BONUS: (PayrollBonus, BonusStatus, BonusStatus.APPROVED, BonusStatus.PAID),
    SettlementSource.ARREAR: (PayrollArrear, ArrearStatus, ArrearStatus.APPROVED, ArrearStatus.PAID),
    SettlementSource.COMMISSION: (PayrollCommission, CommissionStatus, CommissionStatus.APPROVED, CommissionStatus.PAID),
    SettlementSource.REIMBURSEMENT: (
        PayrollReimbursement, ReimbursementStatus, ReimbursementStatus.APPROVED, ReimbursementStatus.INCLUDED_IN_PAYROLL,
    ),
}
# source type → (model, status enum, active status, closed status)
_INSTALMENT = {
    SettlementSource.LOAN: (PayrollLoan, LoanStatus, LoanStatus.ACTIVE, LoanStatus.CLOSED),
    SettlementSource.ADVANCE: (PayrollAdvance, AdvanceStatus, AdvanceStatus.ACTIVE, AdvanceStatus.CLOSED),
}


def _reserving(source_type: SettlementSource, source_id: uuid.UUID, other_than_run: uuid.UUID):
    """Unapplied rows for this source in any OTHER live (not cancelled) run."""
    return and_(
        PayrollItemSettlement.source_type == source_type.value,
        PayrollItemSettlement.source_id == source_id,
        PayrollItemSettlement.payroll_run_id != other_than_run,
        PayrollItemSettlement.applied_at.is_(None),
        PayrollItemSettlement.is_deleted == False,  # noqa: E712
        PayrollRun.id == PayrollItemSettlement.payroll_run_id,
        PayrollRun.status != PayrollRunStatus.CANCELLED,
    )


async def reserved_amount(db: AsyncSession, source_type: SettlementSource, source_id: uuid.UUID, run_id: uuid.UUID) -> Decimal:
    total = (
        await db.execute(
            select(func.coalesce(func.sum(PayrollItemSettlement.amount), 0))
            .select_from(PayrollItemSettlement)
            .join(PayrollRun, PayrollRun.id == PayrollItemSettlement.payroll_run_id)
            .where(_reserving(source_type, source_id, run_id))
        )
    ).scalar_one()
    return Decimal(str(total))


async def is_reserved(db: AsyncSession, source_type: SettlementSource, source_id: uuid.UUID, run_id: uuid.UUID) -> bool:
    return (
        await db.execute(
            select(PayrollItemSettlement.id)
            .join(PayrollRun, PayrollRun.id == PayrollItemSettlement.payroll_run_id)
            .where(_reserving(source_type, source_id, run_id))
            .limit(1)
        )
    ).first() is not None


def record_settlement(
    db: AsyncSession, tenant_id: uuid.UUID, run_id: uuid.UUID, payslip_id: uuid.UUID,
    source_type: SettlementSource, source_id: uuid.UUID, amount: Decimal,
) -> None:
    db.add(PayrollItemSettlement(
        tenant_id=tenant_id, payroll_run_id=run_id, payslip_id=payslip_id,
        source_type=source_type.value, source_id=source_id, amount=amount,
    ))


async def _rows(db: AsyncSession, run: PayrollRun, *conditions) -> list[PayrollItemSettlement]:
    return list(
        (
            await db.execute(
                select(PayrollItemSettlement)
                .where(
                    PayrollItemSettlement.payroll_run_id == run.id,
                    PayrollItemSettlement.is_deleted == False,  # noqa: E712
                    *conditions,
                )
                .order_by(PayrollItemSettlement.created_at)
            )
        ).scalars().all()
    )


async def _source(db: AsyncSession, model, source_id: uuid.UUID):
    return (await db.execute(select(model).where(model.id == source_id).with_for_update())).scalar_one_or_none()


async def apply_run(db: AsyncSession, run: PayrollRun) -> int:
    """Finalize: make the run's recorded effects real. All or nothing — any
    source that changed since generation stops the finalize (409)."""
    now = datetime.now(UTC)
    applied = 0
    for row in await _rows(db, run, PayrollItemSettlement.applied_at.is_(None)):
        kind = SettlementSource(row.source_type)
        if kind in _INSTALMENT:
            model, _status_enum, active, closed = _INSTALMENT[kind]
            src = await _source(db, model, row.source_id)
            if src is None or src.status != active or src.remaining_balance < row.amount:
                raise ConflictError(
                    f"A {kind.value} used by this run changed after it was generated "
                    "(cancelled, suspended or paid down) — reverse the run and generate a new one"
                )
            row.previous_status = src.status.value
            src.remaining_balance -= row.amount
            if src.remaining_balance <= 0:
                src.status = closed
        else:
            model, _status_enum, required, done = _ONE_OFF[kind]
            src = await _source(db, model, row.source_id)
            if src is None or src.status != required:
                raise ConflictError(
                    f"A {kind.value} used by this run changed after it was generated "
                    "(no longer approved) — reverse the run and generate a new one"
                )
            row.previous_status = src.status.value
            src.status = done
        row.applied_at = now
        applied += 1
    await db.flush()
    return applied


async def undo_run(db: AsyncSession, run: PayrollRun) -> int:
    """Reverse / reopen: give back exactly what finalize took."""
    now = datetime.now(UTC)
    undone = 0
    for row in await _rows(db, run, PayrollItemSettlement.applied_at.isnot(None), PayrollItemSettlement.undone_at.is_(None)):
        kind = SettlementSource(row.source_type)
        if kind in _INSTALMENT:
            model, status_enum, _active, _closed = _INSTALMENT[kind]
            src = await _source(db, model, row.source_id)
            if src is not None:
                src.remaining_balance += row.amount
                src.status = status_enum(row.previous_status)
        else:
            model, status_enum, _required, _done = _ONE_OFF[kind]
            src = await _source(db, model, row.source_id)
            if src is not None:
                src.status = status_enum(row.previous_status)
        row.undone_at = now
        undone += 1
    await db.flush()
    return undone
