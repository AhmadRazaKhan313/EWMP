"""
Admin attendance edit / delete (T-01).

An admin with `attendance.edit` changes or removes any day directly: no
approval chain. What replaces the approval is transparency: a written reason
is mandatory and every change leaves an `audit_logs` row with the before and
after values and who did it.

  * Edit goes through the day's PUNCHES (the same `_apply_times` the
    regularization flow uses), so the day is recalculated and the next
    recalculation cannot wipe it out. A punch / day can never exceed 24 h.
  * Delete is a soft delete of the day and its punches; a fresh day can then
    be recorded for that date.
  * If a payroll run covering that date is LOCKED or PAID, the change is
    refused with 409 PAYROLL_LOCKED (the warning the UI shows). Only a user
    with full access (the owner) may override it, explicitly.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.core.timezones import local_to_utc, org_zone
from app.models.attendance import AttendancePunch, AttendanceRecord, AttendanceStatus
from app.models.employee import Employee
from app.models.payroll import PayrollRun, PayrollRunStatus
from app.models.user import User
from app.models.workflows import AuditLog
from app.services.attendance_punches import lock_employee_attendance, recalculate_from_punches
from app.services.attendance_regularization import (
    _apply_times,
    _is_overnight,
    _punches,
    _resolve_out,
    _still_running,
    parse_clock_time,
)

MAX_PUNCH = timedelta(hours=24)
LOCKING = (PayrollRunStatus.LOCKED, PayrollRunStatus.PAID)


class PayrollLockedError(ConflictError):
    error_code = "PAYROLL_LOCKED"
    message = "The payroll for this date is locked"


async def _record(db: AsyncSession, tenant_id: uuid.UUID, record_id: uuid.UUID) -> AttendanceRecord:
    rec = (
        await db.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.id == record_id,
                AttendanceRecord.tenant_id == tenant_id,
                AttendanceRecord.is_deleted == False,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if rec is None:
        raise NotFoundError("Attendance record not found")
    return rec


async def locked_payroll_run(db: AsyncSession, tenant_id: uuid.UUID, on: date) -> PayrollRun | None:
    return (
        await db.execute(
            select(PayrollRun)
            .where(
                PayrollRun.tenant_id == tenant_id,
                PayrollRun.status.in_(LOCKING),
                PayrollRun.period_start <= on,
                PayrollRun.period_end >= on,
                PayrollRun.is_deleted == False,  # noqa: E712
            )
            .limit(1)
        )
    ).scalar_one_or_none()


async def _check_payroll_lock(db, tenant_id, admin: User, on: date, override: bool) -> None:
    run = await locked_payroll_run(db, tenant_id, on)
    if run is None:
        return
    if override and admin.has_full_access:
        return
    hint = "" if admin.has_full_access else " Only the owner can override it."
    raise PayrollLockedError(
        f'The payroll "{run.name}" ({run.period_start} to {run.period_end}) is locked, so this '
        f"day can't be changed.{hint}",
        detail={"payroll_run_id": str(run.id), "can_override": bool(admin.has_full_access)},
    )


def _snapshot(record: AttendanceRecord, punches: list[AttendancePunch]) -> dict:
    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    return {
        "date": record.date.isoformat(),
        "status": record.status.value,
        "check_in": iso(record.check_in),
        "check_out": iso(record.check_out),
        "total_minutes": record.total_minutes,
        "notes": record.notes,
        "punches": [
            {"id": str(p.id), "in": iso(p.punch_in), "out": iso(p.punch_out)} for p in punches
        ],
    }


async def _audit(db, tenant_id, admin: User, action, record, employee, before, after, reason) -> None:
    changed = [k for k in after if before.get(k) != after.get(k)] if after else list(before)
    db.add(AuditLog(
        tenant_id=tenant_id,
        user_id=admin.id,
        user_email=admin.email,
        action=action,
        resource_type="attendance_record",
        resource_id=str(record.id),
        resource_label=f"{employee} · {record.date.isoformat()}",
        before_data=before,
        after_data={**(after or {}), "reason": reason},
        changed_fields=changed,
        severity="warning" if action.endswith("delete") else "info",
    ))


def _clean_reason(reason: str | None) -> str:
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise ValidationError("A reason is required (at least 3 characters)")
    return reason


async def _employee_of(db, tenant_id, record) -> str:
    """Label for the audit row: 'Name (CODE)'."""
    row = (await db.execute(
        select(Employee.employee_code, User.first_name, User.last_name)
        .join(User, User.id == Employee.user_id, isouter=True)
        .where(Employee.id == record.employee_id, Employee.tenant_id == tenant_id)
    )).one()
    name = " ".join(x for x in (row.first_name, row.last_name) if x)
    return f"{name} ({row.employee_code})" if name else row.employee_code


async def audit_mark(
    db: AsyncSession, tenant_id: uuid.UUID, admin: User, record: AttendanceRecord, *,
    created: bool, reason: str | None,
) -> None:
    """Audit row for 'admin marked this day on the employee's behalf' (T-02)."""
    employee = await _employee_of(db, tenant_id, record)
    after = _snapshot(record, await _punches(db, record))
    await _audit(db, tenant_id, admin, "attendance.mark", record, employee,
                 {} if created else {"note": "day already existed"}, after,
                 (reason or "").strip() or "Recorded by HR")
    await db.flush()


async def admin_edit_record(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    admin: User,
    record_id: uuid.UUID,
    *,
    reason: str | None,
    check_in: str | None = None,
    check_out: str | None = None,
    punch_id: uuid.UUID | None = None,
    attendance_status: AttendanceStatus | None = None,
    notes: str | None = None,
    override_payroll_lock: bool = False,
) -> AttendanceRecord:
    reason = _clean_reason(reason)
    if not (check_in or check_out or attendance_status or notes is not None):
        raise ValidationError("Nothing to change")

    record = await _record(db, tenant_id, record_id)
    await _check_payroll_lock(db, tenant_id, admin, record.date, override_payroll_lock)
    await lock_employee_attendance(db, record.employee_id)
    employee = await _employee_of(db, tenant_id, record)
    before = _snapshot(record, await _punches(db, record))

    if check_in or check_out:
        punches = await _punches(db, record)
        if punch_id is not None:
            punch = next((p for p in punches if p.id == punch_id), None)
            if punch is None:
                raise NotFoundError("That punch does not belong to this day")
        elif len(punches) > 1:
            raise ConflictError(f"This day has {len(punches)} punches. Say which one with punch_id")
        else:
            punch = punches[0] if punches else None
        if punch is not None and _still_running(punch):
            raise ConflictError("The employee is checked in right now, so this punch can't be edited yet")

        zone = await org_zone(db, tenant_id)
        new_in = local_to_utc(record.date, parse_clock_time(check_in, "check_in"), zone) if check_in else None
        new_out = local_to_utc(record.date, parse_clock_time(check_out, "check_out"), zone) if check_out else None
        if new_out is not None:
            anchor = new_in or (punch.punch_in if punch else None)
            if anchor is None:
                raise ValidationError("Give check_in too: this day has no punch yet")
            new_out = _resolve_out(anchor, new_out, await _is_overnight(db, record.shift_id))
            if new_out - anchor > MAX_PUNCH:
                raise ValidationError("A single in/out cannot be longer than 24 hours")
        await _apply_times(db, record, punch, new_in, new_out, admin.id)

    if attendance_status is not None and attendance_status not in (AttendanceStatus.PRESENT, AttendanceStatus.LATE):
        record.status = attendance_status      # an explicit call, like HR's manual entry
    elif attendance_status is not None and not (check_in or check_out):
        record.status = attendance_status
    if notes is not None:
        record.notes = notes.strip() or None
    record.is_regularized = True
    record.regularized_by_id = admin.id
    await db.flush()

    after = _snapshot(record, await _punches(db, record))
    await _audit(db, tenant_id, admin, "attendance.edit", record, employee, before, after, reason)
    await db.flush()
    return record


async def admin_delete_record(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    admin: User,
    record_id: uuid.UUID,
    *,
    reason: str | None,
    override_payroll_lock: bool = False,
) -> None:
    reason = _clean_reason(reason)
    record = await _record(db, tenant_id, record_id)
    await _check_payroll_lock(db, tenant_id, admin, record.date, override_payroll_lock)
    await lock_employee_attendance(db, record.employee_id)
    employee = await _employee_of(db, tenant_id, record)
    punches = await _punches(db, record)
    if any(_still_running(p) for p in punches):
        raise ConflictError("The employee is checked in right now. Delete the day after they check out")
    before = _snapshot(record, punches)
    for p in punches:
        p.soft_delete()
    record.soft_delete()
    await db.flush()
    await _audit(db, tenant_id, admin, "attendance.delete", record, employee, before, None, reason)
    await db.flush()
