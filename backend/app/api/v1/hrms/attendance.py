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
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import EmployeeProfileNotLinkedError, NotFoundError, PermissionDeniedError
from app.core.security import create_attendance_qr_token, verify_attendance_qr_token
from app.models.attendance import (
    AttendanceRecord,
    AttendanceRegularization,
    AttendanceSource,
    AttendanceStatus,
    RegularizationStatus,
)
from app.models.employee import Employee
from app.models.organization_structure import Branch
from app.models.user import User
from app.permissions.dependencies import get_current_user, get_tenant_id, require_permission
from app.repositories.employee import EmployeeRepository
from app.services.attendance_punches import close_punch, get_open_punch, lock_employee_attendance, open_punch
from app.services.attendance_regularization import (
    approve_regularization,
    cancel_regularization,
    hr_record_day,
    reject_regularization,
    request_regularization,
)
from app.services.attendance_sync import (
    ensure_work_session_ended,
    ensure_work_session_started,
    session_break_minutes,
)

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
            raise EmployeeProfileNotLinkedError()
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
    # Last on purpose: existing callers pass the arguments above positionally.
    on_date: date | None = Query(None, alias="date", description="A single day (shorthand for date_from = date_to)"),
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
            raise EmployeeProfileNotLinkedError()
        employee_id = own.id

    # The attendance page has always sent ?date=...; this endpoint only knew
    # date_from/date_to, so the filter was silently dropped and the page listed
    # the newest records of every day, all counted as "present".
    # (isinstance, not "is not None": called directly as a function, an omitted
    # on_date is FastAPI's Query(...) placeholder, not None.)
    if isinstance(on_date, date):
        date_from = date_from or on_date
        date_to = date_to or on_date

    filters = [AttendanceRecord.is_deleted == False]
    if not getattr(current_user, "is_platform_admin", False):
        filters.append(AttendanceRecord.tenant_id == tenant_id)
    if date_from:
        filters.append(AttendanceRecord.date >= date_from)
    if date_to:
        filters.append(AttendanceRecord.date <= date_to)
    if employee_id:
        filters.append(AttendanceRecord.employee_id == employee_id)
    if status:
        filters.append(AttendanceRecord.status == status)

    offset = (page - 1) * page_size
    stmt = (
        select(AttendanceRecord, User)
        .join(Employee, AttendanceRecord.employee_id == Employee.id)
        .join(User, Employee.user_id == User.id)
        .where(*filters)
        .order_by(AttendanceRecord.date.desc())
        .offset(offset)
        .limit(page_size)
    )
    count_stmt = select(func.count()).select_from(AttendanceRecord).where(*filters)

    result = await db.execute(stmt)
    rows = result.all()
    if rows:
        items = [(attendance, user) for attendance, user in rows]
    else:
        # Keep lightweight repository tests and legacy adapters compatible
        # with the joined response.
        items = [(attendance, None) for attendance in result.scalars().all()]
    total = (await db.execute(count_stmt)).scalar_one()

    return {
        "items": [
            {
                "id": str(r.id),
                "employee_id": str(r.employee_id),
                "employee_name": (
                    user.display_name
                    or f"{user.first_name} {user.last_name}".strip()
                    if user
                    else "Unknown"
                ),
                "date": str(r.date),
                "check_in": r.check_in.isoformat() if r.check_in else None,
                "check_out": r.check_out.isoformat() if r.check_out else None,
                "status": str(r.status.value),
                "total_minutes": r.total_minutes,
                "overtime_minutes": r.overtime_minutes,
                "late_minutes": r.late_minutes,
                "is_regularized": r.is_regularized,
            }
            for r, user in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, -(-total // page_size)),
    }


@router.get("/daily", summary="Daily attendance sheet: every scheduled employee with a derived status")
async def daily_attendance(
    on_date: date | None = Query(None, alias="date", description="Defaults to today in the organisation's timezone"),
    day_status: str | None = Query(None, alias="status", description="Filter by one or more comma-separated DayStatus values, e.g. absent or present,late,half_day"),
    department_id: UUID | None = Query(None),
    branch_id: UUID | None = Query(None),
    search: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """One row per employee who was employed on the day -- present, late,
    absent, on leave, holiday, weekly off, or not-yet-decided -- worked out
    from their shift, the holiday calendar, approved leave and real punches
    (see app.services.attendance_daily). Unlike /attendance, employees who did
    not punch appear here, which is what makes "Absent" possible.

    `summary` counts the whole day (all pages, before the status filter) so
    the cards stay put while the table is filtered.
    """
    from app.services.attendance_daily import DayStatus, build_daily_sheet, summarize

    wanted: set[str] | None = None
    if day_status:
        wanted = {s.strip() for s in day_status.split(",") if s.strip()}
        unknown = wanted - {s.value for s in DayStatus}
        if unknown:
            raise HTTPException(status_code=422, detail=f"Unknown status '{sorted(unknown)[0]}'")

    employee_id: UUID | None = None
    if not current_user.has_permission("attendance.view"):
        if not current_user.has_permission("attendance.view_own"):
            raise PermissionDeniedError(
                "Viewing attendance requires the 'attendance.view' permission "
                "(or 'attendance.view_own' to see your own)."
            )
        own = await EmployeeRepository(db, tenant_id).get_by_user_id(current_user.id)
        if own is None:
            raise EmployeeProfileNotLinkedError()
        employee_id = own.id

    day, rows = await build_daily_sheet(
        db, tenant_id, on_date,
        employee_id=employee_id, department_id=department_id,
        branch_id=branch_id, search=search,
    )
    summary = summarize(rows)
    shown = [r for r in rows if wanted is None or r.status.value in wanted]
    total = len(shown)
    start = (page - 1) * page_size
    return {
        "date": str(day),
        "items": [r.as_dict() for r in shown[start:start + page_size]],
        "summary": summary,
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
    """HR sets or corrects an employee's day. `check_in`/`check_out` are
    office-clock times ("09:15" or "09:15:00") in the organisation's
    timezone; send one to change just that side.

    Now written through the day's PUNCH (audit M-7): it used to write the
    day's columns directly, and the next recalculation from punches — any
    later check-in that day, the stale-attendance sweep, a regularization —
    silently wiped HR's correction out. Each change is also recorded as an
    approved AttendanceRegularization, so there is an audit trail. A day
    with several punches must be corrected punch by punch
    (POST /attendance/regularizations). Status other than PRESENT/LATE
    (HALF_DAY, ON_LEAVE, …) is set as given; PRESENT vs LATE comes from the
    punch times.
    """
    record, created = await hr_record_day(
        db, tenant_id, current_user, employee_id, date, check_in, check_out, attendance_status
    )
    return {"id": str(record.id), "created": created}


# ── Regularization: employees ask, managers approve (audit M-7) ─────────────

class RegularizationCreate(BaseModel):
    date: date
    # The punch to correct; omit to add a missing punch (then give both times).
    punch_id: UUID | None = None
    check_in: str | None = None   # office-clock "HH:MM"
    check_out: str | None = None  # office-clock "HH:MM"
    reason: str = Field(min_length=3, max_length=2000)
    # HR filing on someone's behalf (needs attendance.regularize); omit for yourself.
    employee_id: UUID | None = None


class RegularizationReview(BaseModel):
    comments: str | None = Field(default=None, max_length=2000)


def _serialize_regularization(r: AttendanceRegularization) -> dict:
    return {
        "id": str(r.id),
        "employee_id": str(r.employee_id),
        "attendance_record_id": str(r.attendance_record_id),
        "punch_id": str(r.punch_id) if r.punch_id else None,
        "date": r.date.isoformat(),
        "requested_check_in": r.requested_punch_in.isoformat() if r.requested_punch_in else None,
        "requested_check_out": r.requested_punch_out.isoformat() if r.requested_punch_out else None,
        "reason": r.reason,
        "status": r.status.value,
        "requested_by_id": str(r.requested_by_id) if r.requested_by_id else None,
        "reviewed_by_id": str(r.reviewed_by_id) if r.reviewed_by_id else None,
        "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
        "review_comments": r.review_comments,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.post("/regularizations", status_code=status.HTTP_201_CREATED, summary="Ask for an attendance correction")
async def create_regularization(
    body: RegularizationCreate,
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """E.g. "I forgot to check out on the 17th — I left at 18:05". Nothing
    changes until a manager approves; the day keeps its current hours."""
    employee = await _resolve_employee(db, tenant_id, current_user, body.employee_id)
    reg = await request_regularization(
        db, tenant_id, current_user, employee.id, body.date, body.punch_id, body.check_in, body.check_out, body.reason
    )
    return _serialize_regularization(reg)


@router.get("/regularizations", summary="List attendance corrections")
async def list_regularizations(
    status_filter: RegularizationStatus | None = Query(None, alias="status"),
    employee_id: UUID | None = None,
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Managers (attendance.regularize) see everyone's; others see their own."""
    filters = [
        AttendanceRegularization.tenant_id == tenant_id,
        AttendanceRegularization.is_deleted == False,  # noqa: E712
    ]
    if current_user.has_permission("attendance.regularize"):
        if employee_id is not None:
            filters.append(AttendanceRegularization.employee_id == employee_id)
    else:
        own = await _resolve_employee(db, tenant_id, current_user, None)
        filters.append(AttendanceRegularization.employee_id == own.id)
    if status_filter is not None:
        filters.append(AttendanceRegularization.status == status_filter)
    rows = (
        await db.execute(
            select(AttendanceRegularization).where(*filters).order_by(AttendanceRegularization.created_at.desc())
        )
    ).scalars().all()
    return {"items": [_serialize_regularization(r) for r in rows], "total": len(rows)}


@router.post("/regularizations/{regularization_id}/approve", summary="Approve a correction (applies it)")
async def approve_regularization_endpoint(
    regularization_id: UUID,
    body: RegularizationReview | None = None,
    current_user: User = Depends(require_permission("attendance.regularize")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    reg = await approve_regularization(
        db, tenant_id, current_user, regularization_id, body.comments if body else None
    )
    return _serialize_regularization(reg)


@router.post("/regularizations/{regularization_id}/reject", summary="Reject a correction")
async def reject_regularization_endpoint(
    regularization_id: UUID,
    body: RegularizationReview | None = None,
    current_user: User = Depends(require_permission("attendance.regularize")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    reg = await reject_regularization(
        db, tenant_id, current_user, regularization_id, body.comments if body else None
    )
    return _serialize_regularization(reg)


@router.post("/regularizations/{regularization_id}/cancel", summary="Withdraw your own pending correction")
async def cancel_regularization_endpoint(
    regularization_id: UUID,
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    reg = await cancel_regularization(db, tenant_id, current_user, regularization_id)
    return _serialize_regularization(reg)


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
    await lock_employee_attendance(db, employee.id)  # one check-in/out at a time per employee
    now = datetime.now(timezone.utc)
    # The organisation's calendar day, not UTC's (audit H-1): in UTC+5 a
    # 02:00 check-in used to be filed under the previous day.

    # One open punch at a time — the same rule the desktop app follows.
    # (This used to be "one check-in per calendar day", which refused a
    # second check-in after lunch and after any desktop session.)
    if await get_open_punch(db, tenant_id, employee.id) is not None:
        raise HTTPException(status_code=400, detail="You're already checked in — check out first")

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

    # Web check-in is now the SAME operation as a desktop check-in (audit
    # C-4): open a punch, and let recalculate_from_punches derive the day —
    # first check-in, totals, and LATE/PRESENT in the organisation's
    # timezone. It used to write AttendanceRecord.check_in directly and
    # create no punch, so web and desktop kept two different truths.
    _, record = await open_punch(
        db, tenant_id=tenant_id, employee_id=employee.id, at=now, source=source,
        shift_id=employee.default_shift_id, latitude=body.latitude, longitude=body.longitude,
    )
    if record.punch_count == 1:
        # Location details describe the day's first check-in.
        record.check_in_latitude = body.latitude
        record.check_in_longitude = body.longitude
        record.is_within_geofence = is_within_geofence
    await db.flush()

    # Keep the desktop app's live timer in sync — checking in on the web
    # should mean the desktop widget shows "checked in" too, without the
    # employee needing to also press Check In there.
    # `now`, not record.check_in: with several punches a day, check_in is
    # the day's FIRST one, and a second check-in's timer must start now.
    await ensure_work_session_started(db, tenant_id, employee.id, started_at=now)

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
    await lock_employee_attendance(db, employee.id)  # one check-in/out at a time per employee
    now = datetime.now(timezone.utc)

    # Web check-out is now the SAME operation as a desktop check-out (audit
    # C-4): close the employee's open punch — whichever app opened it, and
    # whatever day it was opened on (overnight shifts) — and let the day be
    # recalculated from its punches. It used to write check_out straight
    # onto the record and leave the punch open, so desktop and web could
    # never agree on whether someone was still working.
    open_punch_row = await get_open_punch(db, tenant_id, employee.id)

    # End the timer first: its break-excluded total tells us how much of
    # the punch was spent on breaks taken in the desktop app.
    synced_session = await ensure_work_session_ended(db, tenant_id, employee.id, ended_at=now)
    break_minutes = session_break_minutes(synced_session)

    if open_punch_row is None:
        if synced_session is not None:
            # A timer was running with no attendance punch behind it (data
            # left behind by the old code). Stop the timer so the widget
            # doesn't stay stuck on "checked in"; there is no punch to close.
            return {
                "id": None,
                "check_out": now.isoformat(),
                "total_minutes": synced_session.total_minutes,
                "overtime_minutes": 0,
                "late_minutes": 0,
            }
        raise HTTPException(status_code=400, detail="No check-in found to check out from")

    _, record = await close_punch(
        db, open_punch_row, at=now,
        source=AttendanceSource.GEO if body.latitude is not None else AttendanceSource.MANUAL,
        latitude=body.latitude, longitude=body.longitude, break_minutes=break_minutes,
    )
    record.check_out_latitude = body.latitude
    record.check_out_longitude = body.longitude
    await db.flush()

    return {
        "id": str(record.id),
        "check_out": record.check_out.isoformat(),
        "total_minutes": record.total_minutes,
        "overtime_minutes": record.overtime_minutes,
        "late_minutes": record.late_minutes,
    }