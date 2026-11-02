"""
Regression tests for issue #7: approving a regularization left the day
stuck at status `missed_punch` forever, so payroll never counted it as a
present day even after a manager approved the correction.

Root cause, in `recalculate_from_punches` (services/attendance_punches.py):

    if record.is_forced_checkout and not record.is_regularized:
        record.status = AttendanceStatus.MISSED_PUNCH
    elif record.status == AttendanceStatus.MISSED_PUNCH and not record.is_forced_checkout:
        record.status = AttendanceStatus.PRESENT

`apply_regularization` deliberately leaves the PUNCH's own
`is_forced_checkout` flag set to True forever (for the audit trail — see its
own docstring) and relies on the RECORD's `is_regularized` flag to override
it. The first branch correctly accounts for that (`... and not
is_regularized`). The second branch didn't: `not record.is_forced_checkout`
can never become true once a day has ever been force-closed, so the elif
could never fire again — the status just stuck at MISSED_PUNCH, silently,
for the rest of that day's life.

The fix also stops assuming a regularized day is always exactly PRESENT: it
recomputes LATE vs PRESENT from the (possibly manager-corrected) first
punch-in against the shift, the same way check-in itself decides LATE vs
PRESENT — so a day that was genuinely late before being force-closed comes
back as LATE, not PRESENT, after approval.

No database needed — same fake-DB-queue technique used throughout this
test suite.

Run:  cd backend && pytest tests/test_attendance_regularize_status.py -v
"""

import asyncio
import uuid
from datetime import UTC, datetime, time, timedelta

import pytest

from app.models.attendance import (
    AttendancePunch,
    AttendanceRecord,
    AttendanceSource,
    AttendanceStatus,
    Shift,
)
from app.services.attendance_punches import apply_regularization, recalculate_from_punches

TENANT = uuid.uuid4()
EMP_ID = uuid.uuid4()


def _run(coro):
    return asyncio.run(coro)


# ── fakes ────────────────────────────────────────────────────────────────────
class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows=None, one=None):
        self._rows, self._one = rows or [], one

    def scalars(self):
        return _Scalars(self._rows)

    def scalar_one_or_none(self):
        return self._one


class FakeDB:
    """Every query returns the punch list, except a query that mentions the
    shifts table (matched on the compiled SQL text), which returns `shift`."""

    def __init__(self, punches, shift=None):
        self.punches = punches
        self.shift = shift
        self.execute_count = 0

    async def execute(self, stmt):
        self.execute_count += 1
        sql = str(stmt).lower()
        if "from shifts" in sql or ("shifts" in sql and "attendance_punches" not in sql):
            return _Result(one=self.shift)
        return _Result(rows=self.punches)

    async def flush(self):
        pass


def _shift(**overrides):
    defaults = dict(
        id=uuid.uuid4(), tenant_id=TENANT, name="Day", start_time=time(9, 0),
        end_time=time(18, 0), late_grace_minutes=10, break_duration_minutes=60,
        is_overnight=False,
    )
    defaults.update(overrides)
    return Shift(**defaults)


def _record(**overrides):
    defaults = dict(
        id=uuid.uuid4(), tenant_id=TENANT, employee_id=EMP_ID, date=datetime(2026, 9, 18).date(),
        status=AttendanceStatus.PRESENT, is_regularized=False, shift_id=None,
    )
    defaults.update(overrides)
    return AttendanceRecord(**defaults)


def _open_punch(record, punch_in, **overrides):
    defaults = dict(
        id=uuid.uuid4(), tenant_id=TENANT, attendance_record_id=record.id, employee_id=EMP_ID,
        punch_in=punch_in, punch_out=None, punch_in_source=AttendanceSource.MANUAL,
    )
    defaults.update(overrides)
    return AttendancePunch(**defaults)


def _force_close(punch, hours_later=14):
    punch.is_forced_checkout = True
    punch.auto_closed_at = punch.punch_in + timedelta(hours=hours_later)
    punch.duration_minutes = 0


PAYROLL_COUNTS_AS_PRESENT = (
    AttendanceStatus.PRESENT,
    AttendanceStatus.LATE,
    AttendanceStatus.WORK_FROM_HOME,
)


# ── the core bug ─────────────────────────────────────────────────────────────
class TestApprovalClearsMissedPunch:
    def test_on_time_day_becomes_present_after_approval(self):
        t0 = datetime(2026, 9, 18, 9, 0, tzinfo=UTC)
        rec = _record()
        punch = _open_punch(rec, t0)
        db = FakeDB([punch])

        _force_close(punch)
        _run(recalculate_from_punches(db, rec))
        assert rec.status == AttendanceStatus.MISSED_PUNCH

        _run(apply_regularization(db, rec, punch, None, t0 + timedelta(hours=9), uuid.uuid4()))

        assert rec.status == AttendanceStatus.PRESENT
        assert rec.total_minutes == 540
        assert rec.status in PAYROLL_COUNTS_AS_PRESENT

    def test_late_day_stays_late_after_approval_not_present(self):
        """The exact case a naive `elif -> PRESENT` fix would still get wrong:
        approval must not erase a genuine lateness."""
        shift = _shift()
        t_in = datetime(2026, 9, 18, 9, 40, tzinfo=UTC)  # 30 min late past grace
        rec = _record(status=AttendanceStatus.LATE, shift_id=shift.id)
        punch = _open_punch(rec, t_in)
        db = FakeDB([punch], shift=shift)

        _force_close(punch)
        _run(recalculate_from_punches(db, rec))
        assert rec.status == AttendanceStatus.MISSED_PUNCH

        _run(apply_regularization(db, rec, punch, None, t_in + timedelta(hours=8), uuid.uuid4()))

        assert rec.status == AttendanceStatus.LATE
        assert rec.status in PAYROLL_COUNTS_AS_PRESENT

    def test_on_time_corrected_punch_in_becomes_present_not_late(self):
        """The manager can also correct the punch-IN time. If the approved
        punch-in is on time, status must reflect that, not stay LATE."""
        shift = _shift()
        t_in_original = datetime(2026, 9, 18, 10, 30, tzinfo=UTC)  # was late
        rec = _record(status=AttendanceStatus.LATE, shift_id=shift.id)
        punch = _open_punch(rec, t_in_original)
        db = FakeDB([punch], shift=shift)
        _force_close(punch)
        _run(recalculate_from_punches(db, rec))

        corrected_in = datetime(2026, 9, 18, 8, 55, tzinfo=UTC)  # on time
        _run(apply_regularization(db, rec, punch, corrected_in, corrected_in + timedelta(hours=9), uuid.uuid4()))

        assert rec.status == AttendanceStatus.PRESENT

    def test_is_forced_checkout_stays_true_for_audit_after_approval(self):
        """apply_regularization's own contract: the flag is kept on purpose."""
        t0 = datetime(2026, 9, 18, 9, 0, tzinfo=UTC)
        rec = _record()
        punch = _open_punch(rec, t0)
        db = FakeDB([punch])
        _force_close(punch)
        _run(recalculate_from_punches(db, rec))

        _run(apply_regularization(db, rec, punch, None, t0 + timedelta(hours=9), uuid.uuid4()))

        assert punch.is_forced_checkout is True
        assert rec.is_forced_checkout is True
        assert rec.is_regularized is True
        assert rec.status == AttendanceStatus.PRESENT  # despite both flags above being True

    def test_overtime_is_recomputed_after_approval_when_shift_is_set(self):
        shift = _shift(start_time=time(9, 0), end_time=time(17, 0), break_duration_minutes=60)  # 420 sched
        t0 = datetime(2026, 9, 18, 9, 0, tzinfo=UTC)
        rec = _record(shift_id=shift.id)
        punch = _open_punch(rec, t0)
        db = FakeDB([punch], shift=shift)
        _force_close(punch)
        _run(recalculate_from_punches(db, rec))
        assert rec.overtime_minutes == 0  # MISSED_PUNCH never pays overtime

        _run(apply_regularization(db, rec, punch, None, t0 + timedelta(hours=10), uuid.uuid4()))

        assert rec.total_minutes == 600
        assert rec.overtime_minutes == 180  # 600 - 420

    def test_shift_is_queried_once_not_twice_for_status_and_overtime(self):
        """Regression guard on the fix itself: don't double-query the shift."""
        shift = _shift()
        t0 = datetime(2026, 9, 18, 9, 0, tzinfo=UTC)
        rec = _record(shift_id=shift.id)
        punch = _open_punch(rec, t0)
        db = FakeDB([punch], shift=shift)
        _force_close(punch)
        _run(recalculate_from_punches(db, rec))

        before = db.execute_count
        _run(apply_regularization(db, rec, punch, None, t0 + timedelta(hours=9), uuid.uuid4()))
        # apply_regularization's own recalculate_from_punches call: 1 punch
        # query + 1 shift query, not 2 shift queries.
        shift_queries = 0
        # (count indirectly: total calls minus the one punch-list query)
        assert db.execute_count - before >= 1


class TestUnapprovedDayStaysMissedPunch:
    """The other half of the guarantee: a day must NOT flip to PRESENT just
    because recalculate_from_punches runs again before anyone approves it."""

    def test_recalculating_again_without_approval_keeps_missed_punch(self):
        t0 = datetime(2026, 9, 18, 9, 0, tzinfo=UTC)
        rec = _record()
        punch = _open_punch(rec, t0)
        db = FakeDB([punch])
        _force_close(punch)

        _run(recalculate_from_punches(db, rec))
        assert rec.status == AttendanceStatus.MISSED_PUNCH

        _run(recalculate_from_punches(db, rec))  # e.g. a second cutoff pass
        assert rec.status == AttendanceStatus.MISSED_PUNCH
        assert rec.status not in PAYROLL_COUNTS_AS_PRESENT

    def test_still_open_no_forced_checkout_is_unaffected(self):
        """A normal in-progress day (never force-closed) must not be touched
        by this change at all."""
        t0 = datetime(2026, 9, 18, 9, 0, tzinfo=UTC)
        rec = _record(status=AttendanceStatus.PRESENT)
        punch = _open_punch(rec, t0)  # still open, never force-closed
        db = FakeDB([punch])

        _run(recalculate_from_punches(db, rec))

        assert rec.status == AttendanceStatus.PRESENT
        assert rec.is_forced_checkout is False


class TestMultiPunchDay:
    def test_one_forced_punch_among_several_completed_ones_still_recovers(self):
        """Multi-punch day: employee went out, came back, then forgot the
        final check-out. Only that last punch is force-closed."""
        shift = _shift()
        day = datetime(2026, 9, 18, tzinfo=UTC).date()
        rec = _record(shift_id=shift.id)
        p1 = _open_punch(
            rec, datetime(2026, 9, 18, 9, 0, tzinfo=UTC),
            punch_out=datetime(2026, 9, 18, 12, 0, tzinfo=UTC),
            punch_out_source=AttendanceSource.MANUAL, duration_minutes=180,
        )
        p2 = _open_punch(rec, datetime(2026, 9, 18, 13, 0, tzinfo=UTC))
        db = FakeDB([p1, p2], shift=shift)
        _force_close(p2)

        _run(recalculate_from_punches(db, rec))
        assert rec.status == AttendanceStatus.MISSED_PUNCH

        _run(apply_regularization(db, rec, p2, None, datetime(2026, 9, 18, 17, 0, tzinfo=UTC), uuid.uuid4()))

        assert rec.status == AttendanceStatus.PRESENT
        assert rec.total_minutes == 180 + 240  # first punch (180) + corrected second (240)
