"""Finance Phase 1 API: simple Income / Expense / Transfer entries, summary, import, export."""
import datetime
import uuid
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import UnprocessableError
from app.models.user import User
from app.permissions.dependencies import get_tenant_id, require_permission
from app.services import finance_transactions as txn

router = APIRouter()
MAX_UPLOAD = 5 * 1024 * 1024


class TxnCreate(BaseModel):
    type: Literal["income", "expense", "transfer"]
    date: datetime.date
    amount: Decimal = Field(gt=0)
    account_id: uuid.UUID
    category_id: uuid.UUID | None = None
    to_account_id: uuid.UUID | None = None
    description: str | None = Field(None, max_length=500)
    reference: str | None = Field(None, max_length=100)
    currency: str | None = Field(None, min_length=3, max_length=3)
    rate: Decimal | None = Field(None, gt=0)
    payment_provider: str | None = Field(None, max_length=100)
    payment_account_no: str | None = Field(None, max_length=60)
    payment_tid: str | None = Field(None, max_length=100)


class ProviderBody(BaseModel):
    kind: Literal["bank", "wallet"]
    name: str = Field(min_length=1, max_length=100)


@router.post("/transactions", status_code=status.HTTP_201_CREATED, summary="Add an income, expense or transfer")
async def create_txn(body: TxnCreate, user: User = Depends(require_permission("finance.post")),
                     tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    e = await txn.create_transaction(
        db, tenant_id, type=body.type, entry_date=body.date, amount=body.amount, account_id=body.account_id,
        category_id=body.category_id, to_account_id=body.to_account_id, description=body.description,
        reference=body.reference, currency=body.currency, rate=body.rate, created_by=user.id,
        payment_provider=body.payment_provider, payment_account_no=body.payment_account_no, payment_tid=body.payment_tid)
    rows, _ = await txn.list_transactions(db, tenant_id, all_rows=True, search=None, date_from=e.entry_date, date_to=e.entry_date)
    return next(r for r in rows if r["id"] == str(e.id))


@router.get("/transactions", summary="List income / expense / transfer entries")
async def list_txns(type: Literal["income", "expense", "transfer"] | None = None,
                    date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                    category_id: uuid.UUID | None = None, account_id: uuid.UUID | None = None,
                    search: str | None = Query(None, max_length=100),
                    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500),
                    user: User = Depends(require_permission("finance.view")),
                    tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    items, total = await txn.list_transactions(db, tenant_id, type=type, date_from=date_from, date_to=date_to,
                                               category_id=category_id, account_id=account_id, search=search,
                                               page=page, page_size=page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/summary", summary="Totals, per-category breakdown and money-account balances")
async def get_summary(date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                      user: User = Depends(require_permission("finance.view")),
                      tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return await txn.summary(db, tenant_id, date_from, date_to)


@router.post("/transactions/import", summary="Import income or expenses from an Excel / CSV file")
async def import_txns(file: UploadFile = File(...), type: Literal["income", "expense"] = Form(...),
                      account_id: uuid.UUID = Form(...), dry_run: bool = Form(True),
                      create_missing_categories: bool = Form(True),
                      date_order: Literal["mdy", "dmy"] | None = Form(None),
                      user: User = Depends(require_permission("finance.post")),
                      tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    content = await file.read(MAX_UPLOAD + 1)
    if len(content) > MAX_UPLOAD:
        raise UnprocessableError("File is larger than 5 MB")
    res = await txn.import_rows(db, tenant_id, type=type, account_id=account_id, filename=file.filename or "",
                                content=content, dry_run=dry_run, create_missing=create_missing_categories,
                                date_order=date_order, created_by=user.id)
    return res.as_dict()


@router.get("/transactions/export", summary="Download income and expenses as an Excel file")
async def export_txns(date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                      user: User = Depends(require_permission("finance.export")),
                      tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> Response:
    data = await txn.export_workbook(db, tenant_id, date_from, date_to)
    return Response(content=data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="finance.xlsx"'})


@router.get("/providers", summary="Banks or mobile wallets to pick from (built-in list plus the ones you added)")
async def list_providers(kind: Literal["bank", "wallet"], user: User = Depends(require_permission("finance.view")),
                         tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return {"kind": kind, "items": await txn.providers(db, tenant_id, kind)}


@router.post("/providers", status_code=status.HTTP_201_CREATED, summary="Add a bank or wallet name to the list")
async def add_provider(body: ProviderBody, user: User = Depends(require_permission("finance.post")),
                       tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return {"kind": body.kind, "items": await txn.add_provider(db, tenant_id, body.kind, body.name)}
