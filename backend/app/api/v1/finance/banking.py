"""Finance Phase 5 API: statement import, matching and reconciliation for cash / bank / wallet accounts."""
import datetime
import uuid
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import UnprocessableError
from app.models.user import User
from app.permissions.dependencies import get_tenant_id, require_permission
from app.services import finance_banking as bank

router = APIRouter(prefix="/banking")
MAX_UPLOAD = 5 * 1024 * 1024
_view = require_permission("finance.view")
_post = require_permission("finance.post")
_manage = require_permission("finance.manage")
MAX_MONEY = Decimal("999999999999.99")


class MatchBody(BaseModel):
    entry_line_id: uuid.UUID


class CreateEntryBody(BaseModel):
    type: Literal["income", "expense", "transfer"]
    category_id: uuid.UUID | None = None
    other_account_id: uuid.UUID | None = None
    description: str | None = Field(None, max_length=500)


class ReconcileBody(BaseModel):
    account_id: uuid.UUID
    statement_date: datetime.date
    statement_balance: Decimal = Field(ge=-MAX_MONEY, le=MAX_MONEY)
    beginning_balance: Decimal | None = Field(None, ge=-MAX_MONEY, le=MAX_MONEY)


def _money(v: Decimal | None, name: str) -> Decimal | None:
    if v is not None and (not v.is_finite() or abs(v) > MAX_MONEY):
        raise UnprocessableError(f"{name} is out of range")
    return v


@router.post("/statements/import", summary="Import a bank or wallet statement (Excel / CSV) and match it to the ledger")
async def import_statement(file: UploadFile = File(...), account_id: uuid.UUID = Form(...), dry_run: bool = Form(True),
                           opening_balance: Decimal | None = Form(None), closing_balance: Decimal | None = Form(None),
                           date_order: Literal["mdy", "dmy"] | None = Form(None), user: User = Depends(_post),
                           tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    content = await file.read(MAX_UPLOAD + 1)
    if len(content) > MAX_UPLOAD:
        raise UnprocessableError("File is larger than 5 MB")
    return await bank.import_statement(db, tenant_id, account_id=account_id, filename=file.filename or "", content=content, dry_run=dry_run,
                                       opening_balance=_money(opening_balance, "Opening balance"), closing_balance=_money(closing_balance, "Closing balance"),
                                       date_order=date_order, created_by=user.id)


@router.get("/statements", summary="Imported statements of an account")
async def statements(account_id: uuid.UUID, user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id),
                     db: AsyncSession = Depends(get_db)) -> dict:
    return {"items": await bank.list_statements(db, tenant_id, account_id)}


@router.get("/lines", summary="Statement lines of an account")
async def lines(account_id: uuid.UUID, status: Literal["unmatched", "matched", "ignored"] | None = None, statement_id: uuid.UUID | None = None,
                date_from: datetime.date | None = None, date_to: datetime.date | None = None, q: str | None = Query(None, max_length=100),
                limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0), user: User = Depends(_view),
                tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return await bank.list_lines(db, tenant_id, account_id, status=status, statement_id=statement_id, date_from=date_from, date_to=date_to,
                                 q=q, limit=limit, offset=offset)


@router.post("/accounts/{account_id}/auto-match", summary="Match every line that has one obvious ledger entry")
async def auto_match(account_id: uuid.UUID, user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
                     db: AsyncSession = Depends(get_db)) -> dict:
    await bank._money_account(db, tenant_id, account_id)
    return {"matched": await bank.auto_match(db, tenant_id, account_id, user.id)}


@router.get("/lines/{line_id}/suggestions", summary="Ledger entries that could match a statement line")
async def suggestions(line_id: uuid.UUID, user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id),
                      db: AsyncSession = Depends(get_db)) -> dict:
    return {"items": await bank.suggestions(db, tenant_id, line_id)}


@router.post("/lines/{line_id}/match", summary="Match a statement line to a ledger entry")
async def match(line_id: uuid.UUID, body: MatchBody, user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
                db: AsyncSession = Depends(get_db)) -> dict:
    return await bank.match_line(db, tenant_id, line_id, body.entry_line_id, user.id)


@router.post("/lines/{line_id}/unmatch", summary="Remove the match of a statement line")
async def unmatch(line_id: uuid.UUID, user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
                  db: AsyncSession = Depends(get_db)) -> dict:
    return await bank.unmatch_line(db, tenant_id, line_id)


@router.post("/lines/{line_id}/ignore", summary="Leave a statement line out (for example a duplicate)")
async def ignore(line_id: uuid.UUID, user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
                 db: AsyncSession = Depends(get_db)) -> dict:
    return await bank.set_ignored(db, tenant_id, line_id, True)


@router.post("/lines/{line_id}/restore", summary="Bring an ignored statement line back")
async def restore(line_id: uuid.UUID, user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
                  db: AsyncSession = Depends(get_db)) -> dict:
    return await bank.set_ignored(db, tenant_id, line_id, False)


@router.post("/lines/{line_id}/create-entry", status_code=status.HTTP_201_CREATED, summary="Book a statement line as income, expense or transfer and match it")
async def create_entry(line_id: uuid.UUID, body: CreateEntryBody, user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
                       db: AsyncSession = Depends(get_db)) -> dict:
    return await bank.create_entry_for_line(db, tenant_id, line_id, type=body.type, category_id=body.category_id,
                                            other_account_id=body.other_account_id, description=body.description, user_id=user.id)


@router.post("/reconciliations/preview", summary="Check a statement balance against the matched lines")
async def preview(body: ReconcileBody, user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id),
                  db: AsyncSession = Depends(get_db)) -> dict:
    return await bank.reconcile_preview(db, tenant_id, body.account_id, body.statement_date, body.statement_balance, body.beginning_balance)


@router.post("/reconciliations", status_code=status.HTTP_201_CREATED, summary="Finish a reconciliation (the difference must be 0)")
async def finish(body: ReconcileBody, user: User = Depends(_manage), tenant_id: uuid.UUID = Depends(get_tenant_id),
                 db: AsyncSession = Depends(get_db)) -> dict:
    return await bank.finish_reconciliation(db, tenant_id, body.account_id, body.statement_date, body.statement_balance, body.beginning_balance, user.id)


@router.get("/reconciliations", summary="Finished reconciliations of an account")
async def reconciliations(account_id: uuid.UUID, user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id),
                          db: AsyncSession = Depends(get_db)) -> dict:
    return {"items": await bank.list_reconciliations(db, tenant_id, account_id)}


@router.delete("/reconciliations/{reconciliation_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Undo the latest reconciliation of an account")
async def undo(reconciliation_id: uuid.UUID, user: User = Depends(_manage), tenant_id: uuid.UUID = Depends(get_tenant_id),
               db: AsyncSession = Depends(get_db)) -> None:
    await bank.undo_reconciliation(db, tenant_id, reconciliation_id)
