"""
In-app notifications: one place that creates them, and honours each person's
on/off choices (Settings -> Notifications).

Rules:
  * A notification is written only if the recipient has not switched that
    category off. Everything is ON until a person turns it off.
  * Sending must NEVER break the action that caused it (approving leave,
    locking payroll ...). Every send runs in its own savepoint and any failure
    is logged and swallowed.
  * Recipients are always people of the same organisation.

Categories (the `type` column of the notification, and the key in
User.preferences["notifications"]):
  leave, payroll, helpdesk, attendance, device_alert
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee
from app.models.organization import Organization
from app.models.rbac import Permission, Role, role_permissions
from app.models.user import User, user_roles
from app.models.workflows import Notification

logger = logging.getLogger("ewmp.notify")

# key -> (label, description) shown on the Settings page
CATEGORIES: dict[str, tuple[str, str]] = {
    "leave": ("Leave", "New leave requests to approve, and decisions on your own requests."),
    "payroll": ("Payroll", "Your payslip is ready and your salary has been paid."),
    "helpdesk": ("Helpdesk", "New tickets, assignments and updates on tickets you raised."),
    "attendance": ("Attendance", "Automatic check-outs and decisions on attendance corrections."),
    "device_alert": ("Device alerts", "Flagged activity on employee devices."),
}


def preference_map(user: User) -> dict[str, bool]:
    """Every category with its current on/off value (default on)."""
    saved = (user.preferences or {}).get("notifications") or {}
    return {key: saved.get(key, True) is not False for key in CATEGORIES}


def is_enabled(user: User, category: str) -> bool:
    return preference_map(user).get(category, True)


def set_preferences(user: User, updates: dict[str, bool]) -> dict[str, bool]:
    """Apply on/off changes. Unknown categories are ignored. The JSON column is
    re-assigned (not mutated) so SQLAlchemy notices the change."""
    unknown = set(updates) - set(CATEGORIES)
    if unknown:
        raise ValueError(f"Unknown notification category: {sorted(unknown)[0]}")
    current = dict((user.preferences or {}).get("notifications") or {})
    current.update({k: bool(v) for k, v in updates.items()})
    user.preferences = {**(user.preferences or {}), "notifications": current}
    return preference_map(user)


async def user_ids_with_permission(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    codename: str,
    *,
    exclude: Iterable[uuid.UUID | None] = (),
) -> list[uuid.UUID]:
    """Active people of the organisation who hold `codename`: through a role
    that has it, through a super role, or as the organisation owner."""
    owner_id = (
        await db.execute(select(Organization.owner_id).where(Organization.id == tenant_id))
    ).scalar_one_or_none()

    via_role = (
        select(user_roles.c.user_id)
        .join(Role, Role.id == user_roles.c.role_id)
        .outerjoin(role_permissions, role_permissions.c.role_id == Role.id)
        .outerjoin(Permission, Permission.id == role_permissions.c.permission_id)
        .where(or_(Role.is_super.is_(True), Permission.codename == codename))
    )
    conditions = [User.id.in_(via_role)]
    if owner_id is not None:
        conditions.append(User.id == owner_id)

    rows = (
        await db.execute(
            select(User.id).where(
                User.organization_id == tenant_id,
                User.is_deleted == False,  # noqa: E712
                User.is_active == True,  # noqa: E712
                or_(*conditions),
            )
        )
    ).scalars().all()
    skip = {e for e in exclude if e is not None}
    return [uid for uid in rows if uid not in skip]


async def user_id_for_employee(
    db: AsyncSession, tenant_id: uuid.UUID, employee_id: uuid.UUID | None
) -> uuid.UUID | None:
    if employee_id is None:
        return None
    return (
        await db.execute(
            select(Employee.user_id).where(Employee.id == employee_id, Employee.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()


async def user_ids_for_employees(
    db: AsyncSession, tenant_id: uuid.UUID, employee_ids: Iterable[uuid.UUID]
) -> list[uuid.UUID]:
    ids = list({e for e in employee_ids if e is not None})
    if not ids:
        return []
    return list(
        (
            await db.execute(
                select(Employee.user_id).where(Employee.id.in_(ids), Employee.tenant_id == tenant_id)
            )
        ).scalars().all()
    )


async def employee_name(db: AsyncSession, tenant_id: uuid.UUID, employee_id: uuid.UUID | None) -> str:
    if employee_id is None:
        return "An employee"
    row = (
        await db.execute(
            select(User.first_name, User.last_name, User.display_name)
            .join(Employee, Employee.user_id == User.id)
            .where(Employee.id == employee_id, Employee.tenant_id == tenant_id)
        )
    ).first()
    if row is None:
        return "An employee"
    first, last, display = row
    return (display or f"{first or ''} {last or ''}".strip()) or "An employee"


async def notify(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_ids: Iterable[uuid.UUID | None],
    *,
    category: str,
    title: str,
    body: str | None = None,
    action_url: str | None = None,
    icon: str | None = None,
    metadata: dict | None = None,
) -> int:
    """Create one notification per recipient who has this category switched on.
    Returns how many were created. Never raises."""
    if category not in CATEGORIES:
        logger.error("notify: unknown category %r", category)
        return 0
    ids = {u for u in user_ids if u is not None}
    if not ids:
        return 0
    try:
        async with db.begin_nested():
            users = (
                await db.execute(
                    select(User).where(
                        User.id.in_(ids), User.organization_id == tenant_id,
                        User.is_deleted == False, User.is_active == True,  # noqa: E712
                    )
                )
            ).scalars().all()
            created = 0
            for user in users:
                if not is_enabled(user, category):
                    continue
                db.add(
                    Notification(
                        tenant_id=tenant_id, user_id=user.id, title=title[:255], body=body,
                        type=category, icon=icon, action_url=action_url,
                        metadata_=metadata or {},
                    )
                )
                created += 1
            await db.flush()
            return created
    except Exception:  # noqa: BLE001 - a notification must never break the real action
        logger.exception("notify failed (category=%s); the action itself is unaffected", category)
        return 0
