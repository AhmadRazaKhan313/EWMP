"""
Per-employee recurring pay items (Medical, Fuel, Mobile, Loan EMI, ...).

HR adds these on the employee's Compensation tab as extra allowances and
deductions on top of the salary structure. Every payroll run turns them into
payslip lines. Pure functions only — no database access — so the rules are easy
to test:

  * ``fixed``             -> the amount typed in.
  * ``percent_of_basic``  -> that percentage of the employee's basic salary.
  * Allowances are prorated by attendance exactly like structure earnings;
    deductions are charged in full.
  * An item that works out to zero is skipped (no empty payslip lines).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

_CENT = Decimal("0.01")


@dataclass(frozen=True)
class ResolvedPayItem:
    code: str
    name: str
    amount: Decimal
    is_taxable: bool
    order: int


def _amount(item: dict, basic: Decimal) -> Decimal:
    if item.get("calculation") == "percent_of_basic":
        value = basic * Decimal(str(item.get("percentage") or 0)) / Decimal("100")
    else:
        value = Decimal(str(item.get("amount") or 0))
    return max(value, Decimal("0")).quantize(_CENT)


def _as_date(value) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def applies_in_period(item: dict, period_start: date | None, period_end: date | None) -> bool:
    """Does this pay item belong on a payslip for period_start..period_end?

    No period given -> always (keeps older callers working). Items saved before
    dates existed have none, so they stay recurring and open-ended."""
    if period_start is None or period_end is None:
        return True
    start, end = _as_date(item.get("effective_from")), _as_date(item.get("effective_to"))
    if item.get("frequency") == "one_time":
        return start is not None and period_start <= start <= period_end
    if start and start > period_end:
        return False
    if end and end < period_start:
        return False
    return True


def resolve_pay_items(
    items: list[dict] | None,
    basic: Decimal,
    period_start: date | None = None,
    period_end: date | None = None,
) -> tuple[list[ResolvedPayItem], list[ResolvedPayItem]]:
    """Return ``(earnings, deductions)`` for one employee, unprorated."""
    earnings: list[ResolvedPayItem] = []
    deductions: list[ResolvedPayItem] = []
    for index, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        if not applies_in_period(item, period_start, period_end):
            continue
        amount = _amount(item, basic)
        if amount <= 0:
            continue
        key = str(item.get("id") or index)[:8].upper()
        is_earning = item.get("kind") == "earning"
        resolved = ResolvedPayItem(
            code=f"EMP_{key}",
            name=str(item.get("name") or "Extra pay item")[:200],
            amount=amount,
            # A deduction is never "taxable income".
            is_taxable=bool(item.get("is_taxable", True)) if is_earning else False,
            order=(800 if is_earning else 8800) + index,
        )
        (earnings if is_earning else deductions).append(resolved)
    return earnings, deductions
