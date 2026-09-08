"""
Attendance API endpoints.

Includes automated check-in/check-out with:
  - QR code check-in  — kiosk displays a short-lived signed token, employee
    scans it with their phone to prove presence near the branch.
  - Geo-fence check-in — employee's device GPS coords are validated against
    their branch's latitude/longitude/radius (Branch.geo_fence_radius_meters).
  - Late / overtime calculation — computed against the employee's
    default_shift_id at check-in / check-out time.
"""

import math
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from jose import JWTError
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundError, PermissionDeniedError, ValidationError
from app.core.security import create_attendance_qr_token, verify_attendance_qr_token
from app.models.attendance import AttendanceRecord, AttendanceStatus, AttendanceSource, Shift
from app.models.employee import Employee
from app.models.organization_structure import Branch
from app.models.user import User
from app.permissions.dependencies import get_current_user, get_tenant_id, require_permission
from app.repositories.employee import EmployeeRepository
from app.services.attendance_sync import ensure_work_session_ended, ensure_work_session_started

router = APIRouter(prefix="/attendance", tags=["Attendance"])


# ── Helpers ────────────────────────────────────────────────────────────────────
def _haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lng points, in meters."""
    R = 6371000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))


async def _resolve_employee(
    db: AsyncSession, tenant_id: UUID, current_user: User, employee_id: UUID | None
) -> Employee:
    """Resolve whose attendance is being recorded (self-scope gate for bug H7).

    Self-service by default: an authenticated user records attendance for their
    OWN employee record. Recording on behalf of a *different* employee (an HR/
    manager override) requires the ``attendance.regularize`` permission. Without
    this gate any authenticated user could check in or out as any other employee
    just by passing an arbitrary ``employee_id`` — the endpoints only require a
    valid login, not a permission.
    """
    repo = EmployeeRepository(db, tenant_id)
    own = await repo.get_by_user_id(current_user.id)

    # No target, or explicitly targeting self → the caller's own record.
    if employee_id is None or (own is not None and employee_id == own.id):
        if own is None:
            raise NotFoundError("Employee profile not found for this user")
        return own

    # Recording on behalf of someone else → manager/HR only.
    if not current_user.has_permission("attendance.regularize"):
        raise PermissionDeniedError(
            "You can only record your own attendance; recording attendance for "
            "another employee requires the 'attendance.regularize' permission."
        )
    employee = await repo.get(employee_id)  # tenant-scoped: cross-tenant id → None
    if employee is None:
        raise NotFoundError("Employee not found")
    return employee


def _minutes_late(shift: Shift, check_in_at: datetime) -> int:
    """Minutes late vs shift.start_time + grace period. 0 if on time or early."""
    local_time = check_in_at.time()
    scheduled = shift.start_time
    scheduled_minutes = scheduled.hour * 60 + scheduled.minute
    actual_minutes = local_time.hour * 60 + local_time.minute
    late = actual_minutes - scheduled_minutes - shift.late_grace_minutes
    return max(0, late)


def _scheduled_minutes(shift: Shift) -> int:
    """Total scheduled working minutes for the shift, net of break time."""
    start = shift.start_time.hour * 60 + shift.start_time.minute
    end = shift.end_time.hour * 60 + shift.end_time.minute
    if shift.is_overnight or end <= start:
        end += 24 * 60
    return max(0, end - start - shift.break_duration_minutes)


class CheckInRequest(BaseModel):
    method: str  # "manual" | "geo" | "qr"
    employee_id: UUID | None = None
    latitude: float | None = None
    longitude: float | None = None
    qr_token: str | None = None


class CheckOutRequest(BaseModel):
    employee_id: UUID | None = None
    latitude: float | None = None
    longitude: float | None = None


@router.get("", summary="List attendance records")
async def list_attendance(
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    employee_id: UUID | None = Query(None),
    status: AttendanceStatus | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from sqlalchemy import func

    # Two tiers, same shape as leave's view/apply split (see
    # list_leave_requests): `attendance.view` sees the whole org and may
    # filter by any employee_id (unchanged). `attendance.view_own`-only
    # holders — plain self-service employees who were never granted the
    # broad `attendance.view` permission — see only their own records;
    # employee_id is forced to their own employee id, ignoring whatever
    # was requested in the query string, so a self-service holder can
    # never read a colleague's records by passing a different id.
    if not current_user.has_permission("attendance.view"):
        if not current_user.has_permission("attendance.view_own"):
            raise PermissionDeniedError(
                "Viewing attendance requires the 'attendance.view' permission "
                "(or 'attendance.view_own' to see your own)."
            )
        own = await EmployeeRepository(db, tenant_id).get_by_user_id(current_user.id)
        if own is None:
            raise NotFoundError("Employee profile not found for this user")
        employee_id = own.id

    filters = [
        AttendanceRecord.tenant_id == tenant_id,
        AttendanceRecord.is_deleted == False,
    ]
    if date_from:
        filters.append(AttendanceRecord.date >= date_from)
    if date_to:
        filters.append(AttendanceRecord.date <= date_to)
    if employee_id:
        filters.append(AttendanceRecord.employee_id == employee_id)
    if status:
        filters.append(AttendanceRecord.status == status)

    offset = (page - 1) * page_size
    stmt = select(AttendanceRecord).where(*filters).order_by(AttendanceRecord.date.desc()).offset(offset).limit(page_size)
    count_stmt = select(func.count()).select_from(AttendanceRecord).where(*filters)

    items = (await db.execute(stmt)).scalars().all()
    total = (await db.execute(count_stmt)).scalar_one()

    return {
        "items": [
            {
                "id": str(r.id),
                "employee_id": str(r.employee_id),
                "date": str(r.date),
                "check_in": r.check_in.isoformat() if r.check_in else None,
                "check_out": r.check_out.isoformat() if r.check_out else None,
                "status": str(r.status.value),
                "total_minutes": r.total_minutes,
                "overtime_minutes": r.overtime_minutes,
                "late_minutes": r.late_minutes,
                "is_regularized": r.is_regularized,
            }
            for r in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, -(-total // page_size)),
    }


@router.post("", status_code=status.HTTP_201_CREATED, summary="Record manual attendance")
async def record_attendance(
    employee_id: UUID,
    date: date,
    check_in: str | None = None,
    check_out: str | None = None,
    attendance_status: AttendanceStatus = AttendanceStatus.PRESENT,
    current_user: User = Depends(require_permission("attendance.regularize")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manually set/correct an employee's attendance for a given date (e.g.
    HR fixing a missed punch). `check_in`/`check_out` are 24-hour time
    strings ("09:15" or "09:15:00") combined with `date`.
    """

    def _parse_time(value: str, field_name: str) -> datetime:
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                parsed = datetime.strptime(value, fmt).time()
                return datetime.combine(date, parsed, tzinfo=timezone.utc)
            except ValueError:
                continue
        raise ValidationError(f"{field_name} must be in HH:MM or HH:MM:SS 24-hour format, got {value!r}")

    check_in_dt = _parse_time(check_in, "check_in") if check_in else None
    check_out_dt = _parse_time(check_out, "check_out") if check_out else None
    if check_in_dt is not None and check_out_dt is not None and check_out_dt <= check_in_dt:
        raise ValidationError("check_out must be after check_in")

    # Bug fix: this used to always INSERT a new row, even when one already
    # existed for this employee+date, silently creating duplicates every
    # time HR regularized the same day twice. Now it upserts in place.
    existing = (
        await db.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.tenant_id == tenant_id,
                AttendanceRecord.employee_id == employee_id,
                AttendanceRecord.date == date,
                AttendanceRecord.is_deleted == False,  # noqa: E712
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        record = existing
        # Bug fix: check_in/check_out were accepted as parameters but never
        # actually written to the record — regularizing always dropped the
        # times HR entered. Only overwrite a field the caller actually sent.
        if check_in_dt is not None:
            record.check_in = check_in_dt
        if check_out_dt is not None:
            record.check_out = check_out_dt
        record.status = attendance_status
        record.is_regularized = True
        record.regularized_by_id = current_user.id
        created = False
    else:
        record = AttendanceRecord(
            tenant_id=tenant_id,
            employee_id=employee_id,
            date=date,
            status=attendance_status,
            check_in=check_in_dt,
            check_out=check_out_dt,
            check_in_source=AttendanceSource.MANUAL,
            check_out_source=AttendanceSource.MANUAL if check_out_dt is not None else None,
            is_regularized=True,
            regularized_by_id=current_user.id,
        )
        db.add(record)
        created = True

    await db.flush()
    return {"id": str(record.id), "created": created}


@router.get("/qr-code/{branch_id}", summary="Generate a rotating QR check-in token for a branch")
async def get_branch_qr_token(
    branch_id: UUID,
    current_user: User = Depends(require_permission("attendance.regularize")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Meant for a kiosk/reception screen: render this token as a QR code and
    refresh it before `expires_in_minutes` elapses. Employees scan it from
    the mobile app to check in without needing GPS.
    """
    branch = (
        await db.execute(
            select(Branch).where(Branch.id == branch_id, Branch.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if branch is None:
        raise NotFoundError(f"Branch {branch_id} not found")

    token = create_attendance_qr_token(str(tenant_id), str(branch_id), valid_minutes=90)
    return {"token": token, "branch_id": str(branch_id), "expires_in_minutes": 90}


@router.post("/check-in", status_code=status.HTTP_201_CREATED, summary="Check in (QR, geo-fence, or manual)")
async def check_in(
    body: CheckInRequest,
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    employee = await _resolve_employee(db, tenant_id, current_user, body.employee_id)
    now = datetime.now(timezone.utc)
    today = now.date()

    existing = (
        await db.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.employee_id == employee.id,
                AttendanceRecord.tenant_id == tenant_id,
                AttendanceRecord.date == today,
                AttendanceRecord.is_deleted == False,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if existing is not None and existing.check_in is not None:
        raise HTTPException(status_code=400, detail="Already checked in for today")

    source = AttendanceSource.MANUAL
    is_within_geofence: bool | None = None

    if body.method == "geo":
        if body.latitude is None or body.longitude is None:
            raise HTTPException(status_code=400, detail="latitude/longitude required for geo check-in")
        if employee.branch_id is None:
            raise HTTPException(status_code=400, detail="Employee has no branch assigned to validate geofence against")
        branch = (
            await db.execute(select(Branch).where(Branch.id == employee.branch_id))
        ).scalar_one_or_none()
        if branch is None or branch.latitude is None or branch.longitude is None:
            raise HTTPException(status_code=400, detail="Branch does not have a geofence configured")
        distance = _haversine_meters(body.latitude, body.longitude, branch.latitude, branch.longitude)
        is_within_geofence = distance <= branch.geo_fence_radius_meters
        if not is_within_geofence:
            raise HTTPException(
                status_code=403,
                detail=f"You're {int(distance)}m from {branch.name} — outside the {branch.geo_fence_radius_meters}m check-in radius",
            )
        source = AttendanceSource.GEO

    elif body.method == "qr":
        if not body.qr_token:
            raise HTTPException(status_code=400, detail="qr_token required for QR check-in")
        try:
            payload = verify_attendance_qr_token(body.qr_token)
        except JWTError:
            raise HTTPException(status_code=400, detail="QR code expired or invalid — ask reception to refresh it")
        if payload.get("tenant_id") != str(tenant_id):
            raise HTTPException(status_code=403, detail="QR code belongs to a different organization")
        source = AttendanceSource.QR_CODE

    elif body.method != "manual":
        raise HTTPException(status_code=400, detail="method must be one of: manual, geo, qr")

    # Late-minutes calculation against the employee's assigned shift
    late_minutes = 0
    shift_id = employee.default_shift_id
    if shift_id:
        shift = (await db.execute(select(Shift).where(Shift.id == shift_id))).scalar_one_or_none()
        if shift:
            late_minutes = _minutes_late(shift, now)

    attendance_status = AttendanceStatus.LATE if late_minutes > 0 else AttendanceStatus.PRESENT

    if existing is not None:
        existing.check_in = now
        existing.check_in_source = source
        existing.check_in_latitude = body.latitude
        existing.check_in_longitude = body.longitude
        existing.is_within_geofence = is_within_geofence
        existing.late_minutes = late_minutes
        existing.status = attendance_status
        existing.shift_id = shift_id
        record = existing
    else:
        record = AttendanceRecord(
            tenant_id=tenant_id,
            employee_id=employee.id,
            date=today,
            check_in=now,
            check_in_source=source,
            check_in_latitude=body.latitude,
            check_in_longitude=body.longitude,
            is_within_geofence=is_within_geofence,
            late_minutes=late_minutes,
            status=attendance_status,
            shift_id=shift_id,
        )
        db.add(record)

    await db.flush()

    # Keep the desktop app's live timer in sync — checking in on the web
    # should mean the desktop widget shows "checked in" too, without the
    # employee needing to also press Check In there.
    await ensure_work_session_started(db, tenant_id, employee.id, started_at=record.check_in)

    return {
        "id": str(record.id),
        "check_in": record.check_in.isoformat(),
        "status": record.status.value,
        "late_minutes": record.late_minutes,
    }


@router.post("/check-out", summary="Check out and compute worked/overtime minutes")
async def check_out(
    body: CheckOutRequest,
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    employee = await _resolve_employee(db, tenant_id, current_user, body.employee_id)
    now = datetime.now(timezone.utc)

    # Bug fix: this used to look up `AttendanceRecord.date == today` where
    # `today = now.date()` at CHECK-OUT time. For an overnight shift (check
    # in 11pm, check out 1am the next day), "today" at check-out is a
    # different calendar date than the check-in's record, so the record was
    # never found and check-out failed outright with "No check-in found".
    # Instead, find this employee's most recent still-open session (any
    # date) — that's the one check-out is always meant to close.
    record = (
        await db.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.employee_id == employee.id,
                AttendanceRecord.tenant_id == tenant_id,
                AttendanceRecord.check_in.isnot(None),
                AttendanceRecord.check_out.is_(None),
                AttendanceRecord.is_deleted == False,  # noqa: E712
            )
            .order_by(AttendanceRecord.check_in.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=400, detail="No check-in found to check out from")

    record.check_out = now
    record.check_out_latitude = body.latitude
    record.check_out_longitude = body.longitude
    record.check_out_source = AttendanceSource.GEO if body.latitude is not None else AttendanceSource.MANUAL

    # Stopping here (before computing totals) so we can use the WorkSession's
    # break-excluded total_minutes below — otherwise a break taken via the
    # desktop app wouldn't get subtracted from the web attendance record's
    # reported total, and the two "hours worked" numbers would disagree.
    synced_session = await ensure_work_session_ended(db, tenant_id, employee.id, ended_at=now)

    total_minutes = (
        synced_session.total_minutes
        if synced_session is not None and synced_session.total_minutes is not None
        else int((now - record.check_in).total_seconds() // 60)
    )
    record.total_minutes = total_minutes

    overtime_minutes = 0
    if record.shift_id:
        shift = (await db.execute(select(Shift).where(Shift.id == record.shift_id))).scalar_one_or_none()
        if shift:
            scheduled = _scheduled_minutes(shift)
            overtime_minutes = max(0, total_minutes - scheduled)
    record.overtime_minutes = overtime_minutes

    await db.flush()

    return {
        "id": str(record.id),
        "check_out": record.check_out.isoformat(),
        "total_minutes": record.total_minutes,
        "overtime_minutes": record.overtime_minutes,
        "late_minutes": record.late_minutes,
    }