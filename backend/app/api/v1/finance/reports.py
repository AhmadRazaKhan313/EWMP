"""Finance Phase 4 API: reports and their Excel / CSV export."""
import datetime
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import UnprocessableError
from app.models.user import User
from app.permissions.dependencies import get_tenant_id, require_permission
from app.services import finance_reports as rep

router = APIRouter(prefix="/reports")
_view = require_permission("finance.view")
_export = require_permission("finance.export")
ReportName = Literal["profit-loss", "balance-sheet", "trial-balance", "receivables-aging", "payables-aging", "general-ledger"]


def _year_start() -> datetime.date:
    return datetime.date(datetime.date.today().year, 1, 1)


@router.get("/profit-loss", summary="Profit and loss for a period (optionally against the period before)")
async def profit_loss(date_from: datetime.date | None = None, date_to: datetime.date | None = None, compare: bool = False,
                      user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return await rep.profit_loss(db, tenant_id, date_from or _year_start(), date_to or datetime.date.today(), compare)


@router.get("/balance-sheet", summary="Assets, liabilities and equity on a date")
async def balance_sheet(as_of: datetime.date | None = None, user: User = Depends(_view),
                        tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return await rep.balance_sheet(db, tenant_id, as_of or datetime.date.today())


@router.get("/receivables-aging", summary="Who owes you, by how overdue (today)")
async def receivables_aging(user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return await rep.receivables_aging(db, tenant_id)


@router.get("/payables-aging", summary="Whom you owe, by how overdue (today)")
async def payables_aging(user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return await rep.payables_aging(db, tenant_id)


@router.get("/general-ledger", summary="Every line posted to one account, with a running balance")
async def general_ledger(account_id: uuid.UUID, date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                         user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return await rep.general_ledger(db, tenant_id, account_id, date_from, date_to)


@router.get("/export", summary="Download a report as Excel or CSV")
async def export(report: ReportName, format: Literal["xlsx", "csv"] = "xlsx", date_from: datetime.date | None = None,
                 date_to: datetime.date | None = None, as_of: datetime.date | None = None, account_id: uuid.UUID | None = None,
                 compare: bool = False, user: User = Depends(_export), tenant_id: uuid.UUID = Depends(get_tenant_id),
                 db: AsyncSession = Depends(get_db)) -> Response:
    today = datetime.date.today()
    if report == "profit-loss":
        d = await rep.profit_loss(db, tenant_id, date_from or _year_start(), date_to or today, compare)
    elif report == "balance-sheet":
        d = await rep.balance_sheet(db, tenant_id, as_of or today)
    elif report == "trial-balance":
        d = await rep.trial_balance(db, tenant_id, as_of)
    elif report == "receivables-aging":
        d = await rep.receivables_aging(db, tenant_id)
    elif report == "payables-aging":
        d = await rep.payables_aging(db, tenant_id)
    else:
        if account_id is None:
            raise UnprocessableError("Pick an account for the general ledger")
        d = await rep.general_ledger(db, tenant_id, account_id, date_from, date_to)
    content, media, name = rep.render(report, d, format)
    return Response(content=content, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{name}"', "X-Content-Type-Options": "nosniff"})
