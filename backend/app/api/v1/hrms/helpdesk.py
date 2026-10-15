"""IT Helpdesk API endpoints."""
import uuid
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.models.helpdesk import SupportTicket, TicketStatus, TicketPriority
from app.models.user import User
from app.permissions.dependencies import get_current_user, get_tenant_id, require_permission
from app.repositories.employee import EmployeeRepository
from datetime import datetime, UTC

router = APIRouter(prefix="/helpdesk", tags=["Helpdesk"])


class TicketCreate(BaseModel):
    title: str
    description: str = ""
    category: str = "General"
    priority: str = "medium"
    device_id: uuid.UUID | None = None


class TicketUpdate(BaseModel):
    status: str | None = None
    assignee_id: uuid.UUID | None = None
    priority: str | None = None
    resolution_notes: str | None = None

TICKET_PREFIX = "TKT-"


async def _next_ticket_number(db, tenant_id) -> str:
    """Next per-organisation ticket number: highest existing numeric suffix
    in THIS organisation (soft-deleted tickets included, so a number is never
    handed out twice) + 1.

    Used to be count(*) + 1, which reused a number whenever a row was missing
    from the count, and — combined with a platform-wide unique constraint —
    made every organisation after the first collide with the first one's
    TKT-00001 (audit C-5). Concurrent requests can still compute the same
    number; the (tenant_id, ticket_number) constraint catches that and
    create_ticket retries.
    """
    numbers = (
        await db.execute(
            select(SupportTicket.ticket_number).where(
                SupportTicket.tenant_id == tenant_id,
                SupportTicket.ticket_number.like(f"{TICKET_PREFIX}%"),
            )
        )
    ).scalars().all()
    highest = 0
    for number in numbers:
        suffix = number[len(TICKET_PREFIX):]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return f"{TICKET_PREFIX}{str(highest + 1).zfill(5)}"

@router.get("/tickets")
async def list_tickets(
    ticket_status: str | None = Query(None, alias="status"),
    priority: str | None = Query(None),
    assignee_id: uuid.UUID | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    current_user: User = Depends(require_permission("helpdesk.view")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    filters = [SupportTicket.tenant_id == tenant_id, SupportTicket.is_deleted == False]
    if ticket_status:
        filters.append(SupportTicket.status == ticket_status)
    if priority:
        filters.append(SupportTicket.priority == priority)
    if assignee_id:
        filters.append(SupportTicket.assignee_id == assignee_id)
    offset = (page - 1) * page_size
    stmt = select(SupportTicket).where(*filters).order_by(SupportTicket.created_at.desc()).offset(offset).limit(page_size)
    count_stmt = select(func.count()).select_from(SupportTicket).where(*filters)
    items = (await db.execute(stmt)).scalars().all()
    total = (await db.execute(count_stmt)).scalar_one()
    return {
        "items": [{"id": str(t.id), "ticket_number": t.ticket_number,
                   "title": t.title, "description": t.description,
                   "category": t.category, "status": t.status.value,
                   "priority": t.priority.value,
                   "requester_id": str(t.requester_id) if t.requester_id else None,
                   "assignee_id": str(t.assignee_id) if t.assignee_id else None,
                   "resolved_at": t.resolved_at.isoformat() if t.resolved_at else None,
                   "created_at": t.created_at.isoformat()} for t in items],
        "total": total, "page": page, "page_size": page_size,
        "total_pages": max(1, -(-total // page_size)),
    }

@router.post("/tickets", status_code=status.HTTP_201_CREATED)
async def create_ticket(
    body: TicketCreate,
    current_user: User = Depends(require_permission("helpdesk.create")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Who raised it: the caller's own employee record (None for accounts
    # without one, e.g. a platform admin). Tickets used to be saved with no
    # requester at all, so nobody could tell whose problem it was.
    requester = await EmployeeRepository(db, tenant_id).get_by_user_id(current_user.id)

    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        ticket_number = await _next_ticket_number(db, tenant_id)
        ticket = SupportTicket(
            tenant_id=tenant_id, ticket_number=ticket_number,
            title=body.title, description=body.description or None,
            category=body.category, priority=body.priority,
            status=TicketStatus.OPEN, device_id=body.device_id,
            requester_id=requester.id if requester else None,
        )
        try:
            # SAVEPOINT: a lost race with a concurrent create only rolls back
            # this attempt, then we recompute the number and try again.
            async with db.begin_nested():
                db.add(ticket)
                await db.flush()
            break
        except IntegrityError:
            if attempt == max_attempts:
                raise ConflictError(
                    "Could not allocate a ticket number after several attempts — please retry"
                )
    return {"id": str(ticket.id), "ticket_number": ticket_number, "created": True}

@router.patch("/tickets/{ticket_id}")
async def update_ticket(
    ticket_id: uuid.UUID,
    body: TicketUpdate,
    current_user: User = Depends(require_permission("helpdesk.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(SupportTicket).where(SupportTicket.id == ticket_id, SupportTicket.tenant_id == tenant_id))
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise NotFoundError("Ticket not found")
    if body.status:
        ticket.status = body.status
        if body.status == "resolved":
            ticket.resolved_at = datetime.now(UTC)
    if body.assignee_id:
        ticket.assignee_id = body.assignee_id
    if body.priority:
        ticket.priority = body.priority
    if body.resolution_notes:
        ticket.resolution_notes = body.resolution_notes
    await db.flush()
    return {"id": str(ticket.id), "updated": True}

@router.delete("/tickets/{ticket_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ticket(
    ticket_id: uuid.UUID,
    current_user: User = Depends(require_permission("helpdesk.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(select(SupportTicket).where(SupportTicket.id == ticket_id, SupportTicket.tenant_id == tenant_id))
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise NotFoundError("Ticket not found")
    ticket.soft_delete()
    await db.flush()