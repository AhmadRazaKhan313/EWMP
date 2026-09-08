"""
Employee document model.

Design intent: documents are WRITE-ONCE. There is deliberately no service
method or API route that edits a document's file or metadata after upload —
the only ways a document's lifecycle changes after creation are:
  - download (read-only)
  - delete (HR/admin only, via `employees.delete_documents`) — this removes
    the record entirely; it is not an edit. To "fix" a wrong document, HR
    deletes it and the employee/HR uploads a fresh one, which preserves an
    honest history instead of silently mutating what was on file.

`is_locked` is kept as an explicit, always-true-after-upload column (rather
than relying purely on "no PATCH route exists") so the intent is visible
directly in the data model and can be defended even if someone edits the
row through a raw DB console.
"""

import uuid
import enum
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import TenantModel


class DocumentType(str, enum.Enum):
    NATIONAL_ID = "national_id"          # CNIC / national ID card
    PASSPORT = "passport"
    VISA_WORK_PERMIT = "visa_work_permit"
    EMPLOYMENT_CONTRACT = "employment_contract"
    EDUCATIONAL_CERTIFICATE = "educational_certificate"
    PROFESSIONAL_CERTIFICATE = "professional_certificate"
    EXPERIENCE_LETTER = "experience_letter"
    RESUME_CV = "resume_cv"
    BANK_DOCUMENT = "bank_document"
    TAX_DOCUMENT = "tax_document"
    MEDICAL_RECORD = "medical_record"
    POLICE_CLEARANCE = "police_clearance"
    NDA_AGREEMENT = "nda_agreement"
    PHOTO = "photo"
    OTHER = "other"


class EmployeeDocument(TenantModel):
    __tablename__ = "employee_documents"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    document_type: Mapped[DocumentType] = mapped_column(
        SAEnum(DocumentType, name="employee_document_type_enum"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="User-facing label, e.g. 'CNIC — Front Side'"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── File metadata ────────────────────────────────────────────
    storage_key: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="Path/key in the storage backend"
    )
    original_file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    # ── Expiry tracking (for reminders — CNIC/passport/visa renewal) ──
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    # ── Immutability + audit ────────────────────────────────────────
    is_locked: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
        comment="Always true once a document is uploaded — documents are never edited in place",
    )
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Relationships ─────────────────────────────────────────────
    employee: Mapped["Employee"] = relationship(  # noqa: F821
        "Employee", foreign_keys=[employee_id], lazy="noload"
    )

    def __repr__(self) -> str:
        return f"<EmployeeDocument id={self.id} type={self.document_type} employee_id={self.employee_id}>"

    @property
    def is_expired(self) -> bool:
        if self.expiry_date is None:
            return False
        return self.expiry_date < date.today()

    @property
    def days_until_expiry(self) -> int | None:
        if self.expiry_date is None:
            return None
        return (self.expiry_date - date.today()).days
