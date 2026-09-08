"""
Payroll Commission Engine — tiered/marginal commission calculation.

Same marginal-bracket shape as the tax engine (app/services/payroll_tax.py):
each slice of the sales amount is paid at the rate for the tier it falls
into, not the whole amount at one flat rate. E.g. tiers
(0-100000 @ 2%), (100000-500000 @ 5%), (500000+ @ 8%) on sales of 600,000:
  2% * 100,000 + 5% * 400,000 + 8% * 100,000 = 2,000 + 20,000 + 8,000 = 30,000
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


@dataclass(frozen=True)
class CommissionTierData:
    min_amount: Decimal
    max_amount: Decimal | None
    rate_percentage: Decimal


def calculate_tiered_commission(sales_amount: Decimal, tiers: list[CommissionTierData]) -> Decimal:
    """Marginal tier calculation — see module docstring. No tiers configured
    (or non-positive sales) returns 0, not an error."""
    if sales_amount <= 0:
        return Decimal("0.00")

    sorted_tiers = sorted(tiers, key=lambda t: t.min_amount)
    commission = Decimal("0")
    for tier in sorted_tiers:
        if sales_amount <= tier.min_amount:
            break
        upper = tier.max_amount if tier.max_amount is not None else sales_amount
        amount_in_tier = min(sales_amount, upper) - tier.min_amount
        if amount_in_tier <= 0:
            continue
        commission += amount_in_tier * (tier.rate_percentage / Decimal("100"))

    return commission.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
