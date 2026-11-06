"""Finance API (Phase 0): chart of accounts, journal, trial balance, rates, tax rates."""
import datetime
from typing import Literal
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.models.finance import AccountType, FinAccount, FinExchangeRate, FinJournalEntry, FinTaxRate
from app.models.user import User
from app.permissions.dependencies import get_tenant_id, require_permission
from app.services import finance_ledger as ledger

router = APIRouter(prefix="/finance", tags=["Finance"])
from app.api.v1.finance.transactions import router as _txn_router  # noqa: E402
router.include_router(_txn_router)
from app.api.v1.finance.sales import router as _sales_router  # noqa: E402
router.include_router(_sales_router)
from app.api.v1.finance.purchases import router as _purchases_router  # noqa: E402
router.include_router(_purchases_router)
from app.api.v1.finance.reports import router as _reports_router  # noqa: E402
router.include_router(_reports_router)


# ── schemas ──────────────────────────────────────────────────────
class AccountCreate(BaseModel):
    code: str | None = Field(None, min_length=1, max_length=20)  # omitted = next free code
    name: str = Field(min_length=1, max_length=150)
    type: AccountType
    parent_id: uuid.UUID | None = None
    currency: str | None = Field(None, min_length=3, max_length=3)
    description: str | None = None
    money_kind: Literal["cash", "bank", "wallet"] | None = None  # only for asset (money) accounts


class AccountUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=150)
    parent_id: uuid.UUID | None = None
    is_active: bool | None = None
    money_kind: Literal["cash", "bank", "wallet"] | None = None
    description: str | None = None


class LineBody(BaseModel):
    account_id: uuid.UUID
    side: str = Field(pattern="^(debit|credit)$")
    amount: Decimal = Field(gt=0)
    currency: str | None = Field(None, min_length=3, max_length=3)
    rate: Decimal | None = Field(None, gt=0)
    description: str | None = Field(None, max_length=255)


class EntryCreate(BaseModel):
    entry_date: datetime.date
    memo: str | None = None
    reference: str | None = Field(None, max_length=100)
    lines: list[LineBody] = Field(min_length=2)


class VoidBody(BaseModel):
    reason: str | None = None
    on: datetime.date | None = None


class RateBody(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    on_date: datetime.date
    rate: Decimal = Field(gt=0)


class TaxBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    percent: Decimal = Field(ge=0, le=100)
    kind: str = Field("sales", max_length=30)
    account_id: uuid.UUID | None = None
    is_active: bool = True


def _acc(a: FinAccount) -> dict:
    return {"id": str(a.id), "code": a.code, "name": a.name, "type": a.type.value,
            "parent_id": str(a.parent_id) if a.parent_id else None, "is_system": a.is_system,
            "is_active": a.is_active, "currency": a.currency, "description": a.description,
            "money_kind": ledger.account_kind(a)}


def _entry(e: FinJournalEntry, lines=None) -> dict:
    d = {"id": str(e.id), "number": e.number, "entry_date": e.entry_date.isoformat(), "memo": e.memo,
         "reference": e.reference, "status": e.status.value, "base_currency": e.base_currency,
         "reverses_id": str(e.reverses_id) if e.reverses_id else None,
         "reversed_by_id": str(e.reversed_by_id) if e.reversed_by_id else None}
    if lines is not None:
        d["lines"] = [{"id": str(l.id), "account_id": str(l.account_id), "debit": str(l.debit), "credit": str(l.credit),
                       "currency": l.currency, "amount_original": str(l.amount_original),
                       "exchange_rate": str(l.exchange_rate), "description": l.description} for l in lines]
    return d


async def _get_account(db, tenant_id, account_id) -> FinAccount:
    a = (await db.execute(select(FinAccount).where(
        FinAccount.id == account_id, FinAccount.tenant_id == tenant_id, FinAccount.is_deleted == False))  # noqa: E712
    ).scalar_one_or_none()
    if a is None:
        raise NotFoundError("Account not found")
    return a


# ── setup & chart of accounts ────────────────────────────────────
@router.post("/setup", summary="Create the default chart of accounts (idempotent)")
async def setup(user: User = Depends(require_permission("finance.manage")),
                tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    created = await ledger.ensure_chart(db, tenant_id)
    return {"created": created, "base_currency": await ledger.base_currency(db, tenant_id)}


@router.get("/accounts", summary="Chart of accounts")
async def list_accounts(type: AccountType | None = None, include_inactive: bool = False,
                        user: User = Depends(require_permission("finance.view")),
                        tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    f = [FinAccount.tenant_id == tenant_id, FinAccount.is_deleted == False]  # noqa: E712
    if type:
        f.append(FinAccount.type == type)
    if not include_inactive:
        f.append(FinAccount.is_active == True)  # noqa: E712
    items = (await db.execute(select(FinAccount).where(*f).order_by(FinAccount.code))).scalars().all()
    return {"items": [_acc(a) for a in items], "total": len(items)}


@router.post("/accounts", status_code=status.HTTP_201_CREATED, summary="Add an account")
async def create_account(body: AccountCreate, user: User = Depends(require_permission("finance.manage")),
                         tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    code, parent_id = body.code, body.parent_id
    if code is None:
        code = await ledger.next_code(db, tenant_id, body.type)
        if parent_id is None:
            root = await ledger.root_account(db, tenant_id, body.type)
            parent_id = root.id if root else None
    dup = (await db.execute(select(FinAccount.id).where(
        FinAccount.tenant_id == tenant_id, FinAccount.code == code))).first()
    if dup:
        raise ConflictError(f"Account code {code} already exists")
    if parent_id:
        parent = await _get_account(db, tenant_id, parent_id)
        if parent.type != body.type:
            raise ConflictError("Parent account must be of the same type")
    a = FinAccount(tenant_id=tenant_id, code=code, name=body.name, type=body.type, parent_id=parent_id,
                   currency=body.currency.upper() if body.currency else None, description=body.description,
                   money_kind=body.money_kind if body.type == AccountType.ASSET else None)
    db.add(a)
    await db.flush()
    return _acc(a)


@router.patch("/accounts/{account_id}", summary="Edit an account (code and type are fixed)")
async def update_account(account_id: uuid.UUID, body: AccountUpdate,
                         user: User = Depends(require_permission("finance.manage")),
                         tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    a = await _get_account(db, tenant_id, account_id)
    data = body.model_dump(exclude_unset=True)
    if "parent_id" in data and data["parent_id"]:
        if data["parent_id"] == a.id:
            raise ConflictError("An account cannot be its own parent")
        parent = await _get_account(db, tenant_id, data["parent_id"])
        if parent.type != a.type:
            raise ConflictError("Parent account must be of the same type")
    for k, v in data.items():
        setattr(a, k, v)
    await db.flush()
    return _acc(a)


# ── journal ──────────────────────────────────────────────────────
@router.get("/journal", summary="List journal entries")
async def list_entries(date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                       account_id: uuid.UUID | None = None,
                       page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                       user: User = Depends(require_permission("finance.view")),
                       tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    from app.models.finance import FinJournalLine
    f = [FinJournalEntry.tenant_id == tenant_id, FinJournalEntry.is_deleted == False]  # noqa: E712
    if date_from:
        f.append(FinJournalEntry.entry_date >= date_from)
    if date_to:
        f.append(FinJournalEntry.entry_date <= date_to)
    if account_id:
        f.append(FinJournalEntry.id.in_(select(FinJournalLine.entry_id).where(
            FinJournalLine.tenant_id == tenant_id, FinJournalLine.account_id == account_id)))
    total = (await db.execute(select(func.count()).select_from(FinJournalEntry).where(*f))).scalar_one()
    items = (await db.execute(select(FinJournalEntry).where(*f)
             .order_by(FinJournalEntry.entry_date.desc(), FinJournalEntry.number.desc())
             .offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return {"items": [_entry(e) for e in items], "total": total, "page": page, "page_size": page_size}


@router.get("/journal/{entry_id}", summary="One journal entry with its lines")
async def get_entry(entry_id: uuid.UUID, user: User = Depends(require_permission("finance.view")),
                    tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    e, lines = await ledger.get_entry(db, tenant_id, entry_id)
    return _entry(e, lines)


@router.post("/journal", status_code=status.HTTP_201_CREATED, summary="Post a balanced journal entry")
async def post_entry(body: EntryCreate, user: User = Depends(require_permission("finance.post")),
                     tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    e = await ledger.post_entry(
        db, tenant_id, entry_date=body.entry_date, memo=body.memo, reference=body.reference, created_by=user.id,
        lines=[ledger.LineIn(l.account_id, l.side, l.amount, l.currency, l.rate, l.description) for l in body.lines])
    _, lines = await ledger.get_entry(db, tenant_id, e.id)
    return _entry(e, lines)


@router.post("/journal/{entry_id}/void", summary="Void an entry by posting a reversal")
async def void_entry(entry_id: uuid.UUID, body: VoidBody, user: User = Depends(require_permission("finance.void")),
                     tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    rev = await ledger.void_entry(db, tenant_id, entry_id, reason=body.reason, on=body.on, created_by=user.id)
    _, lines = await ledger.get_entry(db, tenant_id, rev.id)
    return _entry(rev, lines)


@router.get("/trial-balance", summary="Trial balance")
async def trial_balance(as_of: datetime.date | None = None, user: User = Depends(require_permission("finance.view")),
                        tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return await ledger.trial_balance(db, tenant_id, as_of)


# ── exchange rates ───────────────────────────────────────────────
@router.get("/exchange-rates", summary="List exchange rates")
async def list_rates(user: User = Depends(require_permission("finance.view")),
                     tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.execute(select(FinExchangeRate).where(
        FinExchangeRate.tenant_id == tenant_id, FinExchangeRate.is_deleted == False)  # noqa: E712
        .order_by(FinExchangeRate.on_date.desc(), FinExchangeRate.currency))).scalars().all()
    return {"items": [{"id": str(r.id), "currency": r.currency, "on_date": r.on_date.isoformat(), "rate": str(r.rate)} for r in rows]}


@router.put("/exchange-rates", summary="Set the rate for a currency on a date")
async def set_rate(body: RateBody, user: User = Depends(require_permission("finance.manage")),
                   tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    cur = body.currency.upper()
    if cur == await ledger.base_currency(db, tenant_id):
        raise ConflictError("The base currency always has rate 1")
    row = (await db.execute(select(FinExchangeRate).where(
        FinExchangeRate.tenant_id == tenant_id, FinExchangeRate.currency == cur,
        FinExchangeRate.on_date == body.on_date))).scalar_one_or_none()
    if row is None:
        row = FinExchangeRate(tenant_id=tenant_id, currency=cur, on_date=body.on_date, rate=body.rate)
        db.add(row)
    else:
        row.rate = body.rate
        row.is_deleted, row.deleted_at = False, None
    await db.flush()
    return {"id": str(row.id), "currency": row.currency, "on_date": row.on_date.isoformat(), "rate": str(row.rate)}


# ── tax rates (configurable; nothing jurisdiction-specific is hard-coded) ──
def _tax(t: FinTaxRate) -> dict:
    return {"id": str(t.id), "name": t.name, "percent": str(t.percent), "kind": t.kind,
            "account_id": str(t.account_id) if t.account_id else None, "is_active": t.is_active}


@router.get("/tax-rates", summary="List tax rates")
async def list_taxes(user: User = Depends(require_permission("finance.view")),
                     tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.execute(select(FinTaxRate).where(
        FinTaxRate.tenant_id == tenant_id, FinTaxRate.is_deleted == False).order_by(FinTaxRate.name))).scalars().all()  # noqa: E712
    return {"items": [_tax(t) for t in rows]}


@router.post("/tax-rates", status_code=status.HTTP_201_CREATED, summary="Add a tax rate")
async def create_tax(body: TaxBody, user: User = Depends(require_permission("finance.manage")),
                     tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    if body.account_id:
        await _get_account(db, tenant_id, body.account_id)
    t = FinTaxRate(tenant_id=tenant_id, **body.model_dump())
    db.add(t)
    await db.flush()
    return _tax(t)
