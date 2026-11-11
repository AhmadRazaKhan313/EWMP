"""Finance Budget API: weekly / monthly / yearly plan against actuals."""
import datetime
import uuid
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.permissions.dependencies import get_tenant_id, require_permission
from app.services import finance_budget as bud

router = APIRouter(prefix="/budget")
_view = require_permission("finance.view")
_manage = require_permission("finance.manage")
Period = Literal["week", "month", "year"]


class PlanBody(BaseModel):
    period: Period
    date: datetime.date
    kind: Literal["income", "expense"]
    category: str
    planned: Decimal


class OpeningBody(BaseModel):
    period: Period
    date: datetime.date
    starting_balance: Decimal | None = None   # empty = use the ledger balance


@router.get("", summary="Budget for the week / month / financial year that contains a date")
async def get_budget(period: Period = "month", date: datetime.date | None = None, user: User = Depends(_view),
                     tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return await bud.get_budget(db, tenant_id, period, date or datetime.date.today())


@router.put("/plan", summary="Set the planned amount of one category")
async def put_plan(body: PlanBody, user: User = Depends(_manage), tenant_id: uuid.UUID = Depends(get_tenant_id),
                   db: AsyncSession = Depends(get_db)) -> dict:
    return await bud.set_plan(db, tenant_id, body.period, body.date, body.kind, body.category, body.planned)


@router.put("/opening", summary="Set (or clear) the starting balance of a period")
async def put_opening(body: OpeningBody, user: User = Depends(_manage), tenant_id: uuid.UUID = Depends(get_tenant_id),
                      db: AsyncSession = Depends(get_db)) -> dict:
    return await bud.set_opening(db, tenant_id, body.period, body.date, body.starting_balance)
