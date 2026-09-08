"""
Tests for the payroll tax engine and contribution engine (pure calculation
functions, no DB needed).

Run:  cd backend && pytest tests/test_payroll_tax_and_contribution_engine.py -v
"""
from decimal import Decimal

import pytest

from app.services.payroll_tax import calculate_progressive_tax, TaxBracketData, annualize, monthly_from_annual
from app.services.payroll_contribution import calculate_contribution, ContributionRuleData


# Example brackets used across tests — deliberately round, made-up numbers.
# NOT real tax law for any jurisdiction; every tenant configures their own.
EXAMPLE_BRACKETS = [
    TaxBracketData(Decimal("0"), Decimal("50000"), Decimal("0")),
    TaxBracketData(Decimal("50000"), Decimal("100000"), Decimal("10")),
    TaxBracketData(Decimal("100000"), None, Decimal("20")),
]


class TestProgressiveTax:
    def test_income_within_the_zero_rate_bracket_pays_nothing(self):
        assert calculate_progressive_tax(Decimal("30000"), EXAMPLE_BRACKETS) == Decimal("0.00")

    def test_income_exactly_at_a_bracket_boundary(self):
        # Exactly 50,000 -> still fully in the 0% bracket (boundary is exclusive-below-next)
        assert calculate_progressive_tax(Decimal("50000"), EXAMPLE_BRACKETS) == Decimal("0.00")

    def test_income_spanning_two_brackets(self):
        # 70,000: first 50k @ 0% = 0, next 20k @ 10% = 2000
        assert calculate_progressive_tax(Decimal("70000"), EXAMPLE_BRACKETS) == Decimal("2000.00")

    def test_income_spanning_all_three_brackets(self):
        # 120,000: 0 + (50k*10%=5000) + (20k*20%=4000) = 9000
        assert calculate_progressive_tax(Decimal("120000"), EXAMPLE_BRACKETS) == Decimal("9000.00")

    def test_zero_income_pays_zero_tax(self):
        assert calculate_progressive_tax(Decimal("0"), EXAMPLE_BRACKETS) == Decimal("0.00")

    def test_negative_income_pays_zero_tax_not_negative_tax(self):
        assert calculate_progressive_tax(Decimal("-5000"), EXAMPLE_BRACKETS) == Decimal("0.00")

    def test_no_brackets_configured_returns_zero_not_an_error(self):
        """A tenant that hasn't set up a tax rule yet must still be able to
        run payroll — validation (not this function) is what should warn
        them, not a crash here."""
        assert calculate_progressive_tax(Decimal("120000"), []) == Decimal("0.00")

    def test_brackets_out_of_order_in_the_input_still_calculate_correctly(self):
        shuffled = [EXAMPLE_BRACKETS[2], EXAMPLE_BRACKETS[0], EXAMPLE_BRACKETS[1]]
        assert calculate_progressive_tax(Decimal("120000"), shuffled) == Decimal("9000.00")

    def test_single_flat_bracket_acts_like_a_flat_tax(self):
        flat = [TaxBracketData(Decimal("0"), None, Decimal("15"))]
        assert calculate_progressive_tax(Decimal("100000"), flat) == Decimal("15000.00")

    def test_result_is_rounded_to_2_decimal_places(self):
        odd_brackets = [TaxBracketData(Decimal("0"), None, Decimal("12.5"))]
        result = calculate_progressive_tax(Decimal("100000.33"), odd_brackets)
        assert result == result.quantize(Decimal("0.01"))


class TestAnnualizeHelpers:
    def test_annualize_multiplies_by_12(self):
        assert annualize(Decimal("10000")) == Decimal("120000")

    def test_monthly_from_annual_divides_by_12_and_rounds(self):
        assert monthly_from_annual(Decimal("120000")) == Decimal("10000.00")

    def test_roundtrip_is_consistent(self):
        monthly = Decimal("8333.33")
        assert monthly_from_annual(annualize(monthly)) == monthly


EXAMPLE_CONTRIBUTION = ContributionRuleData(
    employee_percentage=Decimal("5"), employee_fixed_amount=None,
    employer_percentage=Decimal("8"), employer_fixed_amount=None,
    min_base=Decimal("10000"), max_base=Decimal("200000"),
)


class TestContributionCalculation:
    def test_percentage_based_contribution_both_sides(self):
        employee, employer = calculate_contribution(Decimal("100000"), EXAMPLE_CONTRIBUTION)
        assert employee == Decimal("5000.00")
        assert employer == Decimal("8000.00")

    def test_below_minimum_base_contributes_nothing_on_either_side(self):
        employee, employer = calculate_contribution(Decimal("5000"), EXAMPLE_CONTRIBUTION)
        assert employee == Decimal("0.00")
        assert employer == Decimal("0.00")

    def test_exactly_at_minimum_base_does_contribute(self):
        employee, employer = calculate_contribution(Decimal("10000"), EXAMPLE_CONTRIBUTION)
        assert employee == Decimal("500.00")

    def test_above_maximum_base_is_capped_before_percentage_applies(self):
        employee, employer = calculate_contribution(Decimal("300000"), EXAMPLE_CONTRIBUTION)
        assert employee == Decimal("10000.00")  # 200,000 * 5%, not 300,000 * 5%
        assert employer == Decimal("16000.00")  # 200,000 * 8%

    def test_fixed_amount_contribution(self):
        rule = ContributionRuleData(
            employee_percentage=None, employee_fixed_amount=Decimal("500"),
            employer_percentage=None, employer_fixed_amount=Decimal("1000"),
            min_base=None, max_base=None,
        )
        employee, employer = calculate_contribution(Decimal("50000"), rule)
        assert employee == Decimal("500.00")
        assert employer == Decimal("1000.00")

    def test_fixed_amount_and_percentage_can_combine(self):
        rule = ContributionRuleData(
            employee_percentage=Decimal("2"), employee_fixed_amount=Decimal("100"),
            employer_percentage=None, employer_fixed_amount=None,
            min_base=None, max_base=None,
        )
        employee, _ = calculate_contribution(Decimal("50000"), rule)
        assert employee == Decimal("1100.00")  # 50000*2% + 100

    def test_no_rule_fields_set_contributes_nothing(self):
        rule = ContributionRuleData(
            employee_percentage=None, employee_fixed_amount=None,
            employer_percentage=None, employer_fixed_amount=None,
            min_base=None, max_base=None,
        )
        employee, employer = calculate_contribution(Decimal("50000"), rule)
        assert employee == Decimal("0.00")
        assert employer == Decimal("0.00")

    def test_zero_base_contributes_nothing(self):
        employee, employer = calculate_contribution(Decimal("0"), EXAMPLE_CONTRIBUTION)
        assert employee == Decimal("0.00")
        assert employer == Decimal("0.00")
