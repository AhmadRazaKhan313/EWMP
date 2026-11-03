"""The bell's "Flagged device activity" notification names the employee, not the machine."""
import asyncio
from datetime import datetime, timezone

import pytest
from tests._device_factory import make_device
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_devices_owner_postgres import _h, client, engine, org  # noqa: F401  (fixtures)
from app.core.security import create_device_enrollment_token

pytestmark = pytest.mark.asyncio


async def _enroll(client, org, host):
    return await make_device(org, host)


async def _upload(client, token):
    r = await client.post("/api/v1/devices/alerts/upload", headers={"Authorization": f"Bearer {token}"}, json={"alerts": [
        {"alert_type": "flagged_browsing", "matched_term": "facebook.com", "detail": "facebook.com",
         "occurred_at": datetime.now(timezone.utc).isoformat()}]})
    assert r.status_code == 200 and r.json()["created"] == 1, r.text


async def _bodies(engine, org):
    async with AsyncSession(engine) as s:
        rows = (await s.execute(text(
            "SELECT body FROM notifications WHERE tenant_id = :o AND type = 'device_alert' ORDER BY created_at"),
            {"o": org["org"]})).all()
    return [r[0] for r in rows]


@pytest_asyncio.fixture(autouse=True)
async def _cleanup(engine, org):
    yield
    async with AsyncSession(engine) as s:
        await s.execute(text("DELETE FROM notifications WHERE tenant_id = :o"), {"o": org["org"]})
        await s.commit()


async def test_notification_names_the_employee(client, org, engine):
    dev = await _enroll(client, org, "DESKTOP-I0292P0")
    await client.post(f"/api/v1/devices/{dev['device_id']}/assign", json={"employee_id": str(org["emp"])}, headers=_h(org))
    await _upload(client, dev["agent_token"])
    bodies = await _bodies(engine, org)
    assert bodies and all(b.startswith("Sara Khan (EMP-0042) triggered 1 activity alert(s).") for b in bodies)
    assert not any("DESKTOP-I0292P0" in b for b in bodies)


async def test_unassigned_device_is_not_named_by_hostname(client, org, engine):
    dev = await _enroll(client, org, "DESKTOP-I0292P0")
    await _upload(client, dev["agent_token"])
    bodies = await _bodies(engine, org)
    assert bodies and all(b.startswith("An unassigned device triggered") for b in bodies)


async def test_relabel_script_fixes_old_notifications(client, org, engine):
    dev = await _enroll(client, org, "DESKTOP-I0292P0")
    await _upload(client, dev["agent_token"])  # unassigned -> "An unassigned device ..."
    async with AsyncSession(engine) as s:  # simulate a notification written by the old code
        await s.execute(text("UPDATE notifications SET body = 'DESKTOP-I0292P0 triggered 1 activity alert(s). Review in Device Management.' "
                             "WHERE tenant_id = :o AND type = 'device_alert'"), {"o": org["org"]})
        await s.commit()
    await client.post(f"/api/v1/devices/{dev['device_id']}/assign", json={"employee_id": str(org["emp"])}, headers=_h(org))
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location("relabel", pathlib.Path(__file__).parents[1] / "relabel_device_notifications.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    await mod.main()
    bodies = await _bodies(engine, org)
    assert bodies and all(b.startswith("Sara Khan (EMP-0042) triggered 1 activity alert(s).") for b in bodies)
