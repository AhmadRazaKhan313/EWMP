"""
Workflow Engine, Audit Log, Notification, API Key models.

WorkflowDefinition — the drag-and-drop automation blueprint (stored as JSON graph)
WorkflowRun        — one execution instance of a workflow
WorkflowRunLog     — step-by-step execution log
AuditLog           — immutable record of every write action in the platform
Notification       — in-app notification per user
APIKey             — public REST API keys issued to org admins
Webhook            — outgoing webhook endpoints configured by an org
"""

import uuid
import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer,
    String, Text, JSON, Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import TenantModel, PlatformModel


class TriggerType(str, enum.Enum):
    # Time-based
    SCHEDULE = "schedule"
    # Event-based
    EMPLOYEE_CREATED = "employee_created"
    EMPLOYEE_UPDATED = "employee_updated"
    LEAVE_REQUESTED = "leave_requested"
    LEAVE_APPROVED = "leave_approved"
    LEAVE_REJECTED = "leave_rejected"
    PAYROLL_PROCESSED = "payroll_processed"
    DEVICE_OFFLINE = "device_offline"
    DEVICE_ALERT = "device_alert"
    TICKET_CREATED = "ticket_created"
    TICKET_RESOLVED = "ticket_resolved"
    FORM_SUBMITTED = "form_submitted"
    WEBHOOK_RECEIVED = "webhook_received"
    MANUAL = "manual"


class WorkflowRunStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    WAITING = "waiting"


class WorkflowDefinition(TenantModel):
    __tablename__ = "workflow_definitions"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_type: Mapped[TriggerType] = mapped_column(
        SAEnum(TriggerType, name="trigger_type_enum"), nullable=False, index=True
    )

    # The full DAG definition — nodes, edges, conditions
    graph: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}",
        comment="ReactFlow-compatible node/edge graph serialized to JSON",
    )
    # Trigger configuration (cron expression, event filters, etc.)
    trigger_config: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    # Global variables available to all nodes
    variables: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_draft: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    run_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_status: Mapped[WorkflowRunStatus | None] = mapped_column(
        SAEnum(WorkflowRunStatus, name="wf_run_status_enum"), nullable=True
    )

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    runs: Mapped[list["WorkflowRun"]] = relationship(
        "WorkflowRun", back_populates="definition"
    )

    def __repr__(self) -> str:
        return f"<WorkflowDefinition {self.name!r}>"


class WorkflowRun(TenantModel):
    __tablename__ = "workflow_runs"

    definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_definitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[WorkflowRunStatus] = mapped_column(
        SAEnum(WorkflowRunStatus, name="wf_run_status_enum"), nullable=False,
        default=WorkflowRunStatus.PENDING, index=True,
    )

    trigger_data: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    context: Mapped[dict] = mapped_column(
        JSON, default=dict, server_default="{}",
        comment="Runtime variables accumulated during execution",
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    definition: Mapped["WorkflowDefinition"] = relationship(
        "WorkflowDefinition", back_populates="runs"
    )
    logs: Mapped[list["WorkflowRunLog"]] = relationship(
        "WorkflowRunLog", back_populates="run"
    )


class WorkflowRunLog(TenantModel):
    __tablename__ = "workflow_run_logs"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_id: Mapped[str] = mapped_column(String(100), nullable=False)
    node_type: Mapped[str] = mapped_column(String(50), nullable=False)
    node_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    input_data: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    output_data: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped["WorkflowRun"] = relationship("WorkflowRun", back_populates="logs")


class AuditLog(TenantModel):
    __tablename__ = "audit_logs"

    # Who
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    user_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # What
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resource_label: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Change details
    before_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    changed_fields: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")

    # Context
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    severity: Mapped[str] = mapped_column(String(20), default="info", server_default="info")

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} on {self.resource_type}/{self.resource_id}>"


class Notification(TenantModel):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    action_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict, server_default="{}")

    is_read: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<Notification {self.type!r} user={self.user_id}>"


class APIKey(TenantModel):
    __tablename__ = "api_keys"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    key_prefix: Mapped[str] = mapped_column(
        String(12), nullable=False,
        comment="First 12 chars of raw key shown to user for identification",
    )
    key_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True,
        comment="SHA-256 hash of the full raw key",
    )

    created_by_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    allowed_ips: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Webhook(TenantModel):
    __tablename__ = "webhooks"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    secret: Mapped[str] = mapped_column(String(255), nullable=False)
    events: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    headers: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")

    def __repr__(self) -> str:
        return f"<Webhook {self.name!r} → {self.url!r}>"
