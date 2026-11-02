"""Employee contracts and renewal reminders (E-07).

Rules
- An employee has at most ONE active contract (DB partial unique index enforces it).
- "Renew" closes the active contract (status=renewed) and opens the next one,
  linked through renewed_from_id, so the history stays intact.
- State shown to people is derived from dates, never stored:
  active / expiring / expired / renewed / terminated.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import Date, func, literal, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.documents import EmployeeDocument
from app.models.employee import (
    CONTRACT_TYPES,
    Employee,
    EmployeeContract,
)
from app.models.user import User

REPEAT_ALERT_EVERY_DAYS = 7
ALERT_GRACE_AFTER_EXPIRY_DAYS = 30


def derive_state(c: EmployeeContract, today: date | None = None) -> str:
    today = today or date.today()
    if c.status != "active":
        return c.status
    if c.end_date is None:
        return "active"
    if c.end_date < today:
        return "expired"
    if (c.end_date - today).days <= (c.renewal_alert_days or 0):
        return "expiring"
    return "active"


def _validate_dates(contract_type: str, start: date, end: date | None) -> date | None:
    if contract_type not in CONTRACT_TYPES:
        raise ValidationError(f"contract_type must be one of: {', '.join(CONTRACT_TYPES)}")
    if contract_type == "permanent":
        return None  # a permanent contract has no end date
    if end is None:
        raise ValidationError("End date is required for a non-permanent contract.")
    if end <= start:
        raise ValidationError("End date must be after the start date.")
    return end


def _row(c: EmployeeContract, today: date, code: str | None = None, name: str | None = None) -> dict:
    return {
        "id": str(c.id),
        "employee_id": str(c.employee_id),
        "employee_code": code,
        "employee_name": name,
        "contract_type": c.contract_type,
        "start_date": c.start_date.isoformat(),
        "end_date": c.end_date.isoformat() if c.end_date else None,
        "status": c.status,
        "state": derive_state(c, today),
        "days_left": (c.end_date - today).days if c.end_date and c.status == "active" else None,
        "renewal_alert_days": c.renewal_alert_days,
        "document_id": str(c.document_id) if c.document_id else None,
        "notes": c.notes,
        "renewed_from_id": str(c.renewed_from_id) if c.renewed_from_id else None,
    }


class EmployeeContractService:
    def __init__(self, db: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id

    async def _employee(self, employee_id: uuid.UUID) -> Employee:
        emp = (
            await self.db.execute(
                select(Employee).where(
                    Employee.id == employee_id,
                    Employee.tenant_id == self.tenant_id,
                    Employee.is_deleted == False,  # noqa: E712
                )
            )
        ).scalar_one_or_none()
        if emp is None:
            raise NotFoundError("Employee not found")
        return emp

    async def _contract(self, contract_id: uuid.UUID) -> EmployeeContract:
        c = (
            await self.db.execute(
                select(EmployeeContract).where(
                    EmployeeContract.id == contract_id,
                    EmployeeContract.tenant_id == self.tenant_id,
                    EmployeeContract.is_deleted == False,  # noqa: E712
                )
            )
        ).scalar_one_or_none()
        if c is None:
            raise NotFoundError("Contract not found")
        return c

    async def _check_document(self, employee_id: uuid.UUID, document_id: uuid.UUID | None) -> None:
        """The linked document must be THIS employee's, in THIS organization."""
        if document_id is None:
            return
        found = (
            await self.db.execute(
                select(EmployeeDocument.id).where(
                    EmployeeDocument.id == document_id,
                    EmployeeDocument.tenant_id == self.tenant_id,
                    EmployeeDocument.employee_id == employee_id,
                    EmployeeDocument.is_deleted == False,  # noqa: E712
                )
            )
        ).scalar_one_or_none()
        if found is None:
            raise ValidationError("That document does not belong to this employee.")

    async def _active_for(self, employee_id: uuid.UUID) -> EmployeeContract | None:
        return (
            await self.db.execute(
                select(EmployeeContract).where(
                    EmployeeContract.tenant_id == self.tenant_id,
                    EmployeeContract.employee_id == employee_id,
                    EmployeeContract.status == "active",
                    EmployeeContract.is_deleted == False,  # noqa: E712
                )
            )
        ).scalar_one_or_none()

    # ── reads ────────────────────────────────────────────────────────────
    async def list(
        self,
        *,
        employee_id: uuid.UUID | None = None,
        state: str | None = None,
        expiring_within_days: int | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> dict:
        today = date.today()
        # last day still inside each contract's own alert window
        window_end = literal(today, Date) + func.make_interval(0, 0, 0, EmployeeContract.renewal_alert_days)
        cond = [
            EmployeeContract.tenant_id == self.tenant_id,
            EmployeeContract.is_deleted == False,  # noqa: E712
        ]
        if employee_id:
            cond.append(EmployeeContract.employee_id == employee_id)
        if state in ("renewed", "terminated"):
            cond.append(EmployeeContract.status == state)
        elif state in ("active", "expiring", "expired"):
            cond.append(EmployeeContract.status == "active")
            if state == "expired":
                cond.append(EmployeeContract.end_date < today)
            elif state == "expiring":
                cond += [EmployeeContract.end_date >= today, EmployeeContract.end_date <= window_end]
            else:  # healthy active
                cond.append(
                    (EmployeeContract.end_date.is_(None))
                    | (EmployeeContract.end_date > window_end)
                )
        elif state:
            raise ValidationError("state must be active, expiring, expired, renewed or terminated")
        if expiring_within_days is not None:
            cond += [
                EmployeeContract.status == "active",
                EmployeeContract.end_date.is_not(None),
                EmployeeContract.end_date <= today + timedelta(days=expiring_within_days),
            ]

        total = (await self.db.execute(select(func.count()).select_from(EmployeeContract).where(*cond))).scalar_one()
        rows = (
            await self.db.execute(
                select(EmployeeContract, Employee.employee_code, User.first_name, User.last_name)
                .join(Employee, Employee.id == EmployeeContract.employee_id)
                .join(User, User.id == Employee.user_id, isouter=True)
                .where(*cond)
                .order_by(EmployeeContract.end_date.asc().nulls_last(), EmployeeContract.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        items = [
            _row(c, today, code, " ".join(x for x in (f, l) if x) or code)
            for c, code, f, l in rows
        ]
        return {
            "items": items, "total": total, "page": page, "page_size": page_size,
            "total_pages": max(1, -(-total // page_size)),
        }

    # ── writes ───────────────────────────────────────────────────────────
    async def create(self, employee_id: uuid.UUID, data: dict) -> dict:
        await self._employee(employee_id)
        end = _validate_dates(data["contract_type"], data["start_date"], data.get("end_date"))
        await self._check_document(employee_id, data.get("document_id"))
        if await self._active_for(employee_id):
            raise ConflictError(
                "This employee already has an active contract. Renew or terminate it first."
            )
        c = EmployeeContract(
            tenant_id=self.tenant_id, employee_id=employee_id,
            contract_type=data["contract_type"], start_date=data["start_date"], end_date=end,
            renewal_alert_days=data.get("renewal_alert_days", 30),
            document_id=data.get("document_id"), notes=data.get("notes"), status="active",
        )
        try:
            async with self.db.begin_nested():
                self.db.add(c)
                await self.db.flush()
        except IntegrityError:
            raise ConflictError("This employee already has an active contract.")
        return _row(c, date.today())

    async def update(self, contract_id: uuid.UUID, data: dict) -> dict:
        c = await self._contract(contract_id)
        if c.status != "active":
            raise ConflictError("Only an active contract can be edited.")
        ctype = data.get("contract_type", c.contract_type)
        start = data.get("start_date", c.start_date)
        end = data["end_date"] if "end_date" in data else c.end_date
        end = _validate_dates(ctype, start, end)
        if "document_id" in data:
            await self._check_document(c.employee_id, data["document_id"])
            c.document_id = data["document_id"]
        c.contract_type, c.start_date, c.end_date = ctype, start, end
        if "renewal_alert_days" in data and data["renewal_alert_days"] is not None:
            c.renewal_alert_days = data["renewal_alert_days"]
        if "notes" in data:
            c.notes = data["notes"]
        # Moving the end date changes what an earlier reminder was about.
        c.last_alerted_at = None
        await self.db.flush()
        return _row(c, date.today())

    async def renew(self, contract_id: uuid.UUID, data: dict) -> dict:
        old = await self._contract(contract_id)
        if old.status != "active":
            raise ConflictError("Only an active contract can be renewed.")
        ctype = data.get("contract_type") or old.contract_type
        start = data.get("start_date") or (
            old.end_date + timedelta(days=1) if old.end_date else date.today()
        )
        end = _validate_dates(ctype, start, data.get("end_date"))
        await self._check_document(old.employee_id, data.get("document_id"))
        old.status = "renewed"
        await self.db.flush()  # free the one-active slot before inserting the next
        new = EmployeeContract(
            tenant_id=self.tenant_id, employee_id=old.employee_id, contract_type=ctype,
            start_date=start, end_date=end, status="active",
            renewal_alert_days=data.get("renewal_alert_days") or old.renewal_alert_days,
            document_id=data.get("document_id"), notes=data.get("notes"), renewed_from_id=old.id,
        )
        self.db.add(new)
        await self.db.flush()
        return _row(new, date.today())

    async def terminate(self, contract_id: uuid.UUID, reason: str | None = None) -> dict:
        c = await self._contract(contract_id)
        if c.status != "active":
            raise ConflictError("Only an active contract can be terminated.")
        c.status = "terminated"
        today = date.today()
        if c.end_date is None or c.end_date > today:
            c.end_date = max(today, c.start_date + timedelta(days=0))
        if reason and reason.strip():
            c.notes = f"{c.notes}\nTerminated: {reason.strip()}" if c.notes else f"Terminated: {reason.strip()}"
        await self.db.flush()
        return _row(c, today)

    async def end_active_for_employee(self, employee_id: uuid.UUID) -> None:
        """Called when the employee leaves: their active contract ends with them."""
        c = await self._active_for(employee_id)
        if c is None:
            return
        c.status = "terminated"
        today = date.today()
        if c.end_date is None or c.end_date > today:
            c.end_date = max(today, c.start_date)
        await self.db.flush()

    async def delete(self, contract_id: uuid.UUID) -> None:
        c = await self._contract(contract_id)
        c.soft_delete()
        await self.db.flush()


# ── reminders ───────────────────────────────────────────────────────────────
async def _recipient_ids(db: AsyncSession, tenant_id: uuid.UUID) -> list[uuid.UUID]:
    """Org owner plus anyone who can update employees (HR)."""
    from sqlalchemy.orm import selectinload

    from app.models.organization import Organization
    from app.models.rbac import Role

    org = (await db.execute(select(Organization).where(Organization.id == tenant_id))).scalar_one_or_none()
    if org is None:
        return []
    users = (
        await db.execute(
            select(User)
            .where(User.organization_id == tenant_id, User.is_deleted == False, User.is_active == True)  # noqa: E712
            .options(selectinload(User.roles).selectinload(Role.permissions))
        )
    ).scalars().all()
    return [u.id for u in users if org.owner_id == u.id or u.has_permission("employees.update")]


async def notify_expiring_contracts(db: AsyncSession, today: date | None = None) -> dict:
    """Notify HR about contracts that are inside their alert window (or just
    expired and still not renewed). Each contract is reminded at most once
    every REPEAT_ALERT_EVERY_DAYS days, so the daily job never spams."""
    from app.models.workflows import Notification

    today = today or date.today()
    due = (
        await db.execute(
            select(EmployeeContract, Employee.employee_code, User.first_name, User.last_name)
            .join(Employee, Employee.id == EmployeeContract.employee_id)
            .join(User, User.id == Employee.user_id, isouter=True)
            .where(
                EmployeeContract.status == "active",
                EmployeeContract.is_deleted == False,  # noqa: E712
                Employee.is_deleted == False,  # noqa: E712
                EmployeeContract.end_date.is_not(None),
                EmployeeContract.end_date >= today - timedelta(days=ALERT_GRACE_AFTER_EXPIRY_DAYS),
            )
        )
    ).all()

    recipients: dict[uuid.UUID, list[uuid.UUID]] = {}
    sent = contracts = 0
    for c, code, first, last in due:
        if (c.end_date - today).days > (c.renewal_alert_days or 0):
            continue
        if c.last_alerted_at and (today - c.last_alerted_at).days < REPEAT_ALERT_EVERY_DAYS:
            continue
        if c.tenant_id not in recipients:
            recipients[c.tenant_id] = await _recipient_ids(db, c.tenant_id)
        who = " ".join(x for x in (first, last) if x) or code
        left = (c.end_date - today).days
        if left < 0:
            title, body = "Contract expired", f"{who}'s contract ended on {c.end_date.isoformat()} and was not renewed."
        elif left == 0:
            title, body = "Contract ends today", f"{who}'s contract ends today."
        else:
            title, body = "Contract expiring soon", f"{who}'s contract ends in {left} day(s), on {c.end_date.isoformat()}."
        for uid in recipients[c.tenant_id]:
            db.add(Notification(
                tenant_id=c.tenant_id, user_id=uid, title=title, body=body,
                type="contract_expiry", icon="file-clock",
                action_url=f"/employees/{c.employee_id}?tab=contract",
                metadata_={"contract_id": str(c.id), "employee_id": str(c.employee_id)},
            ))
            sent += 1
        c.last_alerted_at = today
        contracts += 1
    await db.flush()
    return {"contracts": contracts, "notifications": sent}
