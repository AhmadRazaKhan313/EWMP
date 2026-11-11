"""Finance Phase 6 API: month / year close, opening balances, tax report."""
import datetime
import uuid
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.permissions.dependencies import get_tenant_id, require_permission
from app.services import finance_close as close
from app.services import finance_taxes as taxes

router = APIRouter()
_view = require_permission("finance.view")
_manage = require_permission("finance.manage")
MAX_MONEY = Decimal("999999999999.99")


class CloseBody(BaseModel):
    period_type: Literal["month", "year"]
    date: datetime.date
    note: str | None = Field(None, max_length=500)


class OpeningItem(BaseModel):
    account_id: uuid.UUID
    amount: Decimal = Field(ge=-MAX_MONEY, le=MAX_MONEY)


class OpeningBody(BaseModel):
    as_of: datetime.date
    items: list[OpeningItem] = Field(max_length=500)


@router.get("/close", summary="Books lock status and the list of closed periods")
async def close_status(user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return await close.status(db, tenant_id)


@router.get("/close/preview", summary="What closing a month or financial year would lock, with warnings")
async def close_preview(period_type: Literal["month", "year"], date: datetime.date, user: User = Depends(_view),
                        tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return await close.preview(db, tenant_id, period_type, date)


@router.post("/close", summary="Close a month or financial year: nothing can be posted on or before it")
async def close_period(body: CloseBody, user: User = Depends(_manage), tenant_id: uuid.UUID = Depends(get_tenant_id),
                       db: AsyncSession = Depends(get_db)) -> dict:
    return await close.close_period(db, tenant_id, body.period_type, body.date, note=body.note, created_by=user.id)


@router.post("/close/reopen", summary="Reopen the most recently closed period")
async def reopen(user: User = Depends(_manage), tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return await close.reopen_latest(db, tenant_id)


@router.get("/opening-balances", summary="The opening balances entered so far")
async def get_opening(user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return await close.get_opening(db, tenant_id)


@router.put("/opening-balances", summary="Set (replace) the opening balances; the difference goes to Opening Balance Equity")
async def put_opening(body: OpeningBody, user: User = Depends(_manage), tenant_id: uuid.UUID = Depends(get_tenant_id),
                      db: AsyncSession = Depends(get_db)) -> dict:
    return await close.set_opening(db, tenant_id, as_of=body.as_of, items=[(i.account_id, i.amount) for i in body.items], created_by=user.id)


@router.delete("/opening-balances", summary="Remove the opening balances (reverses the entry)")
async def delete_opening(user: User = Depends(_manage), tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return await close.clear_opening(db, tenant_id, created_by=user.id)


@router.get("/reports/taxes", summary="Output tax (invoices) against input tax (bills) by rate")
async def tax_report(date_from: datetime.date | None = None, date_to: datetime.date | None = None, user: User = Depends(_view),
                     tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    today = datetime.date.today()
    return await taxes.tax_report(db, tenant_id, date_from or datetime.date(today.year, today.month, 1), date_to or today)
