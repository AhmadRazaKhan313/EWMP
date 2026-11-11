"""Finance Phase 6: tax report. Accrual basis: output tax from invoices, input tax from bills, by issue date and tax rate.

Voided and draft documents are left out. Amounts are converted to the base currency at the document's own rate.
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.core.exceptions import UnprocessableError
from app.models.finance import FinTaxRate
from app.models.finance_purchases import BillStatus, FinBill, FinBillLine
from app.models.finance_sales import FinInvoice, FinInvoiceLine, InvoiceStatus
from app.services import finance_ledger as led

ZERO = Decimal("0")


def _q(v) -> Decimal:
    return Decimal(v).quantize(Decimal("0.01"))


async def _side(db, tenant_id, doc, line, link, statuses, date_from, date_to) -> list[dict]:
    q = (select(line.tax_rate_id, line.tax_percent, FinTaxRate.name,
                func.coalesce(func.sum(line.net_amount * doc.exchange_rate), 0),
                func.coalesce(func.sum(line.tax_amount * doc.exchange_rate), 0),
                func.count(func.distinct(doc.id)))
         .select_from(line)
         .join(doc, doc.id == link)
         .outerjoin(FinTaxRate, FinTaxRate.id == line.tax_rate_id)
         .where(line.tenant_id == tenant_id, doc.tenant_id == tenant_id, doc.is_deleted == False,  # noqa: E712
                line.is_deleted == False, doc.status.in_(statuses),  # noqa: E712
                doc.issue_date >= date_from, doc.issue_date <= date_to)
         .group_by(line.tax_rate_id, line.tax_percent, FinTaxRate.name)
         .order_by(line.tax_percent.desc(), FinTaxRate.name))
    rows = []
    for rate_id, pct, name, net, tax, n in (await db.execute(q)).all():
        rows.append({"tax_rate_id": str(rate_id) if rate_id else None,
                     "name": name or ("No tax" if Decimal(pct) == 0 else f"{Decimal(pct).normalize():f}%"),
                     "percent": str(Decimal(pct).normalize()), "taxable": str(_q(net)), "tax": str(_q(tax)), "documents": int(n)})
    return rows


def _total(rows: list[dict]) -> dict:
    return {"taxable": str(_q(sum((Decimal(r["taxable"]) for r in rows), ZERO))),
            "tax": str(_q(sum((Decimal(r["tax"]) for r in rows), ZERO)))}


async def tax_report(db, tenant_id: uuid.UUID, date_from: date, date_to: date) -> dict:
    if date_from > date_to:
        raise UnprocessableError("'From' date cannot be after the 'To' date")
    sales = await _side(db, tenant_id, FinInvoice, FinInvoiceLine, FinInvoiceLine.invoice_id,
                        (InvoiceStatus.SENT, InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.PAID), date_from, date_to)
    purchases = await _side(db, tenant_id, FinBill, FinBillLine, FinBillLine.bill_id,
                            (BillStatus.OPEN, BillStatus.PARTIALLY_PAID, BillStatus.PAID), date_from, date_to)
    st, pt = _total(sales), _total(purchases)
    net = _q(Decimal(st["tax"]) - Decimal(pt["tax"]))
    return {"date_from": date_from.isoformat(), "date_to": date_to.isoformat(), "currency": await led.base_currency(db, tenant_id),
            "sales": {"rows": sales, **st}, "purchases": {"rows": purchases, **pt},
            "net_tax_payable": str(net)}
