from decimal import Decimal

from app.models.payroll import AccountMappingPurpose
from app.services.payroll_accounting import (
    generate_journal_entries, total_debits, total_credits, PayslipLineData, DEFAULT_ACCOUNT_CODES,
)


def _balanced_lines():
    lines = [
        PayslipLineData("BASIC", "earning", Decimal("100000")),
        PayslipLineData("HOUSE", "earning", Decimal("20000")),
        PayslipLineData("TAX", "deduction", Decimal("9000")),
        PayslipLineData("PENSION_EE", "deduction", Decimal("5000")),
        PayslipLineData("PENSION_ER", "employer_contribution", Decimal("8000")),
        PayslipLineData("LOAN_abc123", "deduction", Decimal("1000")),
    ]
    net_pay = Decimal("120000") - Decimal("9000") - Decimal("5000") - Decimal("1000")
    return lines, net_pay


class TestJournalEntryBalance:
    def test_debits_always_equal_credits(self):
        lines, net_pay = _balanced_lines()
        entries = generate_journal_entries(lines, net_pay, {})
        assert total_debits(entries) == total_credits(entries)

    def test_balances_with_no_deductions_at_all(self):
        lines = [PayslipLineData("BASIC", "earning", Decimal("50000"))]
        entries = generate_journal_entries(lines, Decimal("50000"), {})
        assert total_debits(entries) == total_credits(entries) == Decimal("50000")

    def test_balances_with_employer_contributions_but_no_employee_deductions(self):
        lines = [
            PayslipLineData("BASIC", "earning", Decimal("50000")),
            PayslipLineData("PENSION_ER", "employer_contribution", Decimal("4000")),
        ]
        entries = generate_journal_entries(lines, Decimal("50000"), {})
        assert total_debits(entries) == total_credits(entries) == Decimal("54000")

    def test_zero_amount_purposes_are_omitted_not_zero_lines(self):
        lines = [PayslipLineData("BASIC", "earning", Decimal("50000"))]
        entries = generate_journal_entries(lines, Decimal("50000"), {})
        purposes = {e.purpose for e in entries}
        assert AccountMappingPurpose.TAX_PAYABLE not in purposes
        assert AccountMappingPurpose.LOAN_RECOVERY_PAYABLE not in purposes

    def test_salary_expense_is_a_debit_and_net_pay_payable_is_a_credit(self):
        lines, net_pay = _balanced_lines()
        entries = generate_journal_entries(lines, net_pay, {})
        salary = next(e for e in entries if e.purpose == AccountMappingPurpose.SALARY_EXPENSE)
        net = next(e for e in entries if e.purpose == AccountMappingPurpose.NET_PAY_PAYABLE)
        assert salary.debit > 0 and salary.credit == 0
        assert net.credit > 0 and net.debit == 0

    def test_uses_configured_account_mapping_over_default(self):
        lines = [PayslipLineData("BASIC", "earning", Decimal("50000"))]
        mapping = {AccountMappingPurpose.SALARY_EXPENSE: ("5100-SAL", "Salaries & Wages")}
        entries = generate_journal_entries(lines, Decimal("50000"), mapping)
        salary = next(e for e in entries if e.purpose == AccountMappingPurpose.SALARY_EXPENSE)
        assert salary.account_code == "5100-SAL"
        assert salary.account_name == "Salaries & Wages"

    def test_falls_back_to_clearly_labeled_placeholder_when_unmapped(self):
        lines = [PayslipLineData("BASIC", "earning", Decimal("50000"))]
        entries = generate_journal_entries(lines, Decimal("50000"), {})
        salary = next(e for e in entries if e.purpose == AccountMappingPurpose.SALARY_EXPENSE)
        assert "UNMAPPED" in salary.account_code

    def test_loan_and_advance_recoveries_classified_separately(self):
        lines = [
            PayslipLineData("BASIC", "earning", Decimal("50000")),
            PayslipLineData("LOAN_xyz", "deduction", Decimal("1000")),
            PayslipLineData("ADVANCE_xyz", "deduction", Decimal("500")),
        ]
        entries = generate_journal_entries(lines, Decimal("48500"), {})
        purposes = {e.purpose: e.credit for e in entries}
        assert purposes[AccountMappingPurpose.LOAN_RECOVERY_PAYABLE] == Decimal("1000")
        assert purposes[AccountMappingPurpose.ADVANCE_RECOVERY_PAYABLE] == Decimal("500")

    def test_unclassified_deduction_falls_into_other_deductions_payable(self):
        lines = [
            PayslipLineData("BASIC", "earning", Decimal("50000")),
            PayslipLineData("PARKING_FEE", "deduction", Decimal("200")),
        ]
        entries = generate_journal_entries(lines, Decimal("49800"), {})
        other = next(e for e in entries if e.purpose == AccountMappingPurpose.OTHER_DEDUCTIONS_PAYABLE)
        assert other.credit == Decimal("200")

    def test_default_account_codes_cover_every_purpose(self):
        assert set(DEFAULT_ACCOUNT_CODES.keys()) == set(AccountMappingPurpose)

    def test_realistic_multi_employee_run_still_balances(self):
        """Aggregating across many employees' payslip lines must still balance."""
        lines = []
        for _ in range(25):
            lines.append(PayslipLineData("BASIC", "earning", Decimal("80000")))
            lines.append(PayslipLineData("TAX", "deduction", Decimal("4500")))
            lines.append(PayslipLineData("PENSION_EE", "deduction", Decimal("4000")))
            lines.append(PayslipLineData("PENSION_ER", "employer_contribution", Decimal("6400")))
        net_pay_total = Decimal("25") * (Decimal("80000") - Decimal("4500") - Decimal("4000"))
        entries = generate_journal_entries(lines, net_pay_total, {})
        assert total_debits(entries) == total_credits(entries)
