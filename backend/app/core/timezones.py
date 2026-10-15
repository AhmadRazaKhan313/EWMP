"""
Organisation-local time — audit finding H-1.

Instants are stored in UTC everywhere (correct). But "which calendar day is
it", "is this check-in late" and "when does this shift end" are WALL-CLOCK
questions, and they used to be answered in UTC:

  * check-in "today" was the UTC date — a 00:00–05:00 check-in in Pakistan
    (UTC+5) landed on the previous day;
  * lateness compared the UTC time of day to the shift's local start — a
    09:30 check-in in Karachi is 04:30 UTC, so nobody was ever late;
  * HR's manual "09:00" was stored as 09:00 UTC (= 14:00 in Karachi);
  * shift end / auto-cutoff instants were built in UTC;
  * the dashboard and "upcoming holidays" used the server's date.

Every such question goes through this module, using the organisation's
timezone (Organization.timezone, editable in Settings → General).

Per-branch timezones are deliberately NOT used yet: branches.timezone is
NOT NULL DEFAULT 'UTC', so an untouched branch can't be told apart from one
really in UTC, and honouring it would force every default branch back to UTC.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

UTC_ZONE = ZoneInfo("UTC")


def zone_from_name(name: str | None) -> ZoneInfo:
    """IANA name → ZoneInfo; anything missing or invalid → UTC (never raises)."""
    if not name:
        return UTC_ZONE
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return UTC_ZONE


async def org_zone(db: AsyncSession, tenant_id: uuid.UUID) -> ZoneInfo:
    """The organisation's timezone (one small query)."""
    from app.models.organization import Organization

    name = (
        await db.execute(select(Organization.timezone).where(Organization.id == tenant_id))
    ).scalar_one_or_none()
    return zone_from_name(name)


def local_now(zone: ZoneInfo, now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)).astimezone(zone)


def local_today(zone: ZoneInfo, now: datetime | None = None) -> date:
    """Today's date in the organisation — not the server's, not UTC's."""
    return local_now(zone, now).date()


def local_date_of(at: datetime, zone: ZoneInfo) -> date:
    """The organisation-local calendar day an instant belongs to."""
    return _aware(at).astimezone(zone).date()


def local_to_utc(on: date, at: time, zone: ZoneInfo) -> datetime:
    """A wall-clock time on a date, in the organisation → the UTC instant."""
    return datetime.combine(on, at, tzinfo=zone).astimezone(UTC)


def nearest_shift_start(at: datetime, start: time, zone: ZoneInfo) -> datetime:
    """The occurrence of a shift's start time (yesterday / today / tomorrow,
    local) closest to `at`. Makes overnight shifts work: 00:30 belongs to
    the shift that started at 22:00 the evening before, not to tonight's."""
    local_at = _aware(at).astimezone(zone)
    candidates = [
        datetime.combine(local_at.date() + timedelta(days=offset), start, tzinfo=zone)
        for offset in (-1, 0, 1)
    ]
    return min(candidates, key=lambda c: abs(c - local_at))


def minutes_late(shift, check_in_at: datetime, zone: ZoneInfo) -> int:
    """Minutes after (local shift start + grace). 0 when on time or early."""
    start_at = nearest_shift_start(check_in_at, shift.start_time, zone)
    late = int((_aware(check_in_at) - start_at).total_seconds() // 60) - (shift.late_grace_minutes or 0)
    return max(0, late)


def _aware(at: datetime) -> datetime:
    """Treat a naive datetime as UTC (how the database hands them back)."""
    return at if at.tzinfo is not None else at.replace(tzinfo=UTC)
