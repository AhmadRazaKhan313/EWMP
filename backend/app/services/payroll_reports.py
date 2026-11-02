"""
Payroll reports, all built from finished payroll only.

Counted: runs that are APPROVED, LOCKED or PAID; payslips that are not REVERSED
or deleted. Draft, review, processing, cancelled and reopened runs are left out
on purpose, so a half-finished run can never inflate the company's cost.

Money is split the way finance reads it:
  salary_gross        earnings except reimbursements
  employer_contrib    employer-side contributions (cost to the company)
  salary_cost         salary_gross + employer_contrib
  reimbursements      claims paid back (REIMB_* earning lines), shown on their own line
  total_paid_out      salary_cost + reimbursements
  deductions / net    what came off the employee, and what they received
"""

from __future__ import annotations

import calendar
import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee
from app.models.organization_structure import Branch, Department
from app.models.payroll import (
    ComponentType, PaymentBatch, PaymentBatchItem, PaymentItemStatus, Payslip, PayslipLine,
    PayslipStatus, PayrollRun, PayrollRunStatus,
)
from app.models.user import User
from app.services.report_engine import DATE, INT, MONEY, TEXT, Column, ReportResult

ZERO = Decimal("0")
COUNTED_RUNS = (PayrollRunStatus.APPROVED, PayrollRunStatus.LOCKED, PayrollRunStatus.PAID)
MONEY_KEYS = ("salary_gross", "employer_contrib", "salary_cost", "reimbursements",
              "total_paid_out", "tax", "employee_contrib", "loan_recovery", "other_deductions",
              "deductions", "net")


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def month_label(year: int, month: int) -> str:
    return f"{calendar.month_name[month]} {year}"


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def _blank() -> dict:
    return {k: ZERO for k in MONEY_KEYS} | {"employees": 0, "runs": 0}


def _classify(line: PayslipLine, bucket: dict) -> None:
    code, amt, kind = line.component_code or "", line.amount or ZERO, line.component_type
    if kind == ComponentType.EARNING:
        bucket["reimbursements" if code.startswith("REIMB_") else "salary_gross"] += amt
    elif kind == ComponentType.EMPLOYER_CONTRIBUTION:
        bucket["employer_contrib"] += amt
    elif kind == ComponentType.DEDUCTION:
        if code == "TAX":
            bucket["tax"] += amt
        elif code.endswith("_EE"):
            bucket["employee_contrib"] += amt
        elif code.startswith(("LOAN_", "ADVANCE_")):
            bucket["loan_recovery"] += amt
        else:
            bucket["other_deductions"] += amt


def _finish(b: dict) -> dict:
    b["salary_cost"] = b["salary_gross"] + b["employer_contrib"]
    b["total_paid_out"] = b["salary_cost"] + b["reimbursements"]
    return b


async def _payslips(
    db: AsyncSession, tenant_id: uuid.UUID, first: date, last: date, *,
    department_id: uuid.UUID | None = None, branch_id: uuid.UUID | None = None,
    search: str | None = None,
):
    """Counted payslips of runs whose period starts inside [first, last]."""
    q = (
        select(Payslip, PayrollRun, Employee, User, Department.name, Branch.name)
        .join(PayrollRun, PayrollRun.id == Payslip.payroll_run_id)
        .join(Employee, Employee.id == Payslip.employee_id)
        .join(User, User.id == Employee.user_id)
        .outerjoin(Department, Department.id == Employee.department_id)
        .outerjoin(Branch, Branch.id == Employee.branch_id)
        .where(
            Payslip.tenant_id == tenant_id, Payslip.is_deleted.is_(False),
            Payslip.status != PayslipStatus.REVERSED,
            PayrollRun.is_deleted.is_(False), PayrollRun.status.in_(COUNTED_RUNS),
            PayrollRun.period_start >= first, PayrollRun.period_start <= last,
        )
    )
    if department_id:
        q = q.where(Employee.department_id == department_id)
    if branch_id:
        q = q.where(Employee.branch_id == branch_id)
    if search:
        like = f"%{search.strip()}%"
        q = q.where(User.first_name.ilike(like) | User.last_name.ilike(like) | Employee.employee_code.ilike(like))
    rows = (await db.execute(q)).all()
    ids = [r[0].id for r in rows]
    lines: dict[uuid.UUID, list[PayslipLine]] = defaultdict(list)
    if ids:
        got = await db.execute(select(PayslipLine).where(
            PayslipLine.payslip_id.in_(ids), PayslipLine.is_deleted.is_(False)))
        for ln in got.scalars():
            lines[ln.payslip_id].append(ln)
    return rows, lines


def _name(user: User) -> str:
    return (getattr(user, "display_name", None) or f"{user.first_name} {user.last_name}").strip()


def _fill(bucket: dict, slip: Payslip, slip_lines: list[PayslipLine]) -> None:
    for ln in slip_lines:
        _classify(ln, bucket)
    bucket["deductions"] += slip.total_deductions or ZERO
    bucket["net"] += slip.net_salary or ZERO


_MONEY_COLS = [
    Column("salary_gross", "Gross salary", MONEY),
    Column("employer_contrib", "Employer contributions", MONEY),
    Column("salary_cost", "Salary cost", MONEY),
    Column("reimbursements", "Reimbursements", MONEY),
    Column("total_paid_out", "Total paid out", MONEY),
    Column("deductions", "Deductions", MONEY),
    Column("net", "Net salary", MONEY),
]


def _totals(rows: list[dict], label_key: str, label: str = "Total") -> dict:
    t = {k: sum((r.get(k, ZERO) for r in rows), ZERO) for k in MONEY_KEYS}
    t[label_key] = label
    return t


def _scope_note(notes: list[str]) -> list[str]:
    return notes + ["Only approved, locked or paid payroll runs are counted. Reversed payslips are excluded."]


async def payroll_expenses(
    db: AsyncSession, tenant_id: uuid.UUID, year: int, month: int, *,
    department_id=None, branch_id=None, months: int = 12,
) -> ReportResult:
    """Month by month payroll cost for the last `months` months, ending at the chosen month."""
    sy, sm = shift_month(year, month, -(months - 1))
    first, _ = month_bounds(sy, sm)
    _, last = month_bounds(year, month)
    rows, lines = await _payslips(db, tenant_id, first, last, department_id=department_id, branch_id=branch_id)

    buckets: dict[tuple[int, int], dict] = {}
    seen: dict[tuple[int, int], set] = defaultdict(set)
    runs: dict[tuple[int, int], set] = defaultdict(set)
    for slip, run, emp, _user, _d, _b in rows:
        key = (run.period_start.year, run.period_start.month)
        b = buckets.setdefault(key, _blank())
        _fill(b, slip, lines.get(slip.id, []))
        seen[key].add(emp.id)
        runs[key].add(run.id)

    out = []
    for i in range(months):
        y, m = shift_month(sy, sm, i)
        b = _finish(buckets.get((y, m), _blank()))
        b.update(month=month_label(y, m), employees=len(seen.get((y, m), ())), runs=len(runs.get((y, m), ())))
        out.append(b)

    cur = next(r for r in out if r["month"] == month_label(year, month))
    result = ReportResult(
        key="payroll-expenses", title="Monthly Payroll Expenses",
        subtitle=f"{months} months up to {month_label(year, month)}",
        columns=[Column("month", "Month"), Column("runs", "Runs", INT), Column("employees", "Employees paid", INT), *_MONEY_COLS],
        rows=out,
        summary=[
            {"label": "Employees paid", "value": cur["employees"], "type": INT},
            {"label": "Salary cost", "value": cur["salary_cost"], "type": MONEY},
            {"label": "Reimbursements", "value": cur["reimbursements"], "type": MONEY},
            {"label": "Total paid out", "value": cur["total_paid_out"], "type": MONEY},
            {"label": "Net salary", "value": cur["net"], "type": MONEY},
        ],
        notes=_scope_note(["Salary cost = gross salary + employer contributions. Reimbursements are shown separately."]),
    )
    t = _totals(out, "month")
    t.update(employees=None, runs=sum(r["runs"] for r in out))
    result.totals = t
    return result


async def payroll_department_cost(
    db: AsyncSession, tenant_id: uuid.UUID, year: int, month: int, *, department_id=None, branch_id=None,
) -> ReportResult:
    first, last = month_bounds(year, month)
    rows, lines = await _payslips(db, tenant_id, first, last, department_id=department_id, branch_id=branch_id)
    groups: dict[str, dict] = {}
    people: dict[str, set] = defaultdict(set)
    for slip, _run, emp, _user, dept, branch in rows:
        name = dept or "No department"
        b = groups.setdefault(name, _blank())
        _fill(b, slip, lines.get(slip.id, []))
        people[name].add(emp.id)
    out = []
    for name in sorted(groups, key=str.lower):
        b = _finish(groups[name])
        b.update(department=name, employees=len(people[name]))
        out.append(b)
    total = _finish(_totals(out, "department"))
    total["employees"] = len({e for s in people.values() for e in s})
    return ReportResult(
        key="payroll-department-cost", title="Payroll Cost by Department", subtitle=month_label(year, month),
        columns=[Column("department", "Department"), Column("employees", "Employees", INT), *_MONEY_COLS],
        rows=out, totals=total, notes=_scope_note([]),
    )


async def payroll_register(
    db: AsyncSession, tenant_id: uuid.UUID, year: int, month: int, *,
    department_id=None, branch_id=None, search=None,
) -> ReportResult:
    first, last = month_bounds(year, month)
    rows, lines = await _payslips(db, tenant_id, first, last, department_id=department_id,
                                  branch_id=branch_id, search=search)
    out = []
    for slip, run, emp, user, dept, _b in rows:
        b = _blank()
        _fill(b, slip, lines.get(slip.id, []))
        _finish(b)
        b.update(
            employee_code=emp.employee_code, employee_name=_name(user), department=dept or "",
            run=run.name, status=slip.status.value, working_days=slip.working_days,
            present_days=slip.present_days, absent_days=slip.absent_days,
            unpaid_leave_days=slip.unpaid_leave_days, overtime_hours=slip.overtime_hours,
        )
        out.append(b)
    out.sort(key=lambda r: (r["employee_name"].lower(), r["run"]))
    cols = [
        Column("employee_code", "Code"), Column("employee_name", "Employee"), Column("department", "Department"),
        Column("run", "Payroll run"), Column("status", "Status"),
        Column("working_days", "Working days", INT), Column("present_days", "Present", "hours"),
        Column("absent_days", "Absent", "hours"), Column("unpaid_leave_days", "Unpaid leave", "hours"),
        Column("overtime_hours", "Overtime hrs", "hours"),
        Column("salary_gross", "Gross salary", MONEY), Column("employer_contrib", "Employer contributions", MONEY),
        Column("reimbursements", "Reimbursements", MONEY), Column("tax", "Tax", MONEY),
        Column("employee_contrib", "Employee contributions", MONEY), Column("loan_recovery", "Loan / advance", MONEY),
        Column("other_deductions", "Other deductions", MONEY), Column("deductions", "Total deductions", MONEY),
        Column("net", "Net salary", MONEY),
    ]
    total = _totals(out, "employee_name")
    return ReportResult(key="payroll-register", title="Payroll Register", subtitle=month_label(year, month),
                        columns=cols, rows=out, totals=total, notes=_scope_note([]))


async def payroll_components(
    db: AsyncSession, tenant_id: uuid.UUID, year: int, month: int, *, department_id=None, branch_id=None,
) -> ReportResult:
    first, last = month_bounds(year, month)
    rows, lines = await _payslips(db, tenant_id, first, last, department_id=department_id, branch_id=branch_id)
    agg: dict[tuple[str, str], dict] = {}
    for slip, *_ in rows:
        for ln in lines.get(slip.id, []):
            code = ln.component_code or ""
            kind = ln.component_type.value
            if code.startswith(("LOAN_", "ADVANCE_")):
                code, name = code.split("_", 1)[0], code.split("_", 1)[0].title() + " recovery"
            else:
                name = ln.component_name
            a = agg.setdefault((kind, code), {"component": name, "type": kind, "code": code,
                                              "employees": set(), "amount": ZERO})
            a["employees"].add(slip.employee_id)
            a["amount"] += ln.amount or ZERO
    order = {"earning": 0, "employer_contribution": 1, "deduction": 2}
    out = [dict(a, employees=len(a["employees"])) for a in agg.values()]
    out.sort(key=lambda r: (order.get(r["type"], 9), -float(r["amount"])))
    for r in out:
        r["type"] = {"earning": "Earning", "employer_contribution": "Employer contribution",
                     "deduction": "Deduction"}.get(r["type"], r["type"])
    return ReportResult(
        key="payroll-components", title="Payroll Component Breakdown", subtitle=month_label(year, month),
        columns=[Column("component", "Component"), Column("code", "Code"), Column("type", "Type"),
                 Column("employees", "Employees", INT), Column("amount", "Amount", MONEY)],
        rows=out, notes=_scope_note([]),
    )


async def payroll_payment_status(
    db: AsyncSession, tenant_id: uuid.UUID, year: int, month: int, *, department_id=None, branch_id=None,
) -> ReportResult:
    first, last = month_bounds(year, month)
    rows, _lines = await _payslips(db, tenant_id, first, last, department_id=department_id, branch_id=branch_id)
    runs: dict[uuid.UUID, dict] = {}
    for slip, run, *_ in rows:
        r = runs.setdefault(run.id, {"run": run.name, "run_status": run.status.value, "pay_date": run.pay_date,
                                     "payslips": 0, "paid": 0, "pending": 0, "failed": 0,
                                     "paid_amount": ZERO, "pending_amount": ZERO})
        r["payslips"] += 1
        if slip.status == PayslipStatus.PAID:
            r["paid"] += 1
            r["paid_amount"] += slip.net_salary or ZERO
        else:
            r["pending"] += 1
            r["pending_amount"] += slip.net_salary or ZERO
    if runs:
        failed = await db.execute(
            select(PaymentBatch.payroll_run_id, PaymentBatchItem.payslip_id)
            .join(PaymentBatchItem, PaymentBatchItem.batch_id == PaymentBatch.id)
            .where(PaymentBatch.payroll_run_id.in_(list(runs)), PaymentBatchItem.status == PaymentItemStatus.FAILED,
                   PaymentBatchItem.is_deleted.is_(False)))
        for run_id, _slip_id in failed.all():
            runs[run_id]["failed"] += 1
    out = sorted(runs.values(), key=lambda r: (r["pay_date"], r["run"]))
    total = {"run": "Total", **{k: sum(r[k] for r in out) for k in ("payslips", "paid", "pending", "failed")},
             "paid_amount": sum((r["paid_amount"] for r in out), ZERO),
             "pending_amount": sum((r["pending_amount"] for r in out), ZERO)}
    return ReportResult(
        key="payroll-payment-status", title="Payroll Payment Status", subtitle=month_label(year, month),
        columns=[Column("run", "Payroll run"), Column("run_status", "Run status"), Column("pay_date", "Pay date", DATE),
                 Column("payslips", "Payslips", INT), Column("paid", "Paid", INT), Column("pending", "Pending", INT),
                 Column("failed", "Failed transfers", INT), Column("paid_amount", "Paid amount", MONEY),
                 Column("pending_amount", "Pending amount", MONEY)],
        rows=out, totals=total, notes=_scope_note([]),
    )
