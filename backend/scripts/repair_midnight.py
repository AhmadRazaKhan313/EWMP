"""Repair legacy attendance rows to the MIDNIGHT rule.

Fixes the days that show 48h-125h (a timer / punch that ran for days):
  1. punches/timers whose end is AFTER their cutoff  -> clipped to the cutoff
     (cutoff = next 12 AM office time; overnight shift = its shift end)
  2. legacy force-closed punches with NO punch_out (0h, MISSED_PUNCH)
     -> closed at the cutoff and credited up to it (breaks excluded)
  3. every touched day is recalculated.

Dry run by default. Back up first:  pg_dump -Fc ewmp > ewmp_backup.dump

  cd backend
  python scripts/repair_midnight.py            # list what would change
  python scripts/repair_midnight.py --fix      # apply
  python scripts/repair_midnight.py --fix --no-credit-missed   # leave 0h days alone
"""
import argparse
import asyncio
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402


async def main(fix: bool, credit_missed: bool) -> None:
    from app.core.timezones import org_zone
    from app.models.attendance import AttendancePunch, AttendanceRecord, Shift
    from app.models.employee import Employee
    from app.models.work_session import BreakRecord, WorkSession, WorkSessionStatus
    from app.services.attendance_punches import (
        CutoffPolicy,
        _break_minutes_between,
        compute_cutoff_at,
        recalculate_from_punches,
    )

    url = os.environ.get("DATABASE_URL")
    if not url:
        from app.core.config import settings  # type: ignore
        url = settings.DATABASE_URL
    engine = create_async_engine(url)
    policy = CutoffPolicy()
    zones: dict[uuid.UUID, object] = {}
    shifts: dict[uuid.UUID, Shift] = {}

    async with AsyncSession(engine, expire_on_commit=False) as db:
        async def zone(t):
            if t not in zones:
                zones[t] = await org_zone(db, t)
            return zones[t]

        async def shift(sid):
            if sid is None:
                return None
            if sid not in shifts:
                shifts[sid] = (await db.execute(select(Shift).where(Shift.id == sid))).scalar_one_or_none()
            return shifts[sid]

        touched: set[uuid.UUID] = set()
        n_clip = n_missed = n_sess = 0

        punches = (await db.execute(select(AttendancePunch).where(AttendancePunch.is_deleted == False))).scalars().all()  # noqa: E712
        for p in punches:
            cutoff = compute_cutoff_at(p.punch_in, await shift(p.shift_id), policy, await zone(p.tenant_id))
            if p.punch_out is not None and p.punch_out > cutoff:
                kind = "clip"
            elif p.punch_out is None and p.is_forced_checkout and credit_missed:
                kind = "missed"
            else:
                continue
            br = await _break_minutes_between(db, p.employee_id, p.punch_in, cutoff)
            mins = max(0, int((cutoff - p.punch_in).total_seconds() // 60) - br)
            old = p.duration_minutes or 0
            print(f"  punch {str(p.id)[:8]} emp {str(p.employee_id)[:8]} in {p.punch_in:%Y-%m-%d %H:%M}Z  {kind:6} {old/60:6.1f}h -> {mins/60:5.1f}h")
            if fix:
                p.punch_out = cutoff
                p.duration_minutes = mins
                if p.is_forced_checkout and p.auto_closed_at is None:
                    p.auto_closed_at = datetime.now(UTC)
            touched.add(p.attendance_record_id)
            n_clip += kind == "clip"
            n_missed += kind == "missed"

        sessions = (await db.execute(
            select(WorkSession).where(WorkSession.is_deleted == False, WorkSession.ended_at.is_not(None))  # noqa: E712
        )).scalars().all()
        emp_shift: dict[uuid.UUID, uuid.UUID | None] = {}
        for s in sessions:
            if s.employee_id not in emp_shift:
                emp_shift[s.employee_id] = (await db.execute(
                    select(Employee.default_shift_id).where(Employee.id == s.employee_id))).scalar_one_or_none()
            cutoff = compute_cutoff_at(s.started_at, await shift(emp_shift[s.employee_id]), policy, await zone(s.tenant_id))
            if s.ended_at <= cutoff:
                continue
            brs = (await db.execute(select(BreakRecord).where(BreakRecord.work_session_id == s.id))).scalars().all()
            bm = sum(max(0, int((min(b.ended_at or cutoff, cutoff) - b.started_at).total_seconds() // 60)) for b in brs)
            mins = max(0, int((cutoff - s.started_at).total_seconds() // 60) - bm)
            print(f"  timer {str(s.id)[:8]} emp {str(s.employee_id)[:8]} start {s.started_at:%Y-%m-%d %H:%M}Z  {(s.total_minutes or 0)/60:6.1f}h -> {mins/60:5.1f}h")
            if fix:
                s.ended_at = cutoff
                s.total_minutes = mins
                s.status = WorkSessionStatus.ENDED
                for b in brs:
                    if b.ended_at is None or b.ended_at > cutoff:
                        b.ended_at = max(b.started_at, cutoff)
            n_sess += 1

        print(f"\npunches clipped: {n_clip} | missed punches credited: {n_missed} | timers clipped: {n_sess} | days touched: {len(touched)}")
        if fix:
            await db.flush()
            recs = (await db.execute(select(AttendanceRecord).where(AttendanceRecord.id.in_(touched)))).scalars().all() if touched else []
            for r in recs:
                await recalculate_from_punches(db, r)
            await db.commit()
            print("APPLIED.")
        else:
            print("Dry run -- nothing changed. Re-run with --fix to apply.")
    await engine.dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--no-credit-missed", action="store_true")
    a = ap.parse_args()
    asyncio.run(main(a.fix, not a.no_credit_missed))
