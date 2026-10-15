"""
Attendance regularization — correcting a day the system recorded wrongly
(audit finding M-7, part B).

Typical case: the employee forgot to check out; the stale-attendance sweep
force-closed the punch with 0 minutes and the day is MISSED_PUNCH. The
employee asks for a correction, a manager approves it, and only then do the
hours come back — an unapproved claim can never move payable time (the
requested times live on the AttendanceRegularization row until approval).

Two ways in, one implementation:

  * employee → request_regularization() → manager → approve / reject
    (or the employee cancels while it's pending);
  * HR's manual POST /attendance → hr_record_day(), which is the same
    correction, recorded as an AttendanceRegularization that is already
    APPROVED so there is an audit trail of who changed what.

Both write through PUNCHES (the source of truth since audit C-4) and then
recalculate the day. HR's manual entry used to write the day's columns
directly, so the next recalculation from punches silently wiped it out.

Times are entered as office-clock times ("09:15"), in the organisation's
timezone. For an overnight shift a check-out earlier than the check-in means
the next morning; for any other shift it is rejected.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.core.timezones import local_to_utc, org_zone
from app.models.attendance import (
    AttendancePunch,
    AttendanceRecord,
    AttendanceRegularization,
    AttendanceSource,
    AttendanceStatus,
    RegularizationStatus,
    Shift,
)
from app.models.employee import Employee
from app.models.user import User
from app.services.attendance_punches import (
    get_or_create_day,
    lock_employee_attendance,
    recalculate_from_punches,
)

HR_REASON = "Recorded by HR"


# ── Parsing ──────────────────────────────────────────────────────────────────

def parse_clock_time(value: str, field_name: str) -> time:
    """'09:15' or '09:15:30' (24-hour)."""
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(value.strip(), fmt).time()
        except ValueError:
            continue
    raise ValidationError(f"{field_name} must be in HH:MM or HH:MM:SS 24-hour format, got {value!r}")


async def _is_overnight(db: AsyncSession, shift_id: uuid.UUID | None) -> bool:
    if shift_id is None:
        return False
    shift = (await db.execute(select(Shift).where(Shift.id == shift_id))).scalar_one_or_none()
    return bool(shift and shift.is_overnight)


def _resolve_out(in_at: datetime, out_at: datetime, overnight: bool) -> datetime:
    """A check-out not after the check-in means 'the next morning' on an
    overnight shift; anywhere else it is a mistake."""
    if out_at > in_at:
        return out_at
    if overnight and out_at + timedelta(days=1) > in_at:
        return out_at + timedelta(days=1)
    raise ValidationError("check_out must be after check_in")


# ── Lookups ──────────────────────────────────────────────────────────────────

async def _employee(db: AsyncSession, tenant_id: uuid.UUID, employee_id: uuid.UUID) -> Employee:
    emp = (
        await db.execute(
            select(Employee).where(
                Employee.id == employee_id,
                Employee.tenant_id == tenant_id,
                Employee.is_deleted == False,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if emp is None:
        raise NotFoundError("Employee not found in this organization")
    return emp


async def _day(db: AsyncSession, tenant_id: uuid.UUID, employee_id: uuid.UUID, on: date) -> AttendanceRecord | None:
    return (
        await db.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.tenant_id == tenant_id,
                AttendanceRecord.employee_id == employee_id,
                AttendanceRecord.date == on,
                AttendanceRecord.is_deleted == False,  # noqa: E712
            )
        )
    ).scalar_one_or_none()


async def _punches(db: AsyncSession, record: AttendanceRecord) -> list[AttendancePunch]:
    return list(
        (
            await db.execute(
                select(AttendancePunch)
                .where(AttendancePunch.attendance_record_id == record.id, AttendancePunch.is_deleted == False)  # noqa: E712
                .order_by(AttendancePunch.punch_in)
            )
        ).scalars().all()
    )


def _still_running(punch: AttendancePunch) -> bool:
    return punch.punch_out is None and not punch.is_forced_checkout


# ── The one place corrected times are written ────────────────────────────────

async def _apply_times(
    db: AsyncSession,
    record: AttendanceRecord,
    punch: AttendancePunch | None,
    new_in: datetime | None,
    new_out: datetime | None,
    reviewer_id: uuid.UUID,
) -> AttendancePunch:
    """Write approved times onto a punch (or add a new closed punch) and
    rebuild the day. Caller holds the employee's attendance lock."""
    if punch is None:
        if new_in is None or new_out is None:
            raise ValidationError("Both check_in and check_out are needed to add a punch")
        punch = AttendancePunch(
            tenant_id=record.tenant_id, attendance_record_id=record.id, employee_id=record.employee_id,
            shift_id=record.shift_id, punch_in=new_in, punch_in_source=AttendanceSource.MANUAL,
        )
        db.add(punch)
    elif _still_running(punch):
        raise ConflictError("That punch is still running (the employee is checked in) — it can't be corrected yet")
    else:
        if new_in is not None:
            punch.punch_in = new_in

    if new_out is not None:
        punch.punch_out = new_out
        punch.punch_out_source = AttendanceSource.MANUAL
    if punch.punch_out is not None:
        if punch.punch_out <= punch.punch_in:
            raise ValidationError("check_out must be after check_in")
        punch.duration_minutes = int((punch.punch_out - punch.punch_in).total_seconds() // 60)
    # A force-closed punch keeps is_forced_checkout=True for audit; the day's
    # is_regularized flag is what lifts MISSED_PUNCH in recalculation.

    def _end(p: AttendancePunch) -> datetime:
        # A still-running punch occupies everything after its start. A
        # force-closed one's real end is unknown (that's what's being
        # corrected), so it blocks only its own start instant until someone
        # regularizes it — at which point THAT correction is checked here.
        if p.punch_out is not None:
            return p.punch_out
        return datetime.max.replace(tzinfo=UTC) if _still_running(p) else p.punch_in

    for other in await _punches(db, record):
        if other is punch or other.id == punch.id:
            continue
        if punch.punch_in < _end(other) and other.punch_in < max(_end(punch), punch.punch_in + timedelta(seconds=1)):
            raise ConflictError("Those times overlap another punch on the same day")

    record.is_regularized = True
    record.regularized_by_id = reviewer_id
    await db.flush()
    await recalculate_from_punches(db, record)
    return punch


# ── Employee flow ────────────────────────────────────────────────────────────

async def request_regularization(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    requester: User,
    employee_id: uuid.UUID,
    on: date,
    punch_id: uuid.UUID | None,
    check_in: str | None,
    check_out: str | None,
    reason: str,
) -> AttendanceRegularization:
    if not check_in and not check_out:
        raise ValidationError("Give the corrected check_in, check_out, or both")
    await _employee(db, tenant_id, employee_id)
    record = await _day(db, tenant_id, employee_id, on)
    if record is None:
        raise NotFoundError("There is no attendance for that day to correct — ask HR to record the day")

    punch = None
    if punch_id is not None:
        punch = next((p for p in await _punches(db, record) if p.id == punch_id), None)
        if punch is None:
            raise NotFoundError("That punch does not belong to this day")
        if _still_running(punch):
            raise ConflictError("That punch is still running — check out first, then request a correction")
    elif not (check_in and check_out):
        raise ValidationError("To add a missing punch, give both check_in and check_out")

    zone = await org_zone(db, tenant_id)
    new_in = local_to_utc(on, parse_clock_time(check_in, "check_in"), zone) if check_in else None
    new_out = local_to_utc(on, parse_clock_time(check_out, "check_out"), zone) if check_out else None
    if new_out is not None:
        anchor = new_in or punch.punch_in
        new_out = _resolve_out(anchor, new_out, await _is_overnight(db, record.shift_id))

    # One pending request per employee per DAY — the rule the database
    # already enforces (uq_regularization_one_pending_per_day): a manager
    # reviews one request per day, not several fragments of it.
    busy = ConflictError(
        "A correction for this day is already waiting for approval — "
        "wait for it, or withdraw it and send one request covering the whole day"
    )
    pending = (
        await db.execute(
            select(AttendanceRegularization.id).where(
                AttendanceRegularization.employee_id == employee_id,
                AttendanceRegularization.date == on,
                AttendanceRegularization.status == RegularizationStatus.PENDING,
                AttendanceRegularization.is_deleted == False,  # noqa: E712
            )
        )
    ).first()
    if pending:
        raise busy

    reg = AttendanceRegularization(
        tenant_id=tenant_id, attendance_record_id=record.id, employee_id=employee_id, punch_id=punch_id,
        date=on, requested_punch_in=new_in, requested_punch_out=new_out, reason=reason.strip(),
        status=RegularizationStatus.PENDING, requested_by_id=requester.id,
    )
    try:
        async with db.begin_nested():  # two requests sent at the same moment
            db.add(reg)
            await db.flush()
    except IntegrityError:
        raise busy
    return reg


async def get_regularization(db: AsyncSession, tenant_id: uuid.UUID, reg_id: uuid.UUID) -> AttendanceRegularization:
    reg = (
        await db.execute(
            select(AttendanceRegularization)
            .where(
                AttendanceRegularization.id == reg_id,
                AttendanceRegularization.tenant_id == tenant_id,
                AttendanceRegularization.is_deleted == False,  # noqa: E712
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if reg is None:
        raise NotFoundError("Regularization request not found")
    return reg


def _require_pending(reg: AttendanceRegularization) -> None:
    if reg.status != RegularizationStatus.PENDING:
        raise ConflictError(f"This request is already {reg.status.value}")


async def _reviewer_is_the_employee(db: AsyncSession, reviewer: User, reg: AttendanceRegularization) -> bool:
    own = (
        await db.execute(select(Employee.id).where(Employee.user_id == reviewer.id, Employee.tenant_id == reg.tenant_id))
    ).scalar_one_or_none()
    return own == reg.employee_id


async def approve_regularization(
    db: AsyncSession, tenant_id: uuid.UUID, reviewer: User, reg_id: uuid.UUID, comments: str | None
) -> AttendanceRegularization:
    reg = await get_regularization(db, tenant_id, reg_id)
    _require_pending(reg)
    if not reviewer.has_full_access and await _reviewer_is_the_employee(db, reviewer, reg):
        raise PermissionDeniedError("You can't approve a correction to your own attendance")

    await lock_employee_attendance(db, reg.employee_id)
    record = (await db.execute(select(AttendanceRecord).where(AttendanceRecord.id == reg.attendance_record_id))).scalar_one()
    punch = None
    if reg.punch_id is not None:
        punch = (await db.execute(select(AttendancePunch).where(AttendancePunch.id == reg.punch_id))).scalar_one_or_none()
        if punch is None or punch.is_deleted:
            raise ConflictError("The punch this request corrects no longer exists")
    await _apply_times(db, record, punch, reg.requested_punch_in, reg.requested_punch_out, reviewer.id)

    reg.status = RegularizationStatus.APPROVED
    reg.reviewed_by_id = reviewer.id
    reg.reviewed_at = datetime.now(UTC)
    reg.review_comments = comments
    await db.flush()
    return reg


async def reject_regularization(
    db: AsyncSession, tenant_id: uuid.UUID, reviewer: User, reg_id: uuid.UUID, comments: str | None
) -> AttendanceRegularization:
    reg = await get_regularization(db, tenant_id, reg_id)
    _require_pending(reg)
    reg.status = RegularizationStatus.REJECTED
    reg.reviewed_by_id = reviewer.id
    reg.reviewed_at = datetime.now(UTC)
    reg.review_comments = comments
    await db.flush()
    return reg


async def cancel_regularization(
    db: AsyncSession, tenant_id: uuid.UUID, actor: User, reg_id: uuid.UUID
) -> AttendanceRegularization:
    reg = await get_regularization(db, tenant_id, reg_id)
    _require_pending(reg)
    if reg.requested_by_id != actor.id and not await _reviewer_is_the_employee(db, actor, reg):
        raise PermissionDeniedError("Only the person who asked for this correction can cancel it")
    reg.status = RegularizationStatus.CANCELLED
    await db.flush()
    return reg


# ── HR manual entry (POST /attendance) ───────────────────────────────────────

async def hr_record_day(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    hr_user: User,
    employee_id: uuid.UUID,
    on: date,
    check_in: str | None,
    check_out: str | None,
    attendance_status: AttendanceStatus,
) -> tuple[AttendanceRecord, bool]:
    """HR sets or corrects one day. Returns (day, created)."""
    zone = await org_zone(db, tenant_id)
    in_t = parse_clock_time(check_in, "check_in") if check_in else None
    out_t = parse_clock_time(check_out, "check_out") if check_out else None

    employee = await _employee(db, tenant_id, employee_id)
    await lock_employee_attendance(db, employee_id)
    created = await _day(db, tenant_id, employee_id, on) is None
    record = await get_or_create_day(db, tenant_id, employee_id, on, employee.default_shift_id)

    if in_t or out_t:
        punches = await _punches(db, record)
        if len(punches) > 1:
            raise ConflictError(
                f"This day has {len(punches)} punches — correct them one at a time with a regularization"
            )
        punch = punches[0] if punches else None
        new_in = local_to_utc(on, in_t, zone) if in_t else None
        new_out = local_to_utc(on, out_t, zone) if out_t else None
        if new_out is not None:
            anchor = new_in or (punch.punch_in if punch else None)
            if anchor is None:
                raise ValidationError("Give check_in too — this day has no check-in yet")
            new_out = _resolve_out(anchor, new_out, await _is_overnight(db, record.shift_id))
        if punch is None and new_out is None:
            raise ValidationError("Give check_out too — HR entries add a complete punch")

        punch = await _apply_times(db, record, punch, new_in, new_out, hr_user.id)
        db.add(AttendanceRegularization(
            tenant_id=tenant_id, attendance_record_id=record.id, employee_id=employee_id, punch_id=punch.id,
            date=on, requested_punch_in=new_in, requested_punch_out=new_out, reason=HR_REASON,
            status=RegularizationStatus.APPROVED, requested_by_id=hr_user.id,
            reviewed_by_id=hr_user.id, reviewed_at=datetime.now(UTC),
        ))

    # PRESENT / LATE come from the punches; anything else (HALF_DAY, ON_LEAVE,
    # WORK_FROM_HOME, ABSENT, …) is HR's explicit call for the day.
    if attendance_status not in (AttendanceStatus.PRESENT, AttendanceStatus.LATE):
        record.status = attendance_status
    record.is_regularized = True
    record.regularized_by_id = hr_user.id
    await db.flush()
    return record, created
