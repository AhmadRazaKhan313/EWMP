"""Employment-status timeline for an employee (E-08)."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import EmployeeStatusHistory
from app.models.user import User


def _value(status) -> str | None:
    return None if status is None else getattr(status, "value", str(status))


async def record_status_change(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
    *,
    from_status,
    to_status,
    changed_by_id: uuid.UUID | None,
    reason: str | None = None,
    effective_date: date | None = None,
    source: str = "update",
) -> EmployeeStatusHistory | None:
    """Add a timeline row. A change to the same status is not a change."""
    if _value(from_status) == _value(to_status):
        return None
    row = EmployeeStatusHistory(
        tenant_id=tenant_id, employee_id=employee_id,
        from_status=_value(from_status), to_status=_value(to_status),
        reason=(reason or "").strip() or None,
        effective_date=effective_date or date.today(),
        changed_by_id=changed_by_id, source=source,
    )
    db.add(row)
    await db.flush()
    return row


async def list_history(db: AsyncSession, tenant_id: uuid.UUID, employee_id: uuid.UUID) -> list[dict]:
    """Newest first, with the name of whoever made the change."""
    rows = (
        await db.execute(
            select(EmployeeStatusHistory, User.first_name, User.last_name)
            .join(User, User.id == EmployeeStatusHistory.changed_by_id, isouter=True)
            .where(
                EmployeeStatusHistory.tenant_id == tenant_id,
                EmployeeStatusHistory.employee_id == employee_id,
                EmployeeStatusHistory.is_deleted == False,  # noqa: E712
            )
            .order_by(EmployeeStatusHistory.effective_date.desc(), EmployeeStatusHistory.created_at.desc())
        )
    ).all()
    return [
        {
            "id": str(h.id),
            "from_status": h.from_status,
            "to_status": h.to_status,
            "reason": h.reason,
            "effective_date": h.effective_date.isoformat(),
            "source": h.source,
            "changed_by": " ".join(x for x in (first, last) if x) or None,
            "created_at": h.created_at.isoformat() if h.created_at else None,
        }
        for h, first, last in rows
    ]
