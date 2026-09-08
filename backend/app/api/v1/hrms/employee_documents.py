"""
Employee Document API.

Access rules:
  - Any employee can upload, view, and download documents on their OWN
    employee record (self-service — e.g. attaching their own CNIC/degree).
  - Viewing/uploading another employee's documents requires the HR
    permission (`employees.view_documents` / `employees.upload_documents`).
  - Deleting a document ALWAYS requires `employees.delete_documents` —
    even the employee who uploaded it cannot delete their own. This is
    intentional: it's what makes "documents can't be edited" hold up in
    practice, not just in the UI. There is no PATCH/PUT route at all.
"""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import PermissionDeniedError
from app.models.documents import DocumentType
from app.models.user import User
from app.permissions.dependencies import get_current_user, get_tenant_id
from app.repositories.employee import EmployeeRepository
from app.schemas.documents import DocumentListResponse, DocumentResponseSchema
from app.services.documents import EmployeeDocumentService

router = APIRouter(prefix="/employees", tags=["Employee Documents"])


async def _is_own_employee_record(
    db: AsyncSession, tenant_id: UUID, user: User, employee_id: UUID
) -> bool:
    repo = EmployeeRepository(db, tenant_id)
    own = await repo.get_by_user_id(user.id)
    return own is not None and own.id == employee_id


async def _require_view_access(db, tenant_id, user, employee_id) -> None:
    if user.is_platform_admin:
        return
    if await _is_own_employee_record(db, tenant_id, user, employee_id):
        return
    if user.has_permission("employees.view_documents"):
        return
    raise PermissionDeniedError("You cannot view this employee's documents")


async def _require_upload_access(db, tenant_id, user, employee_id) -> None:
    if user.is_platform_admin:
        return
    if await _is_own_employee_record(db, tenant_id, user, employee_id):
        return
    if user.has_permission("employees.upload_documents"):
        return
    raise PermissionDeniedError("You cannot upload documents for this employee")


@router.post(
    "/{employee_id}/documents",
    response_model=DocumentResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Upload an employee document (write-once — cannot be edited afterwards)",
)
async def upload_document(
    employee_id: UUID,
    document_type: DocumentType = Form(...),
    title: str = Form(...),
    expiry_date: date | None = Form(None),
    notes: str | None = Form(None),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponseSchema:
    await _require_upload_access(db, tenant_id, current_user, employee_id)

    content = await file.read()
    service = EmployeeDocumentService(db, tenant_id)
    document = await service.upload_document(
        employee_id=employee_id,
        document_type=document_type,
        title=title,
        file_name=file.filename or "document",
        mime_type=file.content_type or "application/octet-stream",
        content=content,
        expiry_date=expiry_date,
        notes=notes,
        uploaded_by_id=current_user.id,
    )
    return DocumentResponseSchema.model_validate(document)


@router.get(
    "/{employee_id}/documents",
    response_model=DocumentListResponse,
    summary="List an employee's documents",
)
async def list_documents(
    employee_id: UUID,
    document_type: DocumentType | None = Query(None),
    expiring_within_days: int | None = Query(
        None, ge=1, le=365, description="Only return documents expiring within N days"
    ),
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    await _require_view_access(db, tenant_id, current_user, employee_id)

    service = EmployeeDocumentService(db, tenant_id)
    items, total = await service.list_documents(
        employee_id,
        document_type=document_type,
        expiring_within_days=expiring_within_days,
    )
    return DocumentListResponse(
        items=[DocumentResponseSchema.model_validate(d) for d in items],
        total=total,
    )


@router.get(
    "/{employee_id}/documents/{document_id}/download",
    summary="Download a document's file",
)
async def download_document(
    employee_id: UUID,
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _require_view_access(db, tenant_id, current_user, employee_id)

    service = EmployeeDocumentService(db, tenant_id)
    document, content = await service.get_document_for_download(employee_id, document_id)
    return Response(
        content=content,
        media_type=document.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{document.original_file_name}"'
        },
    )


@router.delete(
    "/{employee_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document (HR/admin only — not available to the uploading employee)",
)
async def delete_document(
    employee_id: UUID,
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    if not current_user.is_platform_admin and not current_user.has_permission(
        "employees.delete_documents"
    ):
        raise PermissionDeniedError("Only HR/admin can delete employee documents")

    service = EmployeeDocumentService(db, tenant_id)
    await service.delete_document(employee_id, document_id)
