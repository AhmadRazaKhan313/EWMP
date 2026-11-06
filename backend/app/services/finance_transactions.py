"""
Finance Phase 1: simple Income / Expense / Transfer entries on top of the ledger.

A "transaction" is a normal balanced journal entry with source_type
'txn:income' | 'txn:expense' | 'txn:transfer' and exactly two lines:

  income   Dr money account   Cr category (income / equity / liability account)
  expense  Dr category        Cr money account
  transfer Dr to-account      Cr from-account

Voided transactions (the original and its reversal) are left out of lists and sums.
"""
import csv
import hashlib
import io
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.finance import AccountType, EntryStatus, FinAccount, FinJournalEntry, FinJournalLine, FinPaymentProvider
from app.services import finance_ledger as ledger

TXN_TYPES = ("income", "expense", "transfer")
# Asset accounts that are not cash / bank / wallet (header, receivables, fixed assets).
BANKS = [
    "HBL (Habib Bank)", "UBL (United Bank)", "MCB Bank", "Allied Bank", "Bank Alfalah", "Meezan Bank", "Faysal Bank",
    "Askari Bank", "Standard Chartered", "Bank AL Habib", "Habib Metropolitan Bank", "Soneri Bank", "JS Bank",
    "National Bank of Pakistan", "Bank of Punjab", "BankIslami", "Dubai Islamic Bank", "Al Baraka Bank",
    "Silkbank", "Sindh Bank", "Bank of Khyber", "Samba Bank", "Summit Bank", "ZTBL (Zarai Taraqiati Bank)",
]
WALLETS = ["JazzCash", "Easypaisa", "SadaPay", "NayaPay", "UPaisa", "HBL Konnect", "Zindigi", "Finja"]
DEFAULT_PROVIDERS = {"bank": BANKS, "wallet": WALLETS}

NON_MONEY_CODES = ("1000", "1100", "1200", "1500")
# Category account types each transaction type may use.
CATEGORY_TYPES = {
    "income": {AccountType.INCOME, AccountType.EQUITY, AccountType.LIABILITY},
    "expense": {AccountType.EXPENSE, AccountType.ASSET, AccountType.LIABILITY},
}

# Names people use in sheets -> the chart-of-accounts name, per transaction type.
ALIASES = {
    "income": {"founders investment": "Founders Capital", "founder investment": "Founders Capital",
               "loan": "Loans", "upwork": "Upwork Income", "client payment": "Client Payments",
               "client payments": "Client Payments", "other": "Other Income"},
    "expense": {"upwork": "Upwork Connects", "assets": "Fixed Assets", "asset": "Fixed Assets",
                "other": "Other Expenses", "gift": "Gifts"},
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


async def _account(db, tenant_id, account_id, label) -> FinAccount:
    a = (await db.execute(select(FinAccount).where(
        FinAccount.id == account_id, FinAccount.tenant_id == tenant_id, FinAccount.is_deleted == False  # noqa: E712
    ))).scalar_one_or_none()
    if a is None:
        raise UnprocessableError(f"{label} not found")
    if not a.is_active:
        raise UnprocessableError(f"{label} {a.code} is inactive")
    return a


async def create_transaction(
    db: AsyncSession, tenant_id: uuid.UUID, *, type: str, entry_date: date, amount: Decimal,
    account_id: uuid.UUID, category_id: uuid.UUID | None = None, to_account_id: uuid.UUID | None = None,
    description: str | None = None, reference: str | None = None, currency: str | None = None,
    rate: Decimal | None = None, created_by: uuid.UUID | None = None, payment_provider: str | None = None,
    payment_account_no: str | None = None, payment_tid: str | None = None,
) -> FinJournalEntry:
    if type not in TXN_TYPES:
        raise UnprocessableError("type must be income, expense or transfer")
    money = await _account(db, tenant_id, account_id, "Account")
    if money.type != AccountType.ASSET:
        raise UnprocessableError("Pick a cash / bank / wallet account for 'account'")
    if type == "transfer":
        if to_account_id is None:
            raise UnprocessableError("Transfers need a destination account")
        dest = await _account(db, tenant_id, to_account_id, "Destination account")
        if dest.type != AccountType.ASSET:
            raise UnprocessableError("Destination must be a cash / bank / wallet account")
        if dest.id == money.id:
            raise UnprocessableError("Source and destination accounts must differ")
        debit_acc, credit_acc = dest, money
    else:
        if category_id is None:
            raise UnprocessableError("Pick a category")
        cat = await _account(db, tenant_id, category_id, "Category")
        if cat.type not in CATEGORY_TYPES[type]:
            raise UnprocessableError(f"Category '{cat.name}' cannot be used for {type}")
        if cat.id == money.id:
            raise UnprocessableError("Category and account must differ")
        debit_acc, credit_acc = (money, cat) if type == "income" else (cat, money)

    provider = (payment_provider or "").strip() or None
    acc_no = (payment_account_no or "").strip() or None
    tid = (payment_tid or "").strip() or None
    if provider or acc_no or tid:
        kind = ledger.account_kind(money)
        if type == "transfer" or kind not in ("bank", "wallet"):
            raise UnprocessableError("Bank / wallet details only apply to income and expenses on a bank or mobile-wallet account")
        if provider is None:
            raise UnprocessableError("Pick the bank or wallet name")
        await _remember_provider(db, tenant_id, kind, provider)

    lines = [
        ledger.LineIn(debit_acc.id, "debit", amount, currency, rate, description),
        ledger.LineIn(credit_acc.id, "credit", amount, currency, rate, description),
    ]
    entry = await ledger.post_entry(
        db, tenant_id, entry_date=entry_date, lines=lines, memo=description, reference=reference,
        source_type=f"txn:{type}", created_by=created_by,
    )
    entry.payment_provider, entry.payment_account_no, entry.payment_tid = provider, acc_no, tid
    await db.flush()
    return entry


async def providers(db: AsyncSession, tenant_id: uuid.UUID, kind: str) -> list[str]:
    """Built-in names first, then the ones this organization added (alphabetical)."""
    if kind not in DEFAULT_PROVIDERS:
        raise UnprocessableError("kind must be bank or wallet")
    custom = (await db.execute(select(FinPaymentProvider.name).where(
        FinPaymentProvider.tenant_id == tenant_id, FinPaymentProvider.kind == kind,
        FinPaymentProvider.is_deleted == False).order_by(FinPaymentProvider.name))).scalars().all()  # noqa: E712
    return DEFAULT_PROVIDERS[kind] + [c for c in custom if c.lower() not in {d.lower() for d in DEFAULT_PROVIDERS[kind]}]


async def _remember_provider(db: AsyncSession, tenant_id: uuid.UUID, kind: str, name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()[:100]
    if not name:
        raise UnprocessableError("Name is required")
    if name.lower() in {n.lower() for n in await providers(db, tenant_id, kind)}:
        return next(n for n in await providers(db, tenant_id, kind) if n.lower() == name.lower())
    db.add(FinPaymentProvider(tenant_id=tenant_id, kind=kind, name=name))
    await db.flush()
    return name


async def add_provider(db: AsyncSession, tenant_id: uuid.UUID, kind: str, name: str) -> list[str]:
    if kind not in DEFAULT_PROVIDERS:
        raise UnprocessableError("kind must be bank or wallet")
    await _remember_provider(db, tenant_id, kind, name)
    return await providers(db, tenant_id, kind)


def _visible(tenant_id):
    return [
        FinJournalEntry.tenant_id == tenant_id, FinJournalEntry.is_deleted == False,  # noqa: E712
        FinJournalEntry.source_type.like("txn:%"),
        FinJournalEntry.status == EntryStatus.POSTED, FinJournalEntry.reverses_id.is_(None),
    ]


async def list_transactions(
    db: AsyncSession, tenant_id: uuid.UUID, *, type: str | None = None, date_from: date | None = None,
    date_to: date | None = None, category_id: uuid.UUID | None = None, account_id: uuid.UUID | None = None,
    search: str | None = None, page: int = 1, page_size: int = 50, all_rows: bool = False,
) -> tuple[list[dict], int]:
    f = _visible(tenant_id)
    if type:
        f.append(FinJournalEntry.source_type == f"txn:{type}")
    if date_from:
        f.append(FinJournalEntry.entry_date >= date_from)
    if date_to:
        f.append(FinJournalEntry.entry_date <= date_to)
    if search:
        f.append(FinJournalEntry.memo.ilike(f"%{search}%"))
    for acc in (category_id, account_id):
        if acc:
            f.append(FinJournalEntry.id.in_(select(FinJournalLine.entry_id).where(
                FinJournalLine.tenant_id == tenant_id, FinJournalLine.account_id == acc)))
    total = (await db.execute(select(func.count()).select_from(FinJournalEntry).where(*f))).scalar_one()
    q = select(FinJournalEntry).where(*f).order_by(FinJournalEntry.entry_date.desc(), FinJournalEntry.number.desc())
    if not all_rows:
        q = q.offset((page - 1) * page_size).limit(page_size)
    entries = (await db.execute(q)).scalars().all()
    if not entries:
        return [], total
    lines = (await db.execute(select(FinJournalLine).where(
        FinJournalLine.tenant_id == tenant_id, FinJournalLine.entry_id.in_([e.id for e in entries])
    ))).scalars().all()
    accs = {a.id: a for a in (await db.execute(select(FinAccount).where(
        FinAccount.tenant_id == tenant_id, FinAccount.id.in_({l.account_id for l in lines})))).scalars().all()}
    by_entry: dict[uuid.UUID, list[FinJournalLine]] = {}
    for l in lines:
        by_entry.setdefault(l.entry_id, []).append(l)

    out = []
    for e in entries:
        ls = by_entry.get(e.id, [])
        dr = next((l for l in ls if l.debit > 0), None)
        cr = next((l for l in ls if l.credit > 0), None)
        if dr is None or cr is None:
            continue
        kind = e.source_type.split(":", 1)[1]
        if kind == "income":
            money, other = dr, cr
        elif kind == "expense":
            money, other = cr, dr
        else:
            money, other = cr, dr  # from, to
        out.append({
            "id": str(e.id), "number": e.number, "type": kind, "date": e.entry_date.isoformat(),
            "amount": str(dr.debit), "currency": dr.currency, "amount_original": str(dr.amount_original),
            "description": e.memo, "reference": e.reference,
            "payment_provider": e.payment_provider, "payment_account_no": e.payment_account_no, "payment_tid": e.payment_tid,
            "account_id": str(money.account_id), "account": accs[money.account_id].name,
            "account_kind": ledger.account_kind(accs[money.account_id]),
            "category_id": str(other.account_id), "category": accs[other.account_id].name,
            "category_type": accs[other.account_id].type.value,
        })
    return out, total


async def summary(db: AsyncSession, tenant_id: uuid.UUID, date_from: date | None, date_to: date | None) -> dict:
    out: dict = {}
    for kind, side in (("income", FinJournalLine.credit), ("expense", FinJournalLine.debit)):
        q = (select(FinAccount.id, FinAccount.name, FinAccount.type, func.sum(side))
             .select_from(FinJournalLine)
             .join(FinJournalEntry, FinJournalEntry.id == FinJournalLine.entry_id)
             .join(FinAccount, FinAccount.id == FinJournalLine.account_id)
             .where(*_visible(tenant_id), FinJournalEntry.source_type == f"txn:{kind}",
                    FinJournalLine.tenant_id == tenant_id, side > 0))
        if date_from:
            q = q.where(FinJournalEntry.entry_date >= date_from)
        if date_to:
            q = q.where(FinJournalEntry.entry_date <= date_to)
        rows = (await db.execute(q.group_by(FinAccount.id, FinAccount.name, FinAccount.type)
                                 .order_by(func.sum(side).desc()))).all()
        out[kind] = [{"category_id": str(i), "category": n, "type": t.value, "total": str(s)} for i, n, t, s in rows]
    inc = sum(Decimal(r["total"]) for r in out["income"])
    exp = sum(Decimal(r["total"]) for r in out["expense"])
    operating = sum(Decimal(r["total"]) for r in out["income"] if r["type"] == "income")
    tb = await ledger.trial_balance(db, tenant_id, date_to)
    balances = [{"account_id": a["account_id"], "code": a["code"], "name": a["name"], "balance": a["balance"]}
                for a in tb["accounts"] if a["type"] == "asset" and a["code"] not in NON_MONEY_CODES]
    return {
        "currency": await ledger.base_currency(db, tenant_id),
        "income_total": str(inc), "income_operating": str(operating), "income_financing": str(inc - operating),
        "expense_total": str(exp), "balance": str(inc - exp), "profit": str(operating - exp),
        "income_by_category": out["income"], "expense_by_category": out["expense"],
        "money_accounts": balances,
    }


# ── import ───────────────────────────────────────────────────────
HEADER_ALIASES = {
    "date": {"date", "day"},
    "description": {"description", "details", "detail", "narration", "note", "notes", "item"},
    "category": {"category", "head", "type"},
    "amount": {"amount", "amt", "total", "value"},
}


@dataclass
class ImportResult:
    dry_run: bool
    total_rows: int = 0
    to_import: int = 0
    imported: int = 0
    duplicates: int = 0
    date_order: str = "mdy"
    skipped: list[dict] = field(default_factory=list)
    new_categories: list[str] = field(default_factory=list)
    preview: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _read_rows(filename: str, content: bytes) -> list[list]:
    name = (filename or "").lower()
    if name.endswith(".xlsx") or name.endswith(".xlsm"):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        return [list(r) for r in ws.iter_rows(values_only=True)]
    if name.endswith(".csv") or name.endswith(".txt"):
        text = content.decode("utf-8-sig", errors="replace")
        return [list(r) for r in csv.reader(io.StringIO(text))]
    raise UnprocessableError("Upload a .xlsx or .csv file")


def _map_header(rows: list[list]) -> tuple[int, dict[str, int]]:
    for i, row in enumerate(rows[:10]):
        found: dict[str, int] = {}
        for j, cell in enumerate(row):
            n = _norm(str(cell)) if cell is not None else ""
            for key, names in HEADER_ALIASES.items():
                if n in names and key not in found:
                    found[key] = j
        if {"date", "amount", "category"} <= found.keys():
            return i, found
    raise UnprocessableError("Could not find the header row. Expected columns: Date, Amount, Description, Category")


def _parse_amount(v) -> Decimal | None:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v))
    s = re.sub(r"(?i)rs\.?|pkr|₨|,|\s", "", str(v))
    try:
        return Decimal(s)
    except InvalidOperation:
        raise ValueError(f"amount '{v}' is not a number")


def _detect_order(values: list) -> str | None:
    first_big = second_big = False
    for v in values:
        if isinstance(v, str) and re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", v.strip()):
            a, b = (int(x) for x in re.split(r"[/-]", v.strip())[:2])
            first_big |= a > 12
            second_big |= b > 12
    if first_big and not second_big:
        return "dmy"
    if second_big and not first_big:
        return "mdy"
    return None


def _parse_date(v, order: str) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}.*", s):
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", s)
    if not m:
        raise ValueError(f"date '{v}' not understood")
    a, b, y = int(m[1]), int(m[2]), int(m[3])
    y += 2000 if y < 100 else 0
    d, mo = (a, b) if order == "dmy" else (b, a)
    return date(y, mo, d)


async def import_rows(
    db: AsyncSession, tenant_id: uuid.UUID, *, type: str, account_id: uuid.UUID, filename: str, content: bytes,
    dry_run: bool = True, create_missing: bool = True, date_order: str | None = None, created_by: uuid.UUID | None = None,
) -> ImportResult:
    if type not in ("income", "expense"):
        raise UnprocessableError("type must be income or expense")
    await _account(db, tenant_id, account_id, "Account")
    rows = _read_rows(filename, content)
    hi, cols = _map_header(rows)
    body = [(hi + 2 + i, r) for i, r in enumerate(rows[hi + 1:])]  # (spreadsheet row number, cells)
    body = [(n, r) for n, r in body if any(c not in (None, "") for c in r)]
    res = ImportResult(dry_run=dry_run, total_rows=len(body))

    order = date_order or _detect_order([r[cols["date"]] for _, r in body if cols["date"] < len(r)]) or "mdy"
    res.date_order = order

    accounts = (await db.execute(select(FinAccount).where(
        FinAccount.tenant_id == tenant_id, FinAccount.is_deleted == False))).scalars().all()  # noqa: E712
    by_name = {_norm(a.name): a for a in accounts}
    allowed = CATEGORY_TYPES[type]
    pending_new: dict[str, str] = {}  # norm name -> display name

    def get(r, key):
        j = cols.get(key)
        return r[j] if j is not None and j < len(r) else None

    parsed = []
    seen: dict[str, int] = {}
    for n, r in body:
        try:
            amount = _parse_amount(get(r, "amount"))
            if amount is None or amount == 0:
                res.skipped.append({"row": n, "reason": "amount is empty or zero"})
                continue
            if amount < 0:
                amount = -amount
            d = _parse_date(get(r, "date"), order)
            raw_cat = str(get(r, "category") or "").strip()
            if not raw_cat:
                res.skipped.append({"row": n, "reason": "category is empty"})
                continue
            key = _norm(raw_cat)
            target = ALIASES[type].get(key)
            acc = by_name.get(_norm(target)) if target else by_name.get(key)
            if acc is not None and acc.type not in allowed:
                res.skipped.append({"row": n, "reason": f"category '{raw_cat}' is a {acc.type.value} account, not usable for {type}"})
                continue
            if acc is None:
                if not create_missing:
                    res.skipped.append({"row": n, "reason": f"unknown category '{raw_cat}'"})
                    continue
                pending_new.setdefault(key, raw_cat)
            desc = str(get(r, "description") or "").strip() or None
            h = hashlib.sha1(f"{type}|{account_id}|{d}|{amount}|{desc}|{key}".encode()).hexdigest()[:20]
            seen[h] = seen.get(h, 0) + 1
            parsed.append(dict(row=n, date=d, amount=amount, desc=desc, key=key, raw_cat=raw_cat, acc=acc,
                               ref=f"import:{h}:{seen[h]}"))
        except ValueError as e:
            res.skipped.append({"row": n, "reason": str(e)})

    existing = set()
    if parsed:
        existing = set((await db.execute(select(FinJournalEntry.reference).where(
            *_visible(tenant_id), FinJournalEntry.reference.in_([p["ref"] for p in parsed])))).scalars().all())
    fresh = []
    for p in parsed:
        if p["ref"] in existing:
            res.duplicates += 1
            res.skipped.append({"row": p["row"], "reason": "already imported"})
        else:
            fresh.append(p)
    res.to_import = len(fresh)
    res.new_categories = sorted({v for k, v in pending_new.items() if any(p["key"] == k for p in fresh)})
    res.preview = [{"row": p["row"], "date": p["date"].isoformat(), "amount": str(p["amount"]), "description": p["desc"],
                    "category": p["acc"].name if p["acc"] else f"{p['raw_cat']} (new)"} for p in fresh[:20]]
    if dry_run or not fresh:
        return res

    # create the missing categories, then post every row
    new_type = AccountType.INCOME if type == "income" else AccountType.EXPENSE
    created: dict[str, FinAccount] = {}
    root = by_name.get("income" if type == "income" else "expenses")
    for p in fresh:
        if p["acc"] is None:
            if p["key"] not in created:
                code_base = 4900 if type == "income" else 5900
                used = {a.code for a in accounts} | {a.code for a in created.values()}
                code = next(str(c) for c in range(code_base - 1, code_base - 90, -1) if str(c) not in used)
                a = FinAccount(tenant_id=tenant_id, code=code, name=p["raw_cat"][:150], type=new_type,
                               parent_id=root.id if root else None)
                db.add(a)
                await db.flush()
                created[p["key"]] = a
            p["acc"] = created[p["key"]]
    for p in fresh:
        await create_transaction(db, tenant_id, type=type, entry_date=p["date"], amount=p["amount"],
                                 account_id=account_id, category_id=p["acc"].id, description=p["desc"],
                                 reference=p["ref"], created_by=created_by)
        res.imported += 1
    return res


async def export_workbook(db: AsyncSession, tenant_id: uuid.UUID, date_from: date | None, date_to: date | None) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    wb.remove(wb.active)
    for kind, title in (("expense", "Expenses"), ("income", "Income")):
        rows, _ = await list_transactions(db, tenant_id, type=kind, date_from=date_from, date_to=date_to, all_rows=True)
        ws = wb.create_sheet(title)
        ws.append(["Date", "Amount", "Description", "Category"])
        for c in ws[1]:
            c.font = Font(bold=True)
        for r in sorted(rows, key=lambda r: r["date"]):
            ws.append([date.fromisoformat(r["date"]), float(r["amount"]), r["description"] or "", r["category"]])
        n = len(rows) + 1
        ws.append(["Total", f"=SUM(B2:B{n})"])
        ws.cell(row=n + 1, column=1).font = Font(bold=True)
        for col, w in zip("ABCD", (14, 14, 60, 22)):
            ws.column_dimensions[col].width = w
        for row in ws.iter_rows(min_row=2, max_row=n, min_col=1, max_col=1):
            row[0].number_format = "yyyy-mm-dd"
        for row in ws.iter_rows(min_row=2, max_row=n + 1, min_col=2, max_col=2):
            row[0].number_format = "#,##0.00"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
