"""
Employee document API schemas.

Deliberately NO update/edit schema — documents are write-once. Uploading
a file happens via multipart form fields (see the router), not JSON, so
there's no "DocumentCreateSchema" either; only the response shapes live here.
"""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.documents import DocumentType


class DocumentResponseSchema(BaseModel):
    id: UUID
    employee_id: UUID
    document_type: DocumentType
    title: str
    notes: str | None
    original_file_name: str
    mime_type: str
    file_size_bytes: int
    expiry_date: date | None
    is_expired: bool
    days_until_expiry: int | None
    is_locked: bool
    uploaded_by_id: UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    items: list[DocumentResponseSchema]
    total: int
