"""
Work Session & Break API (Phase 3 — desktop app timer).

Self-service only, matching the same self-scope pattern used throughout
this codebase for attendance/leave: any authenticated user with a linked
Employee profile can start/end/break their OWN sessions. There is no
"manage others' timers" concept — that's what /attendance already covers
for HR/managers.
"""
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models.attendance import AttendanceSource
from app.models.work_session import BreakRecord, BreakType, WorkSession, WorkSessionStatus
from app.models.user import User
from app.permissions.dependencies import get_current_user, get_tenant_id
from app.repositories.employee import EmployeeRepository
from app.services.attendance_sync import ensure_attendance_checked_in, ensure_attendance_checked_out

router = APIRouter(prefix="/work-sessions", tags=["Work Sessions"])


async def _resolve_own_employee_id(db: AsyncSession, tenant_id: uuid.UUID, current_user: User) -> uuid.UUID:
    employee = await EmployeeRepository(db, tenant_id).get_by_user_id(current_user.id)
    if employee is None:
        raise NotFoundError("No employee profile is linked to this user")
    return employee.id


def _serialize(session: WorkSession, completed_break_minutes: int = 0, open_break: BreakRecord | None = None) -> dict:
    return {
        "id": str(session.id),
        "employee_id": str(session.employee_id),
        "started_at": session.started_at.isoformat(),
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        "status": session.status.value,
        "total_minutes": session.total_minutes,
        # Lets clients (web + desktop) split "time since check-in" into a
        # working timer that pauses on break and a separate break timer,
        # without each client re-deriving it from a full breaks list.
        "total_break_minutes": completed_break_minutes,
        "current_break_started_at": open_break.started_at.isoformat() if open_break else None,
    }


async def _break_totals(db: AsyncSession, session_id: uuid.UUID) -> tuple[int, BreakRecord | None]:
    """(completed break minutes so far, the currently-open break if any)."""
    breaks = (
        await db.execute(select(BreakRecord).where(BreakRecord.work_session_id == session_id))
    ).scalars().all()
    open_break = next((b for b in breaks if b.ended_at is None), None)
    completed_minutes = sum(
        int((b.ended_at - b.started_at).total_seconds() // 60) for b in breaks if b.ended_at is not None
    )
    return completed_minutes, open_break


async def _get_own_session_or_404(
    db: AsyncSession, tenant_id: uuid.UUID, session_id: uuid.UUID, employee_id: uuid.UUID
) -> WorkSession:
    session = (
        await db.execute(
            select(WorkSession).where(
                WorkSession.id == session_id,
                WorkSession.tenant_id == tenant_id,
                WorkSession.is_deleted == False,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if session is None:
        raise NotFoundError("Work session not found")
    if session.employee_id != employee_id:
        raise PermissionDeniedError("This work session belongs to a different employee")
    return session


@router.get("/me", summary="List the caller's own past work sessions (for a personal attendance table)")
async def list_my_sessions(
    page: int = 1,
    page_size: int = 25,
    current_user: User = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from sqlalchemy import func

    employee_id = await _resolve_own_employee_id(db, tenant_id, current_user)
    filters = [
        WorkSession.tenant_id == tenant_id,
        WorkSession.employee_id == employee_id,
        WorkSession.is_deleted == False,  # noqa: E712
    ]
    offset = (page - 1) * page_size
    stmt = (
        select(WorkSession)
        .where(*filters)
        .order_by(WorkSession.started_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    count_stmt = select(func.count()).select_from(WorkSession).where(*filters)

    items = (await db.execute(stmt)).scalars().all()
    total = (await db.execute(count_stmt)).scalar_one()

    serialized = []
    for s in items:
        completed_minutes, open_break = await _break_totals(db, s.id)
        serialized.append(_serialize(s, completed_minutes, open_break))

    return {
        "items": serialized,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, -(-total // page_size)),
    }


@router.get("/me/active", summary="Get the caller's currently active (or on-break) work session, if any")
async def get_active_session(
    current_user: User = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict | None:
    employee_id = await _resolve_own_employee_id(db, tenant_id, current_user)
    session = (
        await db.execute(
            select(WorkSession).where(
                WorkSession.tenant_id == tenant_id,
                WorkSession.employee_id == employee_id,
                WorkSession.status != WorkSessionStatus.ENDED,
                WorkSession.is_deleted == False,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if session is None:
        return None
    completed_minutes, open_break = await _break_totals(db, session.id)
    return _serialize(session, completed_minutes, open_break)


@router.post("/start", summary="Start (or resume) the caller's timer")
async def start_session(
    current_user: User = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Idempotent: if the caller already has an active/on-break session,
    that same one is returned rather than creating a second, overlapping
    session — clicking "Check In" twice (e.g. a double-click, or the
    button re-rendering before its own state updates) must never fork the
    timer into two concurrent sessions."""
    employee_id = await _resolve_own_employee_id(db, tenant_id, current_user)

    existing = (
        await db.execute(
            select(WorkSession).where(
                WorkSession.tenant_id == tenant_id,
                WorkSession.employee_id == employee_id,
                WorkSession.status != WorkSessionStatus.ENDED,
                WorkSession.is_deleted == False,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        completed_minutes, open_break = await _break_totals(db, existing.id)
        return _serialize(existing, completed_minutes, open_break)

    session = WorkSession(
        tenant_id=tenant_id,
        employee_id=employee_id,
        started_at=datetime.now(UTC),
        status=WorkSessionStatus.ACTIVE,
    )
    db.add(session)
    await db.flush()

    # Keep the web dashboard's Attendance table in sync — starting the
    # desktop timer should mean today's attendance shows a check-in too,
    # without the employee needing to also click Check In on the website.
    employee = await EmployeeRepository(db, tenant_id).get(employee_id)
    if employee is not None:
        await ensure_attendance_checked_in(
            db, tenant_id, employee, source=AttendanceSource.DESKTOP_AGENT, checked_in_at=session.started_at
        )

    return _serialize(session)


@router.post("/{session_id}/end", summary="End the caller's timer")
async def end_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    employee_id = await _resolve_own_employee_id(db, tenant_id, current_user)
    session = await _get_own_session_or_404(db, tenant_id, session_id, employee_id)

    if session.status == WorkSessionStatus.ENDED:
        raise HTTPException(status_code=409, detail="This session has already ended")

    # Auto-close a dangling open break rather than leaving it open forever
    # if the employee ends their day while still "on break".
    open_break = (
        await db.execute(
            select(BreakRecord).where(
                BreakRecord.work_session_id == session.id,
                BreakRecord.ended_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if open_break is not None:
        open_break.ended_at = now

    breaks = (
        await db.execute(select(BreakRecord).where(BreakRecord.work_session_id == session.id))
    ).scalars().all()
    break_minutes = sum(
        int(((b.ended_at or now) - b.started_at).total_seconds() // 60) for b in breaks
    )
    total_minutes = int((now - session.started_at).total_seconds() // 60) - break_minutes

    session.ended_at = now
    session.status = WorkSessionStatus.ENDED
    session.total_minutes = max(0, total_minutes)
    await db.flush()

    # Same reasoning as start_session above: stopping the desktop timer
    # should also close out today's web attendance record.
    await ensure_attendance_checked_out(db, tenant_id, employee_id, checked_out_at=now)

    return _serialize(session, break_minutes, None)


class BreakStartRequest(BaseModel):
    break_type_id: uuid.UUID | None = None


@router.post("/{session_id}/break/start", summary="Start a break, pausing the timer")
async def start_break(
    session_id: uuid.UUID,
    body: BreakStartRequest,
    current_user: User = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    employee_id = await _resolve_own_employee_id(db, tenant_id, current_user)
    session = await _get_own_session_or_404(db, tenant_id, session_id, employee_id)

    if session.status != WorkSessionStatus.ACTIVE:
        raise HTTPException(
            status_code=409, detail=f"Cannot start a break — session is '{session.status.value}', not active"
        )

    break_record = BreakRecord(
        tenant_id=tenant_id,
        work_session_id=session.id,
        break_type_id=body.break_type_id,
        started_at=datetime.now(UTC),
    )
    db.add(break_record)
    session.status = WorkSessionStatus.ON_BREAK
    await db.flush()

    # Return the same shape as every other endpoint here (id/status/timing
    # fields incl. current_break_started_at) instead of a bespoke dict, so
    # clients can treat every work-session response identically.
    completed_minutes, _ = await _break_totals(db, session.id)
    return _serialize(session, completed_minutes, break_record)


@router.post("/{session_id}/break/end", summary="End the current break, resuming the timer")
async def end_break(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    employee_id = await _resolve_own_employee_id(db, tenant_id, current_user)
    session = await _get_own_session_or_404(db, tenant_id, session_id, employee_id)

    if session.status != WorkSessionStatus.ON_BREAK:
        raise HTTPException(status_code=409, detail="This session is not currently on a break")

    open_break = (
        await db.execute(
            select(BreakRecord).where(
                BreakRecord.work_session_id == session.id,
                BreakRecord.ended_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if open_break is None:
        # Status said on_break but no open BreakRecord — data got out of
        # sync somehow; heal by just resuming rather than 500ing.
        session.status = WorkSessionStatus.ACTIVE
        await db.flush()
        completed_minutes, _ = await _break_totals(db, session.id)
        return _serialize(session, completed_minutes, None)

    open_break.ended_at = datetime.now(UTC)
    session.status = WorkSessionStatus.ACTIVE
    await db.flush()

    completed_minutes, _ = await _break_totals(db, session.id)
    return _serialize(session, completed_minutes, None)


@router.get("/{session_id}/breaks", summary="List breaks taken during a session")
async def list_breaks(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    employee_id = await _resolve_own_employee_id(db, tenant_id, current_user)
    session = await _get_own_session_or_404(db, tenant_id, session_id, employee_id)

    breaks = (
        await db.execute(
            select(BreakRecord).where(BreakRecord.work_session_id == session.id).order_by(BreakRecord.started_at)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": str(b.id),
                "started_at": b.started_at.isoformat(),
                "ended_at": b.ended_at.isoformat() if b.ended_at else None,
            }
            for b in breaks
        ]
    }


@router.get("/break-types", summary="List the org's configured break categories")
async def list_break_types(
    current_user: User = Depends(get_current_user),  # noqa: ARG001 — any authenticated user; read-only + tenant-scoped
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Self-service read (Phase 5): the break-type picker needs this list
    to show Lunch/Coffee/Personal/etc. instead of a bare Pause button.
    BreakType rows themselves are managed elsewhere (an admin-side CRUD is
    a separate, not-yet-built piece — out of scope here, same as
    /work-sessions being self-service-only per this file's module
    docstring). Inactive types are excluded: an employee should never be
    offered a category an admin has since retired, even though old
    BreakRecords referencing it must remain untouched for history.
    """
    types = (
        await db.execute(
            select(BreakType)
            .where(BreakType.tenant_id == tenant_id, BreakType.is_active == True)  # noqa: E712
            .order_by(BreakType.name)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": str(t.id),
                "name": t.name,
                "is_paid": t.is_paid,
                "max_minutes": t.max_minutes,
            }
            for t in types
        ]
    }