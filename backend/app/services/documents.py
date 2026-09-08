"""
Employee document service.

Only four operations exist on purpose: upload, list, download, delete.
There is no `update_document` — once a file is uploaded it is immutable.
If a wrong file was uploaded, an HR user with `employees.delete_documents`
deletes it and a fresh one is uploaded; the file itself is never replaced
in place.
"""

import uuid
from datetime import date

import filetype
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError, PermissionDeniedError
from app.core.storage import get_storage
from app.models.documents import DocumentType, EmployeeDocument
from app.repositories.documents import EmployeeDocumentRepository
from app.repositories.employee import EmployeeRepository

MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# Legacy MS Office files (.doc, .xls, .ppt) are all OLE2 Compound File
# containers sharing the same magic bytes — `filetype` can't tell them
# apart by content alone. We recognize the container and label it as the
# one legacy type already on our allowlist (.doc); this is a security
# check, not a strict format classifier, so that's an acceptable trade-off.
_OLE2_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")


def _sniff_mime_type(content: bytes) -> str | None:
    """Determine a file's REAL type from its actual bytes (magic-byte
    sniffing), never from a client-supplied header. Returns None if the
    content doesn't match any recognized binary signature — which is
    exactly what happens for HTML/SVG/script content masquerading as a
    document, since those are plain text with no distinctive magic bytes.
    Callers should treat None as "reject", not "assume harmless".
    """
    if content.startswith(_OLE2_MAGIC):
        return "application/msword"
    kind = filetype.guess(content)
    return kind.mime if kind is not None else None


class EmployeeDocumentService:
    def __init__(self, db: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.repo = EmployeeDocumentRepository(db, tenant_id)
        self.employee_repo = EmployeeRepository(db, tenant_id)

    async def _get_employee_or_raise(self, employee_id: uuid.UUID):
        employee = await self.employee_repo.get(employee_id)
        if employee is None:
            raise NotFoundError("Employee not found")
        return employee

    async def upload_document(
        self,
        *,
        employee_id: uuid.UUID,
        document_type: DocumentType,
        title: str,
        file_name: str,
        mime_type: str,  # noqa: ARG002 — client-declared, kept for signature compatibility but never trusted; see _sniff_mime_type below
        content: bytes,
        expiry_date: date | None,
        notes: str | None,
        uploaded_by_id: uuid.UUID,
    ) -> EmployeeDocument:
        await self._get_employee_or_raise(employee_id)

        if not content:
            raise BadRequestError("Uploaded file is empty")
        if len(content) > MAX_UPLOAD_BYTES:
            raise BadRequestError(
                f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit"
            )

        # Bug fix: this used to validate the CLIENT-SUPPLIED `mime_type`
        # (from the HTTP Content-Type header, which any script or browser
        # can set to whatever it likes) against the allowlist below — an
        # attacker could label an HTML/JS file "application/pdf" and sail
        # straight through. `mime_type` (the parameter) is now only used as
        # a hint for logging; the ACTUAL sniffed type from the file's own
        # bytes is what gets validated and stored.
        sniffed_mime_type = _sniff_mime_type(content)
        if sniffed_mime_type is None or sniffed_mime_type not in ALLOWED_MIME_TYPES:
            raise BadRequestError(
                "Unsupported file type. Allowed: PDF, JPG, PNG, WEBP, DOC, DOCX"
            )

        storage = get_storage()
        key = f"employees/{self.tenant_id}/{employee_id}/{uuid.uuid4().hex}_{file_name}"
        await storage.save(key, content)

        document = await self.repo.create(
            {
                "employee_id": employee_id,
                "document_type": document_type,
                "title": title,
                "notes": notes,
                "storage_key": key,
                "original_file_name": file_name,
                "mime_type": sniffed_mime_type,
                "file_size_bytes": len(content),
                "expiry_date": expiry_date,
                "is_locked": True,
                "uploaded_by_id": uploaded_by_id,
            }
        )
        return document

    async def list_documents(
        self,
        employee_id: uuid.UUID,
        *,
        document_type: DocumentType | None = None,
        expiring_within_days: int | None = None,
    ) -> tuple[list[EmployeeDocument], int]:
        await self._get_employee_or_raise(employee_id)
        return await self.repo.list_for_employee(
            employee_id,
            document_type=document_type,
            expiring_within_days=expiring_within_days,
        )

    async def get_document_for_download(
        self, employee_id: uuid.UUID, document_id: uuid.UUID
    ) -> tuple[EmployeeDocument, bytes]:
        document = await self.repo.get_or_raise(document_id)
        if document.employee_id != employee_id:
            raise NotFoundError("Document not found for this employee")
        storage = get_storage()
        content = await storage.read(document.storage_key)
        return document, content

    async def delete_document(
        self, employee_id: uuid.UUID, document_id: uuid.UUID
    ) -> None:
        """
        Hard-delete is intentional here (not the usual soft delete): once HR
        confirms a document was uploaded in error, the file is removed from
        storage too, so it can't linger and be downloaded via a stale link.
        """
        document = await self.repo.get_or_raise(document_id)
        if document.employee_id != employee_id:
            raise NotFoundError("Document not found for this employee")

        storage = get_storage()
        await storage.delete(document.storage_key)
        await self.repo.delete(document_id, hard=True)