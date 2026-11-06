"""Bank / mobile-wallet details (provider, account no, TID) on income and expense entries. Live Postgres, real HTTP."""
import pytest

from tests.test_finance_ledger_postgres import API, _h, _role_user, _setup, client, engine, org, other_org  # noqa: F401

pytestmark = pytest.mark.asyncio


def _t(accs, type="expense", acc="Bank", cat="Grocery", **kw):
    return {"type": type, "date": "2026-11-02", "amount": "500", "account_id": accs[acc], "category_id": accs[cat],
            "description": "milk", **kw}


async def test_default_accounts_have_a_kind_and_new_ones_can_choose(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    kinds = {a["name"]: a["money_kind"] for a in (await client.get(f"{API}/accounts", headers=h)).json()["items"]}
    assert kinds["Cash"] == "cash" and kinds["Bank"] == "bank" and kinds["Mobile Wallet"] == "wallet"
    r = await client.post(f"{API}/accounts", headers=h, json={"name": "Meezan Current", "type": "asset", "money_kind": "bank"})
    assert r.status_code == 201 and r.json()["money_kind"] == "bank"
    r = await client.post(f"{API}/accounts", headers=h, json={"name": "Misc", "type": "expense", "money_kind": "bank"})
    assert r.json()["money_kind"] is None                          # kinds only apply to money accounts


async def test_bank_details_are_saved_and_listed(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    r = await client.post(f"{API}/transactions", headers=h, json=_t(
        accs, payment_provider="Meezan Bank", payment_account_no=" 0101-123456 ", payment_tid="TID99887"))
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["payment_provider"] == "Meezan Bank" and row["payment_account_no"] == "0101-123456"
    assert row["payment_tid"] == "TID99887" and row["account_kind"] == "bank"
    listed = (await client.get(f"{API}/transactions", headers=h)).json()["items"][0]
    assert listed["payment_tid"] == "TID99887" and listed["payment_provider"] == "Meezan Bank"
    w = await client.post(f"{API}/transactions", headers=h, json=_t(
        accs, "income", "Mobile Wallet", "Client Payments", payment_provider="JazzCash", payment_account_no="0300-1234567", payment_tid="JC1"))
    assert w.status_code == 201 and w.json()["account_kind"] == "wallet"


async def test_details_are_optional_and_rejected_where_they_make_no_sense(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    plain = await client.post(f"{API}/transactions", headers=h, json=_t(accs))                       # bank, no details: fine
    assert plain.status_code == 201 and plain.json()["payment_provider"] is None
    cash = await client.post(f"{API}/transactions", headers=h, json=_t(accs, acc="Cash", payment_provider="HBL (Habib Bank)"))
    assert cash.status_code == 422
    no_name = await client.post(f"{API}/transactions", headers=h, json=_t(accs, payment_tid="T1"))
    assert no_name.status_code == 422 and "bank or wallet name" in no_name.text
    transfer = await client.post(f"{API}/transactions", headers=h, json={
        "type": "transfer", "date": "2026-11-03", "amount": "10", "account_id": accs["Bank"], "to_account_id": accs["Cash"],
        "payment_provider": "HBL (Habib Bank)"})
    assert transfer.status_code == 422
    assert (await client.get(f"{API}/transactions", headers=h)).json()["total"] == 1


async def test_provider_lists_defaults_plus_custom_and_stay_per_organization(client, org, other_org):
    await _setup(client, org)
    await _setup(client, other_org)
    h, ho = _h(org["owner"]), _h(other_org["owner"])
    banks = (await client.get(f"{API}/providers", headers=h, params={"kind": "bank"})).json()["items"]
    wallets = (await client.get(f"{API}/providers", headers=h, params={"kind": "wallet"})).json()["items"]
    assert "Meezan Bank" in banks and "HBL (Habib Bank)" in banks and "JazzCash" in wallets and "Easypaisa" in wallets
    n = len(banks)
    r = await client.post(f"{API}/providers", headers=h, json={"kind": "bank", "name": "  Khushhali   Microfinance Bank "})
    assert r.status_code == 201 and r.json()["items"][-1] == "Khushhali Microfinance Bank" and len(r.json()["items"]) == n + 1
    again = await client.post(f"{API}/providers", headers=h, json={"kind": "bank", "name": "khushhali microfinance bank"})
    assert len(again.json()["items"]) == n + 1                                                        # no duplicate by case
    dup_default = await client.post(f"{API}/providers", headers=h, json={"kind": "bank", "name": "meezan bank"})
    assert len(dup_default.json()["items"]) == n + 1
    assert "Khushhali Microfinance Bank" not in (await client.get(f"{API}/providers", headers=ho, params={"kind": "bank"})).json()["items"]
    assert (await client.get(f"{API}/providers", headers=h, params={"kind": "cash"})).status_code == 422


async def test_a_new_name_typed_on_an_entry_joins_the_list(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    r = await client.post(f"{API}/transactions", headers=h, json=_t(
        accs, "income", "Mobile Wallet", "Client Payments", payment_provider="Zong PayMax", payment_tid="Z1"))
    assert r.status_code == 201
    wallets = (await client.get(f"{API}/providers", headers=h, params={"kind": "wallet"})).json()["items"]
    assert wallets[-1] == "Zong PayMax"


async def test_viewer_can_read_providers_but_not_add(client, org, engine):
    await _setup(client, org)
    viewer = _h(await _role_user(engine, org, ["finance.view"], "Viewer"))
    assert (await client.get(f"{API}/providers", headers=viewer, params={"kind": "bank"})).status_code == 200
    assert (await client.post(f"{API}/providers", headers=viewer, json={"kind": "bank", "name": "X Bank"})).status_code == 403
