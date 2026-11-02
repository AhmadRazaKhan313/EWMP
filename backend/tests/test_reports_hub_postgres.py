"""Reports hub: payroll numbers, which runs count, permissions and the Excel file. Live Postgres."""
import io
import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from openpyxl import load_workbook
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.reports.router import router as reports_router
from app.core.config import settings
from app.core.security import create_access_token
from app.main import app
from app.models.payroll import (
    ComponentType, Payslip, PayslipLine, PayslipStatus, PayrollRun, PayrollRunStatus,
)
from tests.test_devices_owner_postgres import _h, client, engine, org  # noqa: F401  (fixtures)

pytestmark = pytest.mark.asyncio

if not any(getattr(r, "path", "").endswith("/reports/catalog") for r in app.routes):
    app.include_router(reports_router, prefix=settings.API_V1_PREFIX)

P = settings.API_V1_PREFIX + "/reports"
E, D = ComponentType.EARNING, ComponentType.DEDUCTION


def _lines(slip_id, org_id, rows):
    return [PayslipLine(tenant_id=org_id, payslip_id=slip_id, component_code=c, component_name=n,
                        component_type=t, amount=Decimal(a)) for c, n, t, a in rows]


@pytest_asyncio.fixture
async def payroll(engine, org):
    o, emp = org["org"], org["emp"]
    ids = []
    async with AsyncSession(engine, expire_on_commit=False) as s:
        async def run(name, status, start=date(2026, 10, 1)):
            r = PayrollRun(tenant_id=o, name=name, period_start=start, period_end=date(start.year, start.month, 28),
                           pay_date=date(start.year, start.month, 28), status=status)
            s.add(r); await s.flush(); ids.append(r.id); return r

        async def slip(r, status, gross, ded, net, rows):
            p = Payslip(tenant_id=o, payroll_run_id=r.id, employee_id=emp, status=status,
                        gross_salary=Decimal(gross), total_deductions=Decimal(ded), net_salary=Decimal(net))
            s.add(p); await s.flush()
            s.add_all(_lines(p.id, o, rows))

        full = [("BASIC", "Basic", E, "100000"), ("REIMB_TRAVEL", "Reimbursement: Travel", E, "8000"),
                ("PF_ER", "Pension (Employer)", ComponentType.EMPLOYER_CONTRIBUTION, "5000"),
                ("TAX", "Income Tax", D, "10000"), ("PF_EE", "Pension (Employee)", D, "3000"),
                ("LOAN_ab12cd34", "Loan", D, "2000")]
        await slip(await run("Oct 2026", PayrollRunStatus.LOCKED), PayslipStatus.PAID, "108000", "15000", "93000", full)
        # none of these may be counted:
        await slip(await run("Oct draft", PayrollRunStatus.DRAFT), PayslipStatus.GENERATED, "999999", "0", "999999",
                   [("BASIC", "Basic", E, "999999")])
        await slip(await run("Oct cancelled", PayrollRunStatus.CANCELLED), PayslipStatus.GENERATED, "888888", "0", "888888",
                   [("BASIC", "Basic", E, "888888")])
        await slip(await run("Oct reversed", PayrollRunStatus.PAID), PayslipStatus.REVERSED, "777777", "0", "777777",
                   [("BASIC", "Basic", E, "777777")])
        # September, counted: shows in the trend
        await slip(await run("Sep 2026", PayrollRunStatus.APPROVED, date(2026, 9, 1)), PayslipStatus.GENERATED,
                   "50000", "5000", "45000", [("BASIC", "Basic", E, "50000"), ("TAX", "Income Tax", D, "5000")])
        await s.commit()
    yield
    async with AsyncSession(engine) as s:
        await s.execute(text("DELETE FROM payslip_lines WHERE tenant_id = :o"), {"o": o})
        await s.execute(text("DELETE FROM payslips WHERE tenant_id = :o"), {"o": o})
        await s.execute(text("DELETE FROM payroll_runs WHERE tenant_id = :o"), {"o": o})
        await s.commit()


async def test_expenses_split_salary_cost_and_reimbursements(client, org, payroll):
    r = await client.get(f"{P}/hub/payroll-expenses?month=2026-10", headers=_h(org))
    assert r.status_code == 200, r.text
    body = r.json()
    rows = {x["month"]: x for x in body["rows"]}
    assert len(body["rows"]) == 12
    oct_ = rows["October 2026"]
    assert oct_["salary_gross"] == 100000 and oct_["employer_contrib"] == 5000
    assert oct_["salary_cost"] == 105000
    assert oct_["reimbursements"] == 8000
    assert oct_["total_paid_out"] == 113000
    assert oct_["deductions"] == 15000 and oct_["net"] == 93000
    assert oct_["employees"] == 1 and oct_["runs"] == 1  # draft, cancelled, reversed ignored
    assert rows["September 2026"]["salary_cost"] == 50000
    assert body["totals"]["salary_cost"] == 155000
    tiles = {t["label"]: t["value"] for t in body["summary"]}
    assert tiles["Total paid out"] == 113000


async def test_department_cost_and_components(client, org, payroll):
    d = (await client.get(f"{P}/hub/payroll-department-cost?month=2026-10", headers=_h(org))).json()
    assert [r["department"] for r in d["rows"]] == ["Engineering"]
    assert d["rows"][0]["total_paid_out"] == 113000 and d["totals"]["employees"] == 1
    c = (await client.get(f"{P}/hub/payroll-components?month=2026-10", headers=_h(org))).json()
    amounts = {(r["code"]): r["amount"] for r in c["rows"]}
    assert amounts["BASIC"] == 100000 and amounts["TAX"] == 10000 and amounts["LOAN"] == 2000
    assert "999999" not in str(c)


async def test_register_row_and_search(client, org, payroll):
    r = (await client.get(f"{P}/hub/payroll-register?month=2026-10", headers=_h(org))).json()
    row = r["rows"][0]
    assert row["employee_name"] == "Sara Khan" and row["employee_code"] == "EMP-0042"
    assert row["tax"] == 10000 and row["employee_contrib"] == 3000 and row["loan_recovery"] == 2000
    none = (await client.get(f"{P}/hub/payroll-register?month=2026-10&search=zzz", headers=_h(org))).json()
    assert none["rows"] == []


async def test_payment_status(client, org, payroll):
    r = (await client.get(f"{P}/hub/payroll-payment-status?month=2026-10", headers=_h(org))).json()
    assert r["rows"][0]["paid"] == 1 and r["rows"][0]["paid_amount"] == 93000
    assert r["totals"]["payslips"] == 1


async def test_xlsx_is_a_designed_sheet(client, org, payroll):
    r = await client.get(f"{P}/hub/payroll-expenses/xlsx?month=2026-10", headers=_h(org))
    assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"]
    assert r.headers["content-disposition"].endswith("payroll-expenses-2026-10.xlsx")
    ws = load_workbook(io.BytesIO(r.content)).active
    assert ws["A1"].value == "Dev Org" and ws["A2"].value == "Monthly Payroll Expenses"
    header_row = next(i for i in range(1, 15) if ws.cell(i, 1).value == "Month")
    assert ws.freeze_panes == f"A{header_row + 1}"
    headers = [c.value for c in ws[header_row]]
    assert "Total paid out" in headers
    col = headers.index("Total paid out") + 1
    cell = next(ws.cell(i, col) for i in range(header_row + 1, header_row + 14) if ws.cell(i, 1).value == "October 2026")
    assert cell.value == 113000 and "#,##0.00" in cell.number_format
    assert ws.cell(header_row + 13, 1).value == "Total"


async def test_csv_download(client, org, payroll):
    r = await client.get(f"{P}/hub/payroll-register/csv?month=2026-10", headers=_h(org))
    assert r.status_code == 200 and r.text.splitlines()[0].startswith("Code,Employee")
    assert "Sara Khan" in r.text


async def test_catalog_lists_payroll_for_owner_and_hides_it_without_permission(client, org, engine, payroll):
    cat = (await client.get(f"{P}/catalog", headers=_h(org))).json()
    keys = {i["key"] for i in cat["items"]}
    assert {"payroll-expenses", "payroll-register", "attendance-monthly"} <= keys and cat["can_export"]
    async with AsyncSession(engine) as s:
        uid = (await s.execute(text("SELECT user_id FROM employees WHERE id = :e"), {"e": org["emp"]})).scalar()
    worker = {"Authorization": f"Bearer {create_access_token(str(uid))}"}
    r = await client.get(f"{P}/hub/payroll-expenses?month=2026-10", headers=worker)
    assert r.status_code == 403
    assert (await client.get(f"{P}/hub/payroll-expenses/xlsx?month=2026-10", headers=worker)).status_code == 403


async def test_bad_input(client, org):
    assert (await client.get(f"{P}/hub/nope", headers=_h(org))).status_code == 404
    assert (await client.get(f"{P}/hub/payroll-expenses?month=2026-13", headers=_h(org))).status_code == 422
