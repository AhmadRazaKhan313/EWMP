"""
Device management API endpoints.

Includes the actual agent-facing surface that the previous "lock/restart"
endpoints were missing: enrollment + heartbeat. Without these, lock/restart
only ever wrote a row to `pending_actions` that nothing would ever read —
there was no agent process anywhere that could pick it up. See
`agent/ewmp_agent.py` for the companion script that calls these endpoints.
"""

import platform
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from jose import JWTError
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.core.security import (
    create_agent_token,
    create_device_enrollment_token,
    verify_agent_token,
    verify_device_enrollment_token,
)
from app.models.devices import Device, DeviceMetric, DeviceOS, DeviceScreenshot, DeviceStatus, DeviceAlert
from app.models.user import User
from app.permissions.dependencies import get_current_user, get_tenant_id, require_permission
from app.repositories.employee import EmployeeRepository

router = APIRouter(prefix="/devices", tags=["Devices"])


# ── Agent auth ─────────────────────────────────────────────────────────────
async def get_current_device(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
) -> Device:
    """Verify the agent's bearer JWT and load its Device row."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing agent bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = verify_agent_token(token)
    except (JWTError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired agent token")

    device_id = payload.get("sub")
    device = (
        await db.execute(select(Device).where(Device.id == device_id))
    ).scalar_one_or_none()
    if device is None or not device.is_enrolled:
        raise HTTPException(status_code=401, detail="Device not enrolled")
    return device


def _compute_health_score(m: "HeartbeatRequest") -> tuple[int, list[str]]:
    """Cheap heuristic health score (0-100). Real thresholds can move to Settings later."""
    score = 100
    issues: list[str] = []
    if m.disk_usage_percent is not None and m.disk_usage_percent > 90:
        score -= 25
        issues.append("Disk usage above 90%")
    if m.ram_usage_percent is not None and m.ram_usage_percent > 90:
        score -= 20
        issues.append("RAM usage above 90%")
    if m.cpu_usage_percent is not None and m.cpu_usage_percent > 95:
        score -= 10
        issues.append("Sustained high CPU usage")
    if m.battery_percent is not None and m.battery_percent < 15 and not m.battery_is_charging:
        score -= 10
        issues.append("Battery critically low")
    return max(0, score), issues


# ── Schemas ────────────────────────────────────────────────────────────────
class EnrollRequest(BaseModel):
    enrollment_token: str
    hostname: str
    os_type: DeviceOS = DeviceOS.OTHER
    os_name: str | None = None
    os_version: str | None = None
    cpu_model: str | None = None
    cpu_cores: int | None = None
    ram_total_gb: float | None = None
    disk_total_gb: float | None = None
    mac_address: str | None = None
    agent_version: str | None = None


class SelfEnrollRequest(BaseModel):
    """Same hardware fields as EnrollRequest, minus enrollment_token — the
    caller's own access token (see get_current_user) is the credential
    instead, since this is called by a logged-in employee's desktop-app,
    not an unattended agent."""

    hostname: str
    os_type: DeviceOS = DeviceOS.OTHER
    os_name: str | None = None
    os_version: str | None = None
    cpu_model: str | None = None
    cpu_cores: int | None = None
    ram_total_gb: float | None = None
    disk_total_gb: float | None = None
    mac_address: str | None = None
    agent_version: str | None = None
    # Required, not optional: desktop-app must have shown its consent
    # notice (mirrors agent/ewmp_agent.py's ensure_consent_notice_shown())
    # before this call is ever made — see ConsentNotice.tsx. This flag is
    # a server-side record that the employee saw it, not a substitute for
    # actually showing it; the desktop-app is expected to gate this call
    # on the renderer side and never send True without having displayed it.
    consent_acknowledged: bool


class HeartbeatRequest(BaseModel):
    cpu_usage_percent: float | None = None
    ram_usage_percent: float | None = None
    ram_used_gb: float | None = None
    disk_usage_percent: float | None = None
    disk_used_gb: float | None = None
    battery_percent: float | None = None
    battery_is_charging: bool | None = None
    uptime_seconds: int | None = None
    active_user: str | None = None
    public_ip: str | None = None
    local_ip: str | None = None
    installed_apps: list | None = None
    running_processes: list | None = None


# ── Enrollment ───────────────────────────────────────────────────────────────
@router.get("/enrollment-token", summary="Generate a device enrollment token for this org")
async def get_enrollment_token(
    current_user: User = Depends(require_permission("devices.enroll")),
    tenant_id: UUID = Depends(get_tenant_id),
) -> dict:
    """
    Paste the returned token into the agent's config once during install
    (see agent/README.md). It's org-scoped and long-lived — rotate it by
    calling this again and re-configuring agents if it's ever compromised.
    It is NOT a per-device credential; POST /devices/enroll exchanges it
    for a real per-device agent token, which is what agents use afterward.
    """
    token = create_device_enrollment_token(str(tenant_id))
    return {"enrollment_token": token, "expires_in_days": 365}


@router.post("/enroll", summary="Agent self-enrollment (called once by the desktop agent)")
async def enroll_device(
    body: EnrollRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """No user auth here — the enrollment_token itself is the credential, since
    the agent runs unattended with no human logged into EWMP."""
    try:
        payload = verify_device_enrollment_token(body.enrollment_token)
    except (JWTError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired enrollment token")
    tenant_id = payload["tenant_id"]

    import uuid as _uuid
    import hashlib

    device = Device(
        tenant_id=tenant_id,
        hostname=body.hostname,
        device_name=body.hostname,
        agent_id=str(_uuid.uuid4()),
        agent_version=body.agent_version,
        agent_token_hash="",  # set below once we know the token
        os_type=body.os_type,
        os_name=body.os_name,
        os_version=body.os_version,
        cpu_model=body.cpu_model,
        cpu_cores=body.cpu_cores,
        ram_total_gb=body.ram_total_gb,
        disk_total_gb=body.disk_total_gb,
        mac_address=body.mac_address,
        status=DeviceStatus.ONLINE,
        last_seen_at=datetime.now(timezone.utc),
        last_heartbeat_at=datetime.now(timezone.utc),
        is_enrolled=True,
    )
    db.add(device)
    await db.flush()  # need device.id before minting its token

    agent_token = create_agent_token(str(device.id))
    device.agent_token_hash = hashlib.sha256(agent_token.encode()).hexdigest()
    await db.flush()

    return {"device_id": str(device.id), "agent_token": agent_token}


@router.post(
    "/self-enroll",
    summary="Employee self-enrollment (called by desktop-app on login, no admin token needed)",
)
async def self_enroll_device(
    body: SelfEnrollRequest,
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Companion to POST /enroll (the unattended agent path, gated by an
    admin-issued enrollment_token). This path is for desktop-app: the
    employee is already logged in with a normal access token, so that
    token itself is the credential — no separate enrollment_token to
    generate, copy, and paste.

    Idempotent per (tenant, employee, hostname): a device already
    registered for this employee/hostname pair is updated and re-issued
    a fresh agent token rather than duplicated, so logging in from the
    same machine repeatedly doesn't create a new row in the fleet table
    every time.
    """
    if not body.consent_acknowledged:
        raise HTTPException(
            status_code=400,
            detail="Device monitoring notice must be acknowledged before enrollment.",
        )

    employee = await EmployeeRepository(db, tenant_id).get_by_user_id(current_user.id)
    if employee is None:
        raise HTTPException(
            status_code=400,
            detail="No employee record linked to this account — cannot self-enroll a device.",
        )

    import hashlib
    import uuid as _uuid

    now = datetime.now(timezone.utc)
    existing = (
        await db.execute(
            select(Device).where(
                Device.tenant_id == tenant_id,
                Device.assigned_employee_id == employee.id,
                Device.hostname == body.hostname,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        device = existing
        device.device_name = device.device_name or body.hostname
        device.os_type = body.os_type
        device.os_name = body.os_name
        device.os_version = body.os_version
        device.cpu_model = body.cpu_model
        device.cpu_cores = body.cpu_cores
        device.ram_total_gb = body.ram_total_gb
        device.disk_total_gb = body.disk_total_gb
        device.mac_address = body.mac_address
        device.agent_version = body.agent_version
        device.is_enrolled = True
    else:
        device = Device(
            tenant_id=tenant_id,
            hostname=body.hostname,
            device_name=body.hostname,
            agent_id=str(_uuid.uuid4()),
            agent_version=body.agent_version,
            agent_token_hash="",  # set below once we know the token
            os_type=body.os_type,
            os_name=body.os_name,
            os_version=body.os_version,
            cpu_model=body.cpu_model,
            cpu_cores=body.cpu_cores,
            ram_total_gb=body.ram_total_gb,
            disk_total_gb=body.disk_total_gb,
            mac_address=body.mac_address,
            assigned_employee_id=employee.id,
            is_enrolled=True,
        )
        db.add(device)

    device.status = DeviceStatus.ONLINE
    device.last_seen_at = now
    device.last_heartbeat_at = now
    await db.flush()  # need device.id before minting its token

    agent_token = create_agent_token(str(device.id))
    device.agent_token_hash = hashlib.sha256(agent_token.encode()).hexdigest()
    await db.flush()

    return {"device_id": str(device.id), "agent_token": agent_token}


@router.post("/heartbeat", summary="Agent heartbeat — metrics in, pending actions out")
async def heartbeat(
    body: HeartbeatRequest,
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
) -> dict:
    now = datetime.now(timezone.utc)
    device.last_seen_at = now
    device.last_heartbeat_at = now
    device.status = DeviceStatus.ONLINE
    if body.public_ip:
        device.public_ip = body.public_ip
    if body.local_ip:
        device.local_ip = body.local_ip
    if body.installed_apps is not None:
        device.installed_apps = body.installed_apps
    if body.running_processes is not None:
        device.running_processes = body.running_processes

    score, issues = _compute_health_score(body)
    device.health_score = score
    device.health_issues = issues

    db.add(DeviceMetric(
        tenant_id=device.tenant_id,
        device_id=device.id,
        recorded_at=now,
        cpu_usage_percent=body.cpu_usage_percent,
        ram_usage_percent=body.ram_usage_percent,
        ram_used_gb=body.ram_used_gb,
        disk_usage_percent=body.disk_usage_percent,
        disk_used_gb=body.disk_used_gb,
        battery_percent=body.battery_percent,
        battery_is_charging=body.battery_is_charging,
        uptime_seconds=body.uptime_seconds,
        active_user=body.active_user,
    ))

    # Hand over queued actions and clear the queue — the agent is
    # responsible for actually executing them locally (lock/restart).
    #
    # Bug fix: re-fetch this row with a lock before touching
    # pending_actions, matching _queue_device_action above. Without it, an
    # admin's lock_device()/restart_device()/etc. running concurrently with
    # this heartbeat could race: the admin appends to an in-memory list
    # read a moment ago, then this heartbeat's write clears the whole
    # column, silently discarding the admin's just-queued action.
    locked_device = (
        await db.execute(select(Device).where(Device.id == device.id).with_for_update())
    ).scalar_one()
    actions = list(locked_device.pending_actions or [])
    locked_device.pending_actions = []
    await db.flush()

    from app.core.config import settings
    return {
        "actions": actions,
        "health_score": score,
        # Sent on every heartbeat so the agent always has the current
        # list without a separate polling endpoint. See DeviceAlert's
        # docstring for why this drives flagged-match alerts only, not
        # full activity/browsing logging.
        "activity_watchlist": settings.DEVICE_ACTIVITY_WATCHLIST,
    }


@router.get("", summary="List all enrolled devices")
async def list_devices(
    status: DeviceStatus | None = Query(None),
    employee_id: UUID | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    current_user: User = Depends(require_permission("devices.view")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    filters = [Device.tenant_id == tenant_id, Device.is_deleted == False]
    if status:
        filters.append(Device.status == status)
    if employee_id:
        filters.append(Device.assigned_employee_id == employee_id)

    offset = (page - 1) * page_size
    stmt = select(Device).where(*filters).order_by(Device.last_seen_at.desc()).offset(offset).limit(page_size)
    count_stmt = select(func.count()).select_from(Device).where(*filters)
    items = (await db.execute(stmt)).scalars().all()
    total = (await db.execute(count_stmt)).scalar_one()

    # Latest metric snapshot per device, in one bounded query.
    #
    # Bug fix: this used to fetch EVERY historical DeviceMetric row for
    # these devices with no LIMIT — heartbeats arrive roughly every 60s, so
    # a device that's been online for months could have hundreds of
    # thousands of rows, all loaded into memory just to keep 1 per device
    # in a Python dict below. A row_number() window function bounds this
    # to exactly one row per device at the SQL level instead.
    device_ids = [d.id for d in items]
    latest_metrics: dict[UUID, DeviceMetric] = {}
    if device_ids:
        row_number_col = (
            func.row_number()
            .over(partition_by=DeviceMetric.device_id, order_by=DeviceMetric.recorded_at.desc())
            .label("rn")
        )
        ranked_subq = (
            select(DeviceMetric, row_number_col)
            .where(DeviceMetric.device_id.in_(device_ids))
            .subquery()
        )
        latest_metric_alias = aliased(DeviceMetric, ranked_subq)
        metric_stmt = select(latest_metric_alias).where(ranked_subq.c.rn == 1)
        rows = (await db.execute(metric_stmt)).scalars().all()
        for m in rows:
            latest_metrics[m.device_id] = m

    def _metric_field(device_id: UUID, field: str):
        metric = latest_metrics.get(device_id)
        return getattr(metric, field) if metric is not None else None

    return {
        "items": [
            {
                "id": str(d.id),
                "hostname": d.hostname,
                "device_name": d.device_name,
                "os_type": d.os_type.value,
                "os_name": d.os_name,
                "os_version": d.os_version,
                "status": d.status.value,
                "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
                "health_score": d.health_score,
                "cpu_usage_percent": _metric_field(d.id, "cpu_usage_percent"),
                "ram_usage_percent": _metric_field(d.id, "ram_usage_percent"),
                "disk_usage_percent": _metric_field(d.id, "disk_usage_percent"),
                "assigned_employee_id": str(d.assigned_employee_id) if d.assigned_employee_id else None,
                "public_ip": d.public_ip,
                "local_ip": d.local_ip,
            }
            for d in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, -(-total // page_size)),
    }


@router.get("/activity-watchlist", summary="The org-wide watch-list, for building allow-list checkboxes")
async def get_activity_watchlist(
    current_user: User = Depends(require_permission("devices.enroll")),
) -> dict:
    from app.core.config import settings
    return {"watchlist": settings.DEVICE_ACTIVITY_WATCHLIST}


@router.get(
    "/alerts",
    summary="Org-wide, filterable, paginated alert inbox — for the fleet-scale alerts screen",
)
async def list_all_alerts(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    alert_type: str | None = Query(None, description="flagged_app_usage | flagged_browsing"),
    is_acknowledged: bool | None = Query(None),
    device_id: UUID | None = Query(None),
    days: int = Query(7, ge=1, le=90, description="Only alerts from the last N days"),
    current_user: User = Depends(require_permission("devices.view_alerts")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Unlike /alerts/recent (which powers the small notification-bell
    dropdown and is capped at 100 rows from the last N minutes), this is
    the backing endpoint for a dedicated, paginated alerts screen — the
    thing an admin actually needs once there are hundreds or thousands
    of devices. Clicking into every device's drawer one at a time to
    check for alerts doesn't scale past a handful of machines; this
    endpoint lets the whole org's alert activity be triaged from one
    screen, filtered and paged like any other list view in the product.
    """
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    filters = [DeviceAlert.tenant_id == tenant_id, DeviceAlert.occurred_at >= cutoff]

    if alert_type:
        from app.models.devices import DeviceAlertType
        try:
            filters.append(DeviceAlert.alert_type == DeviceAlertType(alert_type))
        except ValueError:
            pass  # unknown filter value — just ignore rather than error, keeps the UI simple
    if is_acknowledged is not None:
        filters.append(DeviceAlert.is_acknowledged == is_acknowledged)
    if device_id is not None:
        filters.append(DeviceAlert.device_id == device_id)

    offset = (page - 1) * page_size
    stmt = (
        select(DeviceAlert)
        .where(*filters)
        .order_by(DeviceAlert.occurred_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    count_stmt = select(func.count()).select_from(DeviceAlert).where(*filters)

    rows = (await db.execute(stmt)).scalars().all()
    total = (await db.execute(count_stmt)).scalar_one()

    device_ids = {a.device_id for a in rows}
    devices_by_id = {}
    if device_ids:
        device_rows = (
            await db.execute(select(Device).where(Device.id.in_(device_ids)))
        ).scalars().all()
        devices_by_id = {d.id: d for d in device_rows}

    return {
        "items": [
            {
                "id": str(a.id),
                "device_id": str(a.device_id),
                "device_name": (devices_by_id.get(a.device_id).device_name if devices_by_id.get(a.device_id) else None)
                    or (devices_by_id.get(a.device_id).hostname if devices_by_id.get(a.device_id) else "Unknown device"),
                "alert_type": a.alert_type.value,
                "matched_term": a.matched_term,
                "detail": a.detail,
                "occurred_at": a.occurred_at.isoformat(),
                "is_acknowledged": a.is_acknowledged,
            }
            for a in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, -(-total // page_size)),
        "unacknowledged_count": (
            await db.execute(
                select(func.count()).select_from(DeviceAlert).where(
                    DeviceAlert.tenant_id == tenant_id,
                    DeviceAlert.occurred_at >= cutoff,
                    DeviceAlert.is_acknowledged == False,  # noqa: E712
                )
            )
        ).scalar_one(),
    }


class BulkAcknowledgeRequest(BaseModel):
    alert_ids: list[UUID]


@router.post("/alerts/acknowledge-bulk", summary="Acknowledge multiple alerts at once")
async def acknowledge_alerts_bulk(
    body: BulkAcknowledgeRequest,
    current_user: User = Depends(require_permission("devices.view_alerts")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not body.alert_ids:
        return {"acknowledged": 0}
    result = await db.execute(
        select(DeviceAlert).where(
            DeviceAlert.id.in_(body.alert_ids), DeviceAlert.tenant_id == tenant_id
        )
    )
    rows = result.scalars().all()
    for row in rows:
        row.is_acknowledged = True
    await db.flush()
    return {"acknowledged": len(rows)}


@router.get("/{device_id}", summary="Get full device detail")
async def get_device(
    device_id: UUID,
    current_user: User = Depends(require_permission("devices.view")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Full detail for a device's page/drawer — the old version of this
    endpoint returned only {id, hostname, status}, which is why there was
    no usable device detail view: there was nothing to show beyond what
    the list table already had.
    """
    result = await db.execute(
        select(Device).where(Device.id == device_id, Device.tenant_id == tenant_id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise NotFoundError("Device not found")

    latest_metric = (
        await db.execute(
            select(DeviceMetric)
            .where(DeviceMetric.device_id == device.id)
            .order_by(DeviceMetric.recorded_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    assigned_employee = None
    if device.assigned_employee_id:
        from sqlalchemy.orm import selectinload
        from app.models.employee import Employee
        emp = (
            await db.execute(
                select(Employee)
                .options(selectinload(Employee.user))
                .where(Employee.id == device.assigned_employee_id)
            )
        ).scalar_one_or_none()
        if emp:
            assigned_employee = {
                "id": str(emp.id),
                "full_name": (
                    f"{emp.user.first_name} {emp.user.last_name}".strip()
                    if emp.user
                    else None
                ),
                "employee_code": emp.employee_code,
            }

    return {
        "id": str(device.id),
        "hostname": device.hostname,
        "device_name": device.device_name,
        "serial_number": device.serial_number,
        "asset_tag": device.asset_tag,
        "status": device.status.value,
        "is_enrolled": device.is_enrolled,
        "agent_version": device.agent_version,
        "os_type": device.os_type.value,
        "os_name": device.os_name,
        "os_version": device.os_version,
        "os_build": device.os_build,
        "bios_version": device.bios_version,
        "motherboard": device.motherboard,
        "cpu_model": device.cpu_model,
        "cpu_cores": device.cpu_cores,
        "cpu_threads": device.cpu_threads,
        "ram_total_gb": device.ram_total_gb,
        "disk_total_gb": device.disk_total_gb,
        "gpu_model": device.gpu_model,
        "public_ip": device.public_ip,
        "local_ip": device.local_ip,
        "mac_address": device.mac_address,
        "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
        "last_heartbeat_at": device.last_heartbeat_at.isoformat() if device.last_heartbeat_at else None,
        "health_score": device.health_score,
        "health_issues": device.health_issues or [],
        "installed_apps": device.installed_apps or [],
        "assigned_employee": assigned_employee,
        "branch_id": str(device.branch_id) if device.branch_id else None,
        "notes": device.notes,
        "latest_metric": (
            {
                "recorded_at": latest_metric.recorded_at.isoformat(),
                "cpu_usage_percent": latest_metric.cpu_usage_percent,
                "ram_usage_percent": latest_metric.ram_usage_percent,
                "ram_used_gb": latest_metric.ram_used_gb,
                "disk_usage_percent": latest_metric.disk_usage_percent,
                "disk_used_gb": latest_metric.disk_used_gb,
                "battery_percent": latest_metric.battery_percent,
                "battery_is_charging": latest_metric.battery_is_charging,
                "uptime_seconds": latest_metric.uptime_seconds,
                "active_user": latest_metric.active_user,
            }
            if latest_metric
            else None
        ),
    }


@router.get("/{device_id}/metrics", summary="Metrics history for charts")
async def get_device_metrics(
    device_id: UUID,
    hours: int = Query(24, ge=1, le=720, description="How far back to look"),
    current_user: User = Depends(require_permission("devices.view")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    device = (
        await db.execute(select(Device).where(Device.id == device_id, Device.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if not device:
        raise NotFoundError("Device not found")

    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (
        await db.execute(
            select(DeviceMetric)
            .where(DeviceMetric.device_id == device_id, DeviceMetric.recorded_at >= cutoff)
            .order_by(DeviceMetric.recorded_at.asc())
        )
    ).scalars().all()

    return {
        "device_id": str(device_id),
        "points": [
            {
                "recorded_at": r.recorded_at.isoformat(),
                "cpu_usage_percent": r.cpu_usage_percent,
                "ram_usage_percent": r.ram_usage_percent,
                "disk_usage_percent": r.disk_usage_percent,
                "battery_percent": r.battery_percent,
            }
            for r in rows
        ],
    }


class DeviceUpdateRequest(BaseModel):
    device_name: str | None = None
    branch_id: UUID | None = None
    asset_tag: str | None = None
    notes: str | None = None


@router.get("/{device_id}/processes", summary="Running processes snapshot")
async def get_device_processes(
    device_id: UUID,
    current_user: User = Depends(require_permission("devices.view_processes")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Returns whatever was captured on the device's most recent heartbeat.
    This is a point-in-time snapshot, not live — the agent only reports
    processes once per heartbeat interval (default 60s), same as metrics.
    """
    device = (
        await db.execute(select(Device).where(Device.id == device_id, Device.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if not device:
        raise NotFoundError("Device not found")
    return {
        "device_id": str(device_id),
        "captured_at": device.last_heartbeat_at.isoformat() if device.last_heartbeat_at else None,
        "processes": device.running_processes or [],
    }


@router.patch("/{device_id}", summary="Update device metadata (friendly name, branch, notes)")
async def update_device(
    device_id: UUID,
    body: DeviceUpdateRequest,
    current_user: User = Depends(require_permission("devices.enroll")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    device = (
        await db.execute(select(Device).where(Device.id == device_id, Device.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if not device:
        raise NotFoundError("Device not found")

    if body.device_name is not None:
        device.device_name = body.device_name
    if body.branch_id is not None:
        device.branch_id = body.branch_id
    if body.asset_tag is not None:
        device.asset_tag = body.asset_tag
    if body.notes is not None:
        device.notes = body.notes
    await db.flush()
    return {"id": str(device.id), "message": "Device updated"}


class AssignDeviceRequest(BaseModel):
    employee_id: UUID


@router.post("/{device_id}/assign", summary="Assign this device to an employee")
async def assign_device(
    device_id: UUID,
    body: AssignDeviceRequest,
    current_user: User = Depends(require_permission("devices.enroll")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    device = (
        await db.execute(select(Device).where(Device.id == device_id, Device.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if not device:
        raise NotFoundError("Device not found")

    from app.models.employee import Employee
    employee = (
        await db.execute(
            select(Employee).where(Employee.id == body.employee_id, Employee.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if not employee:
        raise NotFoundError("Employee not found")

    device.assigned_employee_id = employee.id
    await db.flush()
    return {"id": str(device.id), "assigned_employee_id": str(employee.id)}


@router.post("/{device_id}/unassign", summary="Unassign this device from its current employee")
async def unassign_device(
    device_id: UUID,
    current_user: User = Depends(require_permission("devices.enroll")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    device = (
        await db.execute(select(Device).where(Device.id == device_id, Device.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if not device:
        raise NotFoundError("Device not found")

    device.assigned_employee_id = None
    await db.flush()
    return {"id": str(device.id), "message": "Device unassigned"}


async def _queue_device_action(
    db: AsyncSession, device_id: UUID, tenant_id: UUID, action: dict
) -> Device:
    """Append one action to a device's pending_actions queue.

    Bug fix: every one of the 5 call sites below used to do a plain
    read-modify-write (`actions = list(device.pending_actions or []);
    actions.append(...); device.pending_actions = actions`) with no
    locking. Two admins queuing actions for the same device at nearly the
    same time would race: both read the same starting list, and whichever
    write commits second silently overwrites the first — that admin's
    action is lost even though they got a "queued" success response.

    `.with_for_update()` takes a row-level lock on the device row for the
    duration of this transaction, so a second concurrent request on the
    same device blocks until the first commits, then reads the
    already-updated list. `pending_actions` is a plain `json` column (not
    `jsonb`), so a DB-side atomic concat isn't available here — row
    locking is the correct fix for this column type.
    """
    device = (
        await db.execute(
            select(Device).where(Device.id == device_id, Device.tenant_id == tenant_id).with_for_update()
        )
    ).scalar_one_or_none()
    if not device:
        raise NotFoundError("Device not found")
    actions = list(device.pending_actions or [])
    actions.append(action)
    device.pending_actions = actions
    await db.flush()
    return device


@router.post("/{device_id}/actions/lock", summary="Lock device remotely")
async def lock_device(
    device_id: UUID,
    current_user: User = Depends(require_permission("devices.remote_control")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _queue_device_action(db, device_id, tenant_id, {"action": "lock", "requested_by": str(current_user.id)})
    return {"message": "Lock command queued", "device_id": str(device_id)}


@router.post("/{device_id}/actions/restart", summary="Restart device remotely")
async def restart_device(
    device_id: UUID,
    current_user: User = Depends(require_permission("devices.remote_control")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _queue_device_action(db, device_id, tenant_id, {"action": "restart", "requested_by": str(current_user.id)})
    return {"message": "Restart command queued", "device_id": str(device_id)}


@router.post("/{device_id}/actions/shutdown", summary="Shut down device remotely")
async def shutdown_device(
    device_id: UUID,
    current_user: User = Depends(require_permission("devices.remote_control")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _queue_device_action(db, device_id, tenant_id, {"action": "shutdown", "requested_by": str(current_user.id)})
    return {"message": "Shutdown command queued", "device_id": str(device_id)}


class MessageDeviceRequest(BaseModel):
    message: str


@router.post("/{device_id}/actions/message", summary="Pop a message on the device's screen")
async def message_device(
    device_id: UUID,
    body: MessageDeviceRequest,
    # Higher-tier permission than lock/restart/shutdown — this reaches the
    # employee directly rather than just the machine's power state.
    current_user: User = Depends(require_permission("devices.remote_commands")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _queue_device_action(
        db, device_id, tenant_id, {"action": "message", "text": body.message, "requested_by": str(current_user.id)}
    )
    return {"message": "Message command queued", "device_id": str(device_id)}


# ── Screen monitoring ────────────────────────────────────────────────────────
#
# On-demand only — an admin explicitly requests a capture, the agent takes
# ONE screenshot on its next check-in (within ~heartbeat interval) and
# uploads it, and the request stays in the audit trail (requested_by_id +
# captured_at). There is no continuous recording/live-streaming mode.
@router.post(
    "/{device_id}/screenshot/request",
    summary="Request a one-off screenshot from the device",
)
async def request_screenshot(
    device_id: UUID,
    current_user: User = Depends(require_permission("devices.view_screen")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _queue_device_action(
        db, device_id, tenant_id, {"action": "screenshot", "requested_by": str(current_user.id)}
    )
    return {"message": "Screenshot requested — will arrive on the device's next check-in", "device_id": str(device_id)}


class ScreenshotUploadMeta(BaseModel):
    mime_type: str = "image/png"
    width: int | None = None
    height: int | None = None
    requested_by: str | None = None


@router.post(
    "/screenshots/upload",
    summary="[Agent] Upload a captured screenshot",
)
async def upload_screenshot(
    file: UploadFile = File(...),
    mime_type: str = Form("image/png"),
    width: int | None = Form(None),
    height: int | None = Form(None),
    requested_by: str | None = Form(None),
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.core.storage import get_storage
    from app.core.exceptions import BadRequestError

    content = await file.read()
    if not content:
        raise BadRequestError("Empty screenshot upload")
    if len(content) > 15 * 1024 * 1024:
        raise BadRequestError("Screenshot exceeds the 15 MB upload limit")

    storage = get_storage()
    key = f"devices/{device.tenant_id}/{device.id}/screenshots/{uuid4().hex}.png"
    await storage.save(key, content)

    screenshot = DeviceScreenshot(
        tenant_id=device.tenant_id,
        device_id=device.id,
        storage_key=key,
        mime_type=mime_type,
        file_size_bytes=len(content),
        width=width,
        height=height,
        captured_at=datetime.now(timezone.utc),
        requested_by_id=UUID(requested_by) if requested_by else None,
    )
    db.add(screenshot)
    await db.flush()
    return {"id": str(screenshot.id), "message": "Screenshot uploaded"}


@router.get(
    "/{device_id}/screenshots",
    summary="List a device's screenshot history",
)
async def list_screenshots(
    device_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_permission("devices.view_screen")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    device = (
        await db.execute(select(Device).where(Device.id == device_id, Device.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if not device:
        raise NotFoundError("Device not found")

    rows = (
        await db.execute(
            select(DeviceScreenshot)
            .where(DeviceScreenshot.device_id == device_id, DeviceScreenshot.tenant_id == tenant_id)
            .order_by(DeviceScreenshot.captured_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    return {
        "items": [
            {
                "id": str(s.id),
                "captured_at": s.captured_at.isoformat(),
                "width": s.width,
                "height": s.height,
                "file_size_bytes": s.file_size_bytes,
                "requested_by_id": str(s.requested_by_id) if s.requested_by_id else None,
            }
            for s in rows
        ],
        "total": len(rows),
    }


@router.get(
    "/{device_id}/screenshots/{screenshot_id}/image",
    summary="Fetch the actual screenshot image",
)
async def get_screenshot_image(
    device_id: UUID,
    screenshot_id: UUID,
    current_user: User = Depends(require_permission("devices.view_screen")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    screenshot = (
        await db.execute(
            select(DeviceScreenshot).where(
                DeviceScreenshot.id == screenshot_id,
                DeviceScreenshot.device_id == device_id,
                DeviceScreenshot.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not screenshot:
        raise NotFoundError("Screenshot not found")

    from app.core.storage import get_storage
    storage = get_storage()
    content = await storage.read(screenshot.storage_key)
    return Response(content=content, media_type=screenshot.mime_type)


# ── Activity Alerts (flagged-match only — see DeviceAlert docstring) ────────
class AlertUploadItem(BaseModel):
    alert_type: str  # "flagged_app_usage" | "flagged_browsing"
    matched_term: str
    detail: str
    occurred_at: datetime


class AlertUploadRequest(BaseModel):
    alerts: list[AlertUploadItem]


@router.post("/alerts/upload", summary="[Agent] Upload flagged-activity alerts")
async def upload_alerts(
    body: AlertUploadRequest,
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Accepts only watch-list matches the agent already filtered locally —
    see DeviceAlert's docstring. This endpoint does not accept, and the
    schema above cannot represent, a full activity/browsing log entry.

    Per-device allow-list overrides (DeviceAllowedApp) are applied here,
    not on the agent — the agent has no concept of "allowed"; it just
    reports every match against the global watch-list. Filtering happens
    server-side so an admin's allow-list change takes effect on the very
    next upload, with no agent restart or redeploy needed.
    """
    from app.models.devices import DeviceAlertType, DeviceAllowedApp

    allowed_rows = (
        await db.execute(
            select(DeviceAllowedApp.domain_or_app).where(DeviceAllowedApp.device_id == device.id)
        )
    ).scalars().all()
    # Bug fix: this used to reduce every entry down to just its first DNS
    # label (`.split(".")[0]`) and compare labels. That both
    # over-suppresses (unrelated domains that happen to share a short first
    # label, e.g. an allow-list entry "chat.example.com" -> "chat" would
    # also match "chat.totally-different-site.com") and under-suppresses
    # (allow-listing "google.com" should cover "mail.google.com" too, but
    # "mail" != "google" as first labels, so it wouldn't be suppressed).
    # A proper "is this the domain, or a subdomain of it" check fixes both.
    allowed_domains = [a.lower().strip(".") for a in allowed_rows if a]

    def _is_allowed(matched_term: str) -> bool:
        candidate = matched_term.lower().strip(".")
        return any(candidate == allow or candidate.endswith("." + allow) for allow in allowed_domains)

    created = 0
    suppressed = 0
    for item in body.alerts:
        try:
            alert_type = DeviceAlertType(item.alert_type)
        except ValueError:
            continue  # ignore unknown alert types rather than failing the whole batch

        if _is_allowed(item.matched_term):
            suppressed += 1
            continue

        db.add(
            DeviceAlert(
                tenant_id=device.tenant_id,
                device_id=device.id,
                alert_type=alert_type,
                matched_term=item.matched_term[:200],
                detail=item.detail[:500],
                occurred_at=item.occurred_at,
            )
        )
        created += 1
    await db.flush()

    if created > 0:
        from app.services.device_alerts import notify_admins_of_device_alert
        await notify_admins_of_device_alert(db, device, created)

    return {"created": created, "suppressed_by_allowlist": suppressed}


@router.get("/{device_id}/alerts", summary="List a device's flagged-activity alerts")
async def list_device_alerts(
    device_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    acknowledged: bool | None = Query(None),
    current_user: User = Depends(require_permission("devices.view_alerts")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    device_row = (
        await db.execute(select(Device).where(Device.id == device_id, Device.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if not device_row:
        raise NotFoundError("Device not found")

    filters = [DeviceAlert.device_id == device_id, DeviceAlert.tenant_id == tenant_id]
    if acknowledged is not None:
        filters.append(DeviceAlert.is_acknowledged == acknowledged)

    rows = (
        await db.execute(
            select(DeviceAlert).where(*filters).order_by(DeviceAlert.occurred_at.desc()).limit(limit)
        )
    ).scalars().all()

    return {
        "items": [
            {
                "id": str(a.id),
                "alert_type": a.alert_type.value,
                "matched_term": a.matched_term,
                "detail": a.detail,
                "occurred_at": a.occurred_at.isoformat(),
                "is_acknowledged": a.is_acknowledged,
            }
            for a in rows
        ],
        "total": len(rows),
    }


@router.post("/{device_id}/alerts/{alert_id}/acknowledge", summary="Mark an alert as reviewed")
async def acknowledge_alert(
    device_id: UUID,
    alert_id: UUID,
    current_user: User = Depends(require_permission("devices.view_alerts")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    alert = (
        await db.execute(
            select(DeviceAlert).where(
                DeviceAlert.id == alert_id,
                DeviceAlert.device_id == device_id,
                DeviceAlert.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not alert:
        raise NotFoundError("Alert not found")
    alert.is_acknowledged = True
    await db.flush()
    return {"id": str(alert.id), "message": "Alert acknowledged"}


@router.get("/alerts/recent", summary="Org-wide recent alerts, for the dashboard notification feed")
async def list_recent_alerts(
    since_minutes: int = Query(60, ge=1, le=1440),
    current_user: User = Depends(require_permission("devices.view_alerts")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
    rows = (
        await db.execute(
            select(DeviceAlert)
            .where(DeviceAlert.tenant_id == tenant_id, DeviceAlert.occurred_at >= cutoff)
            .order_by(DeviceAlert.occurred_at.desc())
            .limit(100)
        )
    ).scalars().all()

    device_ids = {a.device_id for a in rows}
    devices_by_id = {}
    if device_ids:
        device_rows = (
            await db.execute(select(Device).where(Device.id.in_(device_ids)))
        ).scalars().all()
        devices_by_id = {d.id: d for d in device_rows}

    return {
        "items": [
            {
                "id": str(a.id),
                "device_id": str(a.device_id),
                "device_name": (devices_by_id.get(a.device_id).device_name if devices_by_id.get(a.device_id) else None)
                    or (devices_by_id.get(a.device_id).hostname if devices_by_id.get(a.device_id) else "Unknown device"),
                "alert_type": a.alert_type.value,
                "matched_term": a.matched_term,
                "detail": a.detail,
                "occurred_at": a.occurred_at.isoformat(),
                "is_acknowledged": a.is_acknowledged,
            }
            for a in rows
        ],
        "total": len(rows),
    }


# ── Per-Device Allow-List (overrides the global watch-list) ────────────────
class AllowedAppCreateRequest(BaseModel):
    domain_or_app: str
    reason: str | None = None


@router.get("/{device_id}/allowed-apps", summary="List this device's allow-list overrides")
async def list_allowed_apps(
    device_id: UUID,
    current_user: User = Depends(require_permission("devices.enroll")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.models.devices import DeviceAllowedApp

    device_row = (
        await db.execute(select(Device).where(Device.id == device_id, Device.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if not device_row:
        raise NotFoundError("Device not found")

    rows = (
        await db.execute(
            select(DeviceAllowedApp)
            .where(DeviceAllowedApp.device_id == device_id, DeviceAllowedApp.tenant_id == tenant_id)
            .order_by(DeviceAllowedApp.domain_or_app)
        )
    ).scalars().all()

    return {
        "items": [
            {
                "id": str(a.id),
                "domain_or_app": a.domain_or_app,
                "reason": a.reason,
                "allowed_by_id": str(a.allowed_by_id) if a.allowed_by_id else None,
                "created_at": a.created_at.isoformat(),
            }
            for a in rows
        ],
        "total": len(rows),
    }


@router.post(
    "/{device_id}/allowed-apps",
    status_code=status.HTTP_201_CREATED,
    summary="Allow an app/domain on this specific device (suppresses its alerts here only)",
)
async def add_allowed_app(
    device_id: UUID,
    body: AllowedAppCreateRequest,
    current_user: User = Depends(require_permission("devices.enroll")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.models.devices import DeviceAllowedApp

    device_row = (
        await db.execute(select(Device).where(Device.id == device_id, Device.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if not device_row:
        raise NotFoundError("Device not found")

    normalized = body.domain_or_app.strip().lower()
    if not normalized:
        raise NotFoundError("domain_or_app cannot be empty")

    existing = (
        await db.execute(
            select(DeviceAllowedApp).where(
                DeviceAllowedApp.device_id == device_id,
                DeviceAllowedApp.domain_or_app == normalized,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return {"id": str(existing.id), "domain_or_app": existing.domain_or_app, "message": "Already allowed"}

    entry = DeviceAllowedApp(
        tenant_id=tenant_id,
        device_id=device_id,
        domain_or_app=normalized,
        reason=body.reason,
        allowed_by_id=current_user.id,
    )
    db.add(entry)
    await db.flush()
    return {"id": str(entry.id), "domain_or_app": entry.domain_or_app}


@router.delete(
    "/{device_id}/allowed-apps/{allowed_app_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove an allow-list override (alerts for this app/domain resume on this device)",
)
async def remove_allowed_app(
    device_id: UUID,
    allowed_app_id: UUID,
    current_user: User = Depends(require_permission("devices.enroll")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    from app.models.devices import DeviceAllowedApp

    entry = (
        await db.execute(
            select(DeviceAllowedApp).where(
                DeviceAllowedApp.id == allowed_app_id,
                DeviceAllowedApp.device_id == device_id,
                DeviceAllowedApp.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not entry:
        raise NotFoundError("Allow-list entry not found")
    await db.delete(entry)
    await db.flush()


@router.post("/{device_id}/decommission", summary="Decommission and revoke a device")
async def decommission_device(
    device_id: UUID,
    current_user: User = Depends(require_permission("devices.decommission")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Permanently revokes the device's agent token (is_enrolled=False, so
    get_current_device rejects it on the next heartbeat), marks it
    decommissioned, unassigns it from any employee, and soft-deletes the
    row so it drops out of the active fleet list. Use this when a machine
    is retired or an employee offboards.
    """
    device = (
        await db.execute(select(Device).where(Device.id == device_id, Device.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if not device:
        raise NotFoundError("Device not found")

    device.is_enrolled = False
    device.status = DeviceStatus.DECOMMISSIONED
    device.assigned_employee_id = None
    device.soft_delete()
    await db.flush()
    return {"id": str(device.id), "message": "Device decommissioned"}