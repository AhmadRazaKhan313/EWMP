"""
Payroll Tax Engine — progressive/marginal bracket calculation.

Deliberately contains NO jurisdiction-specific tax rules or numbers. Every
tenant configures their own PayrollTaxRule + PayrollTaxBracket rows for
their own country/tax year; this module only implements the generic
marginal-bracket MATH, the same shape used by most progressive income tax
systems worldwide (each slice of income is taxed at the rate for the
bracket it falls into, not the whole amount at one rate).
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


@dataclass(frozen=True)
class TaxBracketData:
    min_amount: Decimal
    max_amount: Decimal | None  # None = no upper bound (the top bracket)
    rate_percentage: Decimal


def calculate_progressive_tax(taxable_income: Decimal, brackets: list[TaxBracketData]) -> Decimal:
    """
    Standard marginal-bracket tax calculation.

    Example: brackets = [(0-50000 @ 0%), (50000-100000 @ 10%), (100000-None @ 20%)]
    taxable_income = 120000
      -> 0% on the first 50,000       = 0
      -> 10% on the next 50,000       = 5,000
      -> 20% on the remaining 20,000  = 4,000
      -> total tax = 9,000

    An empty bracket list (no tax rule configured) returns 0, not an error —
    payroll must still be able to run for tenants that haven't set up tax
    yet; PAYROLL_VALIDATION should be the one to flag that as a warning, not
    this function raising and blocking the whole calculation.
    """
    if taxable_income <= 0:
        return Decimal("0.00")

    sorted_brackets = sorted(brackets, key=lambda b: b.min_amount)
    tax = Decimal("0")
    for bracket in sorted_brackets:
        if taxable_income <= bracket.min_amount:
            break
        upper = bracket.max_amount if bracket.max_amount is not None else taxable_income
        taxable_in_bracket = min(taxable_income, upper) - bracket.min_amount
        if taxable_in_bracket <= 0:
            continue
        tax += taxable_in_bracket * (bracket.rate_percentage / Decimal("100"))

    return tax.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def annualize(monthly_amount: Decimal) -> Decimal:
    return monthly_amount * Decimal("12")


def monthly_from_annual(annual_amount: Decimal) -> Decimal:
    return (annual_amount / Decimal("12")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
