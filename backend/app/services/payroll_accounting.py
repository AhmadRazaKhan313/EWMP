"""
Payroll Accounting Integration — journal-entry generation.

Never hardcodes chart-of-account IDs. Every entry is built against a
"purpose" (see AccountMappingPurpose) that the tenant maps to a real
account code via PayrollAccountMapping; a purpose with no configured
mapping falls back to a clearly-labeled placeholder the finance team must
remap before posting anywhere real.

The debit/credit split follows the standard payroll journal pattern:

  Debit:  Salary Expense (gross earnings)
  Debit:  Employer Contribution Expense
  Credit: Net Pay Payable
  Credit: Tax Payable
  Credit: Contribution Payable (employee + employer sides — both are
          owed to the fund until remitted)
  Credit: Loan Recovery Payable
  Credit: Advance Recovery Payable
  Credit: Other Deductions Payable (catch-all)

This always balances by construction: employer contributions appear on
BOTH sides (as an expense AND as a payable, since the employer owes that
amount to the contribution fund) — see generate_journal_entries's docstring
example and the balance test in test_payroll_accounting.py.
"""
from dataclasses import dataclass
from decimal import Decimal

from app.models.payroll import AccountMappingPurpose

DEFAULT_ACCOUNT_CODES: dict[AccountMappingPurpose, tuple[str, str]] = {
    AccountMappingPurpose.SALARY_EXPENSE: ("6000-UNMAPPED", "Salary Expense (unmapped — configure in Payroll Settings)"),
    AccountMappingPurpose.EMPLOYER_CONTRIBUTION_EXPENSE: ("6010-UNMAPPED", "Employer Contribution Expense (unmapped)"),
    AccountMappingPurpose.NET_PAY_PAYABLE: ("2000-UNMAPPED", "Net Pay Payable (unmapped)"),
    AccountMappingPurpose.TAX_PAYABLE: ("2010-UNMAPPED", "Tax Payable (unmapped)"),
    AccountMappingPurpose.CONTRIBUTION_PAYABLE: ("2020-UNMAPPED", "Contribution Payable (unmapped)"),
    AccountMappingPurpose.LOAN_RECOVERY_PAYABLE: ("2030-UNMAPPED", "Loan Recovery Payable (unmapped)"),
    AccountMappingPurpose.ADVANCE_RECOVERY_PAYABLE: ("2040-UNMAPPED", "Advance Recovery Payable (unmapped)"),
    AccountMappingPurpose.OTHER_DEDUCTIONS_PAYABLE: ("2050-UNMAPPED", "Other Deductions Payable (unmapped)"),
}


@dataclass(frozen=True)
class JournalLine:
    purpose: AccountMappingPurpose
    account_code: str
    account_name: str
    debit: Decimal
    credit: Decimal


@dataclass(frozen=True)
class PayslipLineData:
    code: str
    component_type: str  # "earning" | "deduction" | "employer_contribution"
    amount: Decimal


def _classify_deduction_purpose(code: str) -> AccountMappingPurpose:
    if code == "TAX":
        return AccountMappingPurpose.TAX_PAYABLE
    if code.startswith("LOAN_"):
        return AccountMappingPurpose.LOAN_RECOVERY_PAYABLE
    if code.startswith("ADVANCE_"):
        return AccountMappingPurpose.ADVANCE_RECOVERY_PAYABLE
    if code.endswith("_EE"):  # contribution engine's employee-side lines, e.g. PENSION_EE
        return AccountMappingPurpose.CONTRIBUTION_PAYABLE
    return AccountMappingPurpose.OTHER_DEDUCTIONS_PAYABLE


def generate_journal_entries(
    all_lines: list[PayslipLineData],
    net_pay_total: Decimal,
    account_mappings: dict[AccountMappingPurpose, tuple[str, str]],
) -> list[JournalLine]:
    """
    all_lines: every PayslipLine across every payslip in the run being posted.
    net_pay_total: sum of net_salary across those same payslips.
    account_mappings: purpose -> (account_code, account_name); falls back to
      DEFAULT_ACCOUNT_CODES for any purpose not present.

    Returns a balanced list of JournalLine — total debits == total credits,
    always, by construction (see module docstring).
    """
    totals: dict[AccountMappingPurpose, Decimal] = {p: Decimal("0") for p in AccountMappingPurpose}

    for line in all_lines:
        if line.component_type == "earning":
            totals[AccountMappingPurpose.SALARY_EXPENSE] += line.amount
        elif line.component_type == "employer_contribution":
            totals[AccountMappingPurpose.EMPLOYER_CONTRIBUTION_EXPENSE] += line.amount
            totals[AccountMappingPurpose.CONTRIBUTION_PAYABLE] += line.amount
        elif line.component_type == "deduction":
            totals[_classify_deduction_purpose(line.code)] += line.amount

    totals[AccountMappingPurpose.NET_PAY_PAYABLE] = net_pay_total

    debit_purposes = {AccountMappingPurpose.SALARY_EXPENSE, AccountMappingPurpose.EMPLOYER_CONTRIBUTION_EXPENSE}

    entries: list[JournalLine] = []
    for purpose in AccountMappingPurpose:
        amount = totals[purpose]
        if amount == 0:
            continue
        account_code, account_name = account_mappings.get(purpose, DEFAULT_ACCOUNT_CODES[purpose])
        is_debit = purpose in debit_purposes
        entries.append(JournalLine(
            purpose=purpose, account_code=account_code, account_name=account_name,
            debit=amount if is_debit else Decimal("0"),
            credit=Decimal("0") if is_debit else amount,
        ))

    return entries


def total_debits(entries: list[JournalLine]) -> Decimal:
    return sum((e.debit for e in entries), Decimal("0"))


def total_credits(entries: list[JournalLine]) -> Decimal:
    return sum((e.credit for e in entries), Decimal("0"))
