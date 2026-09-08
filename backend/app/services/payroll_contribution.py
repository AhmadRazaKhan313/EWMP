"""
Payroll Contribution Engine — statutory/company contributions with
independent employee-side and employer-side amounts, and an optional
min/max base (contribution floor/ceiling).
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


@dataclass(frozen=True)
class ContributionRuleData:
    employee_percentage: Decimal | None
    employee_fixed_amount: Decimal | None
    employer_percentage: Decimal | None
    employer_fixed_amount: Decimal | None
    min_base: Decimal | None
    max_base: Decimal | None


def calculate_contribution(base_amount: Decimal, rule: ContributionRuleData) -> tuple[Decimal, Decimal]:
    """
    Returns (employee_side_amount, employer_side_amount).

    - base_amount below min_base -> both sides are 0 (common real-world
      pattern: no contribution below a minimum salary threshold).
    - base_amount above max_base -> the base used for the percentage
      calculation is capped at max_base (fixed amounts are unaffected by
      the cap either way).
    """
    effective_base = base_amount
    if rule.min_base is not None and base_amount < rule.min_base:
        effective_base = Decimal("0")
    elif rule.max_base is not None and base_amount > rule.max_base:
        effective_base = rule.max_base

    employee_amount = Decimal("0")
    if effective_base > 0 and rule.employee_percentage:
        employee_amount += effective_base * (rule.employee_percentage / Decimal("100"))
    if rule.employee_fixed_amount and effective_base > 0:
        employee_amount += rule.employee_fixed_amount

    employer_amount = Decimal("0")
    if effective_base > 0 and rule.employer_percentage:
        employer_amount += effective_base * (rule.employer_percentage / Decimal("100"))
    if rule.employer_fixed_amount and effective_base > 0:
        employer_amount += rule.employer_fixed_amount

    return (
        employee_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        employer_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
    )
