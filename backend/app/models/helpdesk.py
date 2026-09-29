"""Helpdesk / IT Support Ticket model."""
import uuid, enum
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import TenantModel

class TicketStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    PENDING = "pending"
    RESOLVED = "resolved"
    CLOSED = "closed"

class TicketPriority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class SupportTicket(TenantModel):
    __tablename__ = "support_tickets"
    # Ticket numbers are generated per organisation (TKT-00001, ...), so they
    # must be unique per organisation, not platform-wide (audit C-5; migration
    # c4e95883fb29). Soft-deleted tickets still count: a number is never reused.
    __table_args__ = (
        UniqueConstraint("tenant_id", "ticket_number", name="uq_support_tickets_tenant_ticket_number"),
    )
    ticket_number: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(100), default="General")
    status: Mapped[TicketStatus] = mapped_column(SAEnum(TicketStatus, name="ticket_status_enum"), default=TicketStatus.OPEN, index=True)
    priority: Mapped[TicketPriority] = mapped_column(SAEnum(TicketPriority, name="ticket_priority_enum"), default=TicketPriority.MEDIUM, index=True)
    requester_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)