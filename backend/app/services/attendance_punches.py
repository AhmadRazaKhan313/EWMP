"""
Attendance punch lifecycle, auto-cutoff and regularization.

This module owns three things that used to be spread across the
attendance API handler, or did not exist at all:

  1. Opening and closing PUNCHES (in/out pairs). A day may contain many.
     The old code stored one check_in and one check_out per day, so a
     second check-in was rejected outright with "Already checked in for
     today" and the rest of the day's movements were lost.

  2. Deriving the DAY from its punches. attendance_records.check_in /
     check_out / total_minutes are still the columns payroll, the CSV
     export and the reports read, so they are kept correct as a derived
     summary rather than being rewritten everywhere at once.

  3. The AUTO-CUTOFF. Nothing previously stopped an open session running
     forever: an employee who forgot to check out on Friday came back on
     Monday to a timer reading 72 hours, and every "hours worked" figure
     that touched that record was wrong.

Design notes worth keeping in mind before changing anything here:

  * A forced checkout leaves punch_out NULL. The system does not invent a
    time the employee did not punch. Hours for that punch are zero until
    a manager approves a regularization. Writing a guessed punch_out
    would silently pay people for hours nobody can attest to, and would
    be indistinguishable from a real punch a month later.

  * Every function is idempotent and safe to run twice. The scheduler is
    expected to be run by cron/k8s, which means at-least-once delivery
    and occasional overlapping runs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date as date_cls, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezones import UTC_ZONE, local_date_of, minutes_late, org_zone
from app.models.attendance import (
    AttendancePunch,
    AttendanceRecord,
    AttendanceSource,
    AttendanceStatus,
    Shift,
)

# ── Cutoff policy ─────────────────────────────────────────────────────────

# How long after a shift's scheduled end an open punch is allowed to keep
# running before the scheduler closes it. Covers legitimate overtime
# without letting a forgotten punch run into the next day.
DEFAULT_GRACE_HOURS_AFTER_SHIFT_END = 4

# Absolute ceiling measured from punch_in, applied to EVERY punch
# including shift-assigned ones. This is the backstop for flexible-shift
# and no-shift employees, who have no scheduled end to measure from, and
# for the case where a shift is mis-configured. 14 hours is chosen to sit
# above any plausible real working day (including a double shift) while
# still being obviously wrong as a recorded duration.
HARD_CAP_HOURS = 14


@dataclass(frozen=True)
class CutoffPolicy:
    """Per-tenant knobs. Defaults match the module constants."""

    grace_hours_after_shift_end: int = DEFAULT_GRACE_HOURS_AFTER_SHIFT_END
    hard_cap_hours: int = HARD_CAP_HOURS


def compute_cutoff_at(
    punch_in: datetime,
    shift: Shift | None,
    policy: CutoffPolicy = CutoffPolicy(),
    zone: ZoneInfo = UTC_ZONE,
) -> datetime:
    """
    The moment an open punch becomes stale.

    Two candidate deadlines, and the EARLIER wins:

      * shift end + grace, when a shift is known;
      * punch_in + hard cap, always.

    Taking the earlier is what makes a mis-configured shift harmless. A
    shift row with end_time accidentally set to 23:59 would otherwise
    hold a punch open most of a day past the point it is obviously
    abandoned; the hard cap still closes it.

    Overnight shifts (is_overnight, e.g. 22:00–06:00) have their end on
    the FOLLOWING calendar day relative to the shift's start, which is
    why the end is anchored to the punch's own date and rolled forward
    rather than being read off punch_in.date() directly.
    """
    hard_cap_at = punch_in + timedelta(hours=policy.hard_cap_hours)
    if shift is None:
        return hard_cap_at

    shift_end_at = _resolve_shift_end(punch_in, shift, zone)
    shift_deadline = shift_end_at + timedelta(hours=policy.grace_hours_after_shift_end)
    return min(shift_deadline, hard_cap_at)


def _resolve_shift_end(punch_in: datetime, shift: Shift, zone: ZoneInfo = UTC_ZONE) -> datetime:
    """
    Turn a shift's wall-clock end_time into a real instant for this punch.

    The subtlety is multi-shift and overnight work. A 22:00–06:00 shift
    punched in at 22:30 on the 5th ends at 06:00 on the 6th; the same
    shift punched in at 00:30 on the 6th (someone arriving late into the
    night portion) also ends at 06:00 on the 6th, NOT the 7th. Anchoring
    to the date and rolling forward only when the end has already passed
    handles both without needing to know which half of the shift the
    punch landed in.

    `zone` is the organisation's timezone: the shift's 18:00 means 18:00 on
    the office clock. It used to be built in the punch's own tzinfo — UTC —
    so in Karachi an 18:00 shift "ended" at 23:00 local (audit H-1).
    """
    anchor = local_date_of(punch_in, zone)
    end_at = datetime.combine(anchor, shift.end_time, tzinfo=zone)

    if shift.is_overnight:
        start_at = datetime.combine(anchor, shift.start_time, tzinfo=zone)
        # Punched in during the evening half → the end is tomorrow.
        # Punched in after midnight → the end is today.
        if punch_in >= start_at:
            end_at += timedelta(days=1)
    elif end_at <= punch_in:
        # A same-day shift that the punch already sits past (late arrival
        # after the scheduled end, or a shift edited mid-day).
        end_at += timedelta(days=1)

    return end_at


# ── Punch lifecycle ───────────────────────────────────────────────────────


async def get_open_punch(
    db: AsyncSession, tenant_id: uuid.UUID, employee_id: uuid.UUID
) -> AttendancePunch | None:
    """
    The employee's one currently-running punch, if any.

    Deliberately does not filter by date. The punch that needs closing
    may have been opened yesterday (overnight shift) or three days ago
    (forgotten). Filtering by "today" is the bug that made check-out fail
    outright for overnight shifts.
    """
    return (
        await db.execute(
            select(AttendancePunch)
            .where(
                AttendancePunch.tenant_id == tenant_id,
                AttendancePunch.employee_id == employee_id,
                AttendancePunch.punch_out.is_(None),
                AttendancePunch.is_forced_checkout == False,  # noqa: E712
                AttendancePunch.is_deleted == False,  # noqa: E712
            )
            .order_by(AttendancePunch.punch_in.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def get_or_create_day(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
    on_date: date_cls,
    shift_id: uuid.UUID | None = None,
) -> AttendanceRecord:
    lookup = select(AttendanceRecord).where(
        AttendanceRecord.tenant_id == tenant_id,
        AttendanceRecord.employee_id == employee_id,
        AttendanceRecord.date == on_date,
        AttendanceRecord.is_deleted == False,  # noqa: E712
    )
    record = (await db.execute(lookup)).scalar_one_or_none()

    if record is None:
        record = AttendanceRecord(
            tenant_id=tenant_id,
            employee_id=employee_id,
            date=on_date,
            status=AttendanceStatus.PRESENT,
            shift_id=shift_id,
        )
        try:
            # uq_attendance_records_one_per_day (audit H-2): if a concurrent
            # request (double-click, web + desktop at once) created this day
            # first, only this SAVEPOINT rolls back and we use its row.
            async with db.begin_nested():
                db.add(record)
                await db.flush()
        except IntegrityError:
            record = (await db.execute(lookup)).scalar_one()

    return record


async def open_punch(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
    at: datetime,
    source: AttendanceSource = AttendanceSource.MANUAL,
    shift_id: uuid.UUID | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> tuple[AttendancePunch, AttendanceRecord]:
    """
    Start a punch. This is what "check in" now means.

    A second, third or fourth punch on the same day is normal and
    expected — lunch, a client visit, an evening return. What is NOT
    allowed is two punches open at once, which would make "how long have
    you been working" unanswerable.
    """
    existing = await get_open_punch(db, tenant_id, employee_id)
    if existing is not None:
        raise ValueError("There is already an open punch — check out before checking in again.")

    # The organisation's calendar day, not UTC's (audit H-1).
    day = local_date_of(at, await org_zone(db, tenant_id))
    record = await get_or_create_day(db, tenant_id, employee_id, day, shift_id)

    punch = AttendancePunch(
        tenant_id=tenant_id,
        attendance_record_id=record.id,
        employee_id=employee_id,
        punch_in=at,
        punch_in_source=source,
        punch_in_latitude=latitude,
        punch_in_longitude=longitude,
        shift_id=shift_id or record.shift_id,
    )
    try:
        # uq on "one open punch per employee": two check-ins arriving
        # together (a double-click, or web and desktop at the same moment)
        # both pass the check above; the second insert fails here. The
        # punch the other request just opened IS this check-in — return it
        # rather than a 500 (audit H-2).
        async with db.begin_nested():
            db.add(punch)
            await db.flush()
    except IntegrityError:
        existing = await get_open_punch(db, tenant_id, employee_id)
        if existing is None:
            raise
        record = (
            await db.execute(select(AttendanceRecord).where(AttendanceRecord.id == existing.attendance_record_id))
        ).scalar_one()
        return existing, record

    await recalculate_from_punches(db, record)
    return punch, record


async def close_punch(
    db: AsyncSession,
    punch: AttendancePunch,
    at: datetime,
    source: AttendanceSource = AttendanceSource.MANUAL,
    latitude: float | None = None,
    longitude: float | None = None,
    break_minutes: int = 0,
) -> tuple[AttendancePunch, AttendanceRecord]:
    """Close a punch and refresh the day's derived totals."""
    if at <= punch.punch_in:
        raise ValueError("Check-out time must be after the check-in it closes.")

    punch.punch_out = at
    punch.punch_out_source = source
    punch.punch_out_latitude = latitude
    punch.punch_out_longitude = longitude
    punch.duration_minutes = max(
        0, int((at - punch.punch_in).total_seconds() // 60) - max(break_minutes, 0)
    )
    await db.flush()

    record = (
        await db.execute(
            select(AttendanceRecord).where(AttendanceRecord.id == punch.attendance_record_id)
        )
    ).scalar_one()
    await recalculate_from_punches(db, record)
    return punch, record


# ── Deriving the day from its punches ─────────────────────────────────────


async def recalculate_from_punches(db: AsyncSession, record: AttendanceRecord) -> AttendanceRecord:
    """
    Rebuild the day's summary columns from its punches.

    `check_in` becomes the FIRST punch-in of the day and `check_out` the
    LAST punch-out — which is what every existing consumer of those
    columns already assumes they mean. `total_minutes` is the SUM of the
    punches, not last-out minus first-in, so the two-hour gap an employee
    spent off-site at lunch is not paid as worked time. That difference
    is the entire reason multi-punch matters for payroll.

    Open and force-closed punches contribute zero minutes. An open punch
    contributes nothing because it is still running and its total is not
    yet knowable; a force-closed one because nobody knows when the
    employee actually left.
    """
    punches = (
        await db.execute(
            select(AttendancePunch)
            .where(
                AttendancePunch.attendance_record_id == record.id,
                AttendancePunch.is_deleted == False,  # noqa: E712
            )
            .order_by(AttendancePunch.punch_in)
        )
    ).scalars().all()

    if not punches:
        record.punch_count = 0
        record.total_minutes = 0
        return record

    completed = [p for p in punches if p.punch_out is not None]

    record.check_in = punches[0].punch_in
    record.check_in_source = punches[0].punch_in_source
    record.check_out = completed[-1].punch_out if completed else None
    record.check_out_source = completed[-1].punch_out_source if completed else None
    record.punch_count = len(punches)
    record.total_minutes = sum(p.duration_minutes or 0 for p in completed)

    forced = [p for p in punches if p.is_forced_checkout]
    record.is_forced_checkout = len(forced) > 0
    if forced:
        record.forced_checkout_at = max(
            p.auto_closed_at for p in forced if p.auto_closed_at is not None
        )

    # One shift lookup, reused below for both the LATE/PRESENT recompute and
    # the overtime calc — not two separate queries for the same row.
    shift: Shift | None = None
    if record.shift_id:
        shift = (
            await db.execute(select(Shift).where(Shift.id == record.shift_id))
        ).scalar_one_or_none()

    # A day containing a force-closed punch is MISSED_PUNCH until
    # regularized, regardless of how many other punches completed
    # cleanly — the total is known to be short by an unknown amount, and
    # reporting it as PRESENT would present an undercount as a fact.
    # `is_regularized` is checked so an approved correction is not
    # immediately re-flagged by the next recalculation.
    if record.is_forced_checkout and not record.is_regularized:
        record.status = AttendanceStatus.MISSED_PUNCH
    elif record.status in (AttendanceStatus.PRESENT, AttendanceStatus.LATE, AttendanceStatus.MISSED_PUNCH):
        # Leaving MISSED_PUNCH — either this punch was never force-closed,
        # or it was and has now been regularized (apply_regularization
        # deliberately leaves is_forced_checkout=True for the audit trail;
        # is_regularized is what's supposed to override it, per the comment
        # there — this elif is what actually has to honor that). Recompute
        # PRESENT vs LATE from the (possibly corrected) first punch-in
        # instead of defaulting to PRESENT, so a day that was late before
        # being force-closed doesn't silently lose that fact on approval.
        #
        # Also the ONE place lateness is decided for a normal day, whichever
        # app checked in (audit C-4): the desktop path used to leave every
        # day PRESENT with late_minutes never set, and the web path computed
        # it separately. Only attendance-derived statuses are touched —
        # ON_LEAVE / HOLIDAY / HALF_DAY / ABSENT set by HR stay as they are.
        late_minutes = (
            minutes_late(shift, record.check_in, await org_zone(db, record.tenant_id)) if shift else 0
        )
        record.late_minutes = late_minutes
        record.status = AttendanceStatus.LATE if late_minutes > 0 else AttendanceStatus.PRESENT

    # Overtime is only meaningful once the day is actually closed. A
    # MISSED_PUNCH day has an unknown total, so claiming overtime on it
    # would pay out on a number the system itself does not trust.
    if record.status == AttendanceStatus.MISSED_PUNCH:
        record.overtime_minutes = 0
    elif shift is not None:
        record.overtime_minutes = max(0, (record.total_minutes or 0) - _scheduled_minutes(shift))

    await db.flush()
    return record


def _scheduled_minutes(shift: Shift) -> int:
    """Paid minutes in one scheduled shift, breaks excluded."""
    start = datetime.combine(date_cls.min, shift.start_time)
    end = datetime.combine(date_cls.min, shift.end_time)
    if end <= start:
        end += timedelta(days=1)
    gross = int((end - start).total_seconds() // 60)
    return max(0, gross - (shift.break_duration_minutes or 0))


# ── Auto-cutoff scheduler ─────────────────────────────────────────────────


@dataclass
class CutoffResult:
    scanned: int = 0
    closed: int = 0
    closed_punch_ids: list[uuid.UUID] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.closed_punch_ids is None:
            self.closed_punch_ids = []


async def run_auto_cutoff(
    db: AsyncSession,
    now: datetime | None = None,
    tenant_id: uuid.UUID | None = None,
    policy: CutoffPolicy = CutoffPolicy(),
) -> CutoffResult:
    """
    Force-close every punch that has run past its cutoff.

    Intended to be run on a schedule — hourly is a good default. It is
    NOT run on a timer inside the API process: an API process is
    replicated, and three replicas each running their own timer is three
    concurrent cutoff passes. Cron or a k8s CronJob calling
    `manage.py attendance cutoff` gives one caller and a place for
    failures to be seen.

    Safe to run repeatedly and concurrently: a punch that a parallel run
    already closed no longer matches the open-punch filter, and closing
    is a pure state transition with no side effects outside this row and
    its parent day.

    `tenant_id` narrows the pass to one organization, which matters for
    backfills and for tenants in very different timezones; omitted, it
    sweeps every tenant.
    """
    now = now or datetime.now(UTC)
    result = CutoffResult()

    filters = [
        AttendancePunch.punch_out.is_(None),
        AttendancePunch.is_forced_checkout == False,  # noqa: E712
        AttendancePunch.is_deleted == False,  # noqa: E712
        # Nothing can be stale before the shortest possible deadline has
        # elapsed, so this keeps the scan off the whole table.
        AttendancePunch.punch_in < now,
    ]
    if tenant_id is not None:
        filters.append(AttendancePunch.tenant_id == tenant_id)

    open_punches = (
        await db.execute(select(AttendancePunch).where(*filters).order_by(AttendancePunch.punch_in))
    ).scalars().all()

    # One shift lookup per distinct shift, not per punch — a cutoff pass
    # over a few thousand open punches otherwise issues a few thousand
    # identical queries.
    shift_ids = {p.shift_id for p in open_punches if p.shift_id is not None}
    shifts: dict[uuid.UUID, Shift] = {}
    if shift_ids:
        rows = (await db.execute(select(Shift).where(Shift.id.in_(shift_ids)))).scalars().all()
        shifts = {s.id: s for s in rows}

    touched_record_ids: set[uuid.UUID] = set()
    # Shift ends are wall-clock times in each organisation's own timezone.
    zones: dict[uuid.UUID, ZoneInfo] = {}

    for punch in open_punches:
        result.scanned += 1
        shift = shifts.get(punch.shift_id) if punch.shift_id else None
        if punch.tenant_id not in zones:
            zones[punch.tenant_id] = await org_zone(db, punch.tenant_id)
        if now < compute_cutoff_at(punch.punch_in, shift, policy, zones[punch.tenant_id]):
            continue

        # punch_out stays NULL on purpose — see the module docstring.
        punch.is_forced_checkout = True
        punch.auto_closed_at = now
        punch.duration_minutes = 0
        result.closed += 1
        result.closed_punch_ids.append(punch.id)
        touched_record_ids.add(punch.attendance_record_id)

    if touched_record_ids:
        records = (
            await db.execute(
                select(AttendanceRecord).where(AttendanceRecord.id.in_(touched_record_ids))
            )
        ).scalars().all()
        for record in records:
            await recalculate_from_punches(db, record)

    await db.flush()
    return result


# ── Regularization ────────────────────────────────────────────────────────


async def apply_regularization(
    db: AsyncSession,
    record: AttendanceRecord,
    punch: AttendancePunch | None,
    approved_punch_in: datetime | None,
    approved_punch_out: datetime | None,
    reviewer_id: uuid.UUID,
) -> AttendanceRecord:
    """
    Write an APPROVED correction onto the attendance record.

    Only ever called from the approval path. Until a manager approves,
    the requested times live on the regularization row and the day keeps
    reporting zero hours — that is what stops an unapproved claim from
    moving payable time.
    """
    if punch is not None:
        if approved_punch_in is not None:
            punch.punch_in = approved_punch_in
        if approved_punch_out is not None:
            if approved_punch_out <= punch.punch_in:
                raise ValueError("Approved check-out must be after the check-in.")
            punch.punch_out = approved_punch_out
            punch.punch_out_source = AttendanceSource.MANUAL
            punch.duration_minutes = int(
                (approved_punch_out - punch.punch_in).total_seconds() // 60
            )
        # The forced flag stays TRUE for audit — this day was force-closed
        # and later corrected, and that history is worth more than a
        # clean-looking row. is_regularized is what suppresses the
        # MISSED_PUNCH status in recalculate_from_punches.
        punch.auto_closed_at = punch.auto_closed_at

    record.is_regularized = True
    record.regularized_by_id = reviewer_id
    await db.flush()

    await recalculate_from_punches(db, record)
    return record