"""
One attendance state for the desktop app, the desktop widget and the website.

All three read the same server-side work session (GET /work-sessions/me/active)
and change it through the same endpoints, so the server has to be the single,
race-proof source of truth. These tests pin that down:

  * break start/end are serialised with check-in/out and idempotent -- a
    double-click, or two interfaces acting at the same instant, can never leave
    two open breaks or resurrect an ended session;
  * a check-in / check-out made through ANY path (the web's attendance API or
    the desktop's work-session API) is seen identically by every reader;
  * every response carries the server's clock, so timers share one time base.

Real HTTP stack + live Postgres (TEST_DATABASE_URL), like the other *_postgres
tests.
"""

import asyncio
import itertools
import os
import uuid
from datetime import UTC, date, datetime

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.employee import Employee
from app.models.organization import Organization
from app.models.user import User

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp"
)
pytestmark = pytest.mark.asyncio

PW_HASH = hash_password("x")   # hashed once; every test user shares it


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(DATABASE_URL)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def client(engine):
    async def _get_db():
        async with AsyncSession(engine, expire_on_commit=False, autoflush=False) as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _get_db
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


class Org:
    def __init__(self, engine):
        self.engine, self.org_id, self.n = engine, uuid.uuid4(), 0

    async def setup(self):
        async with AsyncSession(self.engine) as s:
            s.add(Organization(id=self.org_id, name="Sync Org", slug=f"sync-{self.org_id.hex[:8]}",
                               email=f"s-{self.org_id.hex[:8]}@example.com"))
            await s.commit()

    async def employee(self) -> dict:
        self.n += 1
        email = f"emp{self.n}-{uuid.uuid4().hex[:6]}@example.com"
        async with AsyncSession(self.engine, expire_on_commit=False) as s:
            u = User(organization_id=self.org_id, email=email, email_normalized=email, password_hash=PW_HASH,
                     first_name="Emp", last_name=str(self.n), is_active=True, is_email_verified=True)
            s.add(u)
            await s.flush()
            e = Employee(tenant_id=self.org_id, user_id=u.id, employee_code=f"S{self.n:04d}", date_of_joining=date(2026, 1, 1))
            s.add(e)
            await s.commit()
            return {"user": u.id, "employee": e.id,
                    "h": {"Authorization": f"Bearer {create_access_token(str(u.id))}"}}

    async def scalar(self, sql, **p):
        async with AsyncSession(self.engine) as s:
            return (await s.execute(text(sql), p)).scalar_one()

    async def teardown(self):
        async with AsyncSession(self.engine) as s:
            o = {"o": self.org_id}
            for sql in ("DELETE FROM break_records WHERE tenant_id = :o", "DELETE FROM attendance_punches WHERE tenant_id = :o",
                        "DELETE FROM work_sessions WHERE tenant_id = :o", "DELETE FROM attendance_records WHERE tenant_id = :o",
                        "DELETE FROM employees WHERE tenant_id = :o", "DELETE FROM users WHERE organization_id = :o",
                        "DELETE FROM organizations WHERE id = :o"):
                await s.execute(text(sql), o)
            await s.commit()


@pytest_asyncio.fixture
async def org(engine):
    o = Org(engine)
    await o.setup()
    yield o
    await o.teardown()


API = "/api/v1"
async def start(client, emp):            # desktop / widget check-in
    r = await client.post(f"{API}/work-sessions/start", headers=emp["h"]); assert r.status_code in (200, 201), r.text; return r.json()
async def active(client, emp):           # what ALL THREE interfaces read
    r = await client.get(f"{API}/work-sessions/me/active", headers=emp["h"]); assert r.status_code == 200, r.text; return r.json()
async def brk_start(client, emp, sid):   return await client.post(f"{API}/work-sessions/{sid}/break/start", json={}, headers=emp["h"])
async def brk_end(client, emp, sid):     return await client.post(f"{API}/work-sessions/{sid}/break/end", headers=emp["h"])


# ── Break start / end can't be doubled up ─────────────────────────────────────

class TestBreaksAreRaceProof:
    async def test_starting_a_break_twice_is_one_break_and_no_error(self, client, org):
        emp = await org.employee(); sid = (await start(client, emp))["id"]
        first, second = await brk_start(client, emp, sid), await brk_start(client, emp, sid)
        assert (first.status_code, second.status_code) == (200, 200), (first.text, second.text)
        assert second.json()["status"] == "on_break"
        assert second.json()["current_break_started_at"] == first.json()["current_break_started_at"]
        assert await org.scalar("SELECT count(*) FROM break_records WHERE work_session_id = :s", s=sid) == 1

    async def test_simultaneous_break_starts_create_exactly_one_break(self, client, org):
        """THE race: the widget and the website (or a double-click) at the same instant."""
        emp = await org.employee(); sid = (await start(client, emp))["id"]
        results = await asyncio.gather(*[brk_start(client, emp, sid) for _ in range(6)])
        assert [r.status_code for r in results] == [200] * 6, [r.text for r in results if r.status_code != 200]
        assert await org.scalar("SELECT count(*) FROM break_records WHERE work_session_id = :s", s=sid) == 1
        assert await org.scalar("SELECT count(*) FROM break_records WHERE work_session_id = :s AND ended_at IS NULL", s=sid) == 1

    async def test_ending_a_break_twice_is_fine_and_changes_nothing_the_second_time(self, client, org):
        emp = await org.employee(); sid = (await start(client, emp))["id"]
        await brk_start(client, emp, sid)
        first, second = await brk_end(client, emp, sid), await brk_end(client, emp, sid)
        assert (first.status_code, second.status_code) == (200, 200)
        assert second.json()["status"] == "active" and second.json()["current_break_started_at"] is None
        assert second.json()["total_break_seconds"] == first.json()["total_break_seconds"]
        assert await org.scalar("SELECT count(*) FROM break_records WHERE work_session_id = :s", s=sid) == 1

    async def test_simultaneous_break_ends_do_not_error(self, client, org):
        emp = await org.employee(); sid = (await start(client, emp))["id"]
        await brk_start(client, emp, sid)
        results = await asyncio.gather(*[brk_end(client, emp, sid) for _ in range(5)])
        assert [r.status_code for r in results] == [200] * 5
        assert (await active(client, emp))["status"] == "active"

    async def test_ending_a_break_that_was_never_started_reports_the_working_state(self, client, org):
        emp = await org.employee(); sid = (await start(client, emp))["id"]
        r = await brk_end(client, emp, sid)
        assert r.status_code == 200 and r.json()["status"] == "active"

    async def test_a_break_still_cannot_be_started_on_an_ended_session(self, client, org):
        emp = await org.employee(); sid = (await start(client, emp))["id"]
        assert (await client.post(f"{API}/work-sessions/{sid}/end", headers=emp["h"])).status_code == 200
        assert (await brk_start(client, emp, sid)).status_code == 409
        assert (await brk_end(client, emp, sid)).status_code == 409

    @pytest.mark.parametrize("round_", range(4))
    async def test_a_break_racing_a_check_out_never_revives_the_session(self, client, org, round_):
        """Break-start used to read 'active', lose to the check-out, then flip the
        ENDED session back to on_break."""
        emp = await org.employee(); sid = (await start(client, emp))["id"]
        await asyncio.gather(brk_start(client, emp, sid), client.post(f"{API}/work-sessions/{sid}/end", headers=emp["h"]))
        assert (await org.scalar("SELECT status::text FROM work_sessions WHERE id = :s", s=sid)).lower() == "ended"
        assert await org.scalar("SELECT count(*) FROM break_records WHERE work_session_id = :s AND ended_at IS NULL", s=sid) == 0
        assert await active(client, emp) is None

    async def test_the_database_itself_refuses_a_second_open_break(self, engine, client, org):
        from sqlalchemy.exc import IntegrityError
        emp = await org.employee(); sid = (await start(client, emp))["id"]
        await brk_start(client, emp, sid)
        async with AsyncSession(engine) as s:
            with pytest.raises(IntegrityError):
                await s.execute(text(
                    "INSERT INTO break_records (id, tenant_id, work_session_id, started_at, is_deleted, created_at, updated_at) "
                    "VALUES (:i, :t, :s, now(), false, now(), now())"), {"i": uuid.uuid4(), "t": org.org_id, "s": sid})
                await s.commit()


# ── Every reader sees the same state, whichever path changed it ───────────────

class TestEveryInterfaceSeesTheSameState:
    @pytest.mark.parametrize("check_in_via,check_out_via", list(itertools.product(("desktop", "web"), repeat=2)))
    async def test_check_in_break_check_out_from_any_mix_of_interfaces(self, client, org, check_in_via, check_out_via):
        emp = await org.employee()
        assert await active(client, emp) is None                                   # everyone starts offline

        if check_in_via == "desktop":                                              # desktop app / widget
            await start(client, emp)
        else:                                                                      # website
            r = await client.post(f"{API}/attendance/check-in", json={"method": "manual"}, headers=emp["h"]); assert r.status_code == 201, r.text
        s = await active(client, emp)
        assert s["status"] == "active"                                             # all three show WORKING

        assert (await brk_start(client, emp, s["id"])).status_code == 200
        assert (await active(client, emp))["status"] == "on_break"                 # all three show ON BREAK
        assert (await brk_end(client, emp, s["id"])).status_code == 200
        assert (await active(client, emp))["status"] == "active"                   # all three show WORKING again

        if check_out_via == "desktop":
            assert (await client.post(f"{API}/work-sessions/{s['id']}/end", headers=emp["h"])).status_code == 200
        else:
            assert (await client.post(f"{API}/attendance/check-out", json={}, headers=emp["h"])).status_code == 200
        assert await active(client, emp) is None                                   # all three show CHECKED OUT

        # The attendance record (what the Attendance page shows) has one day with both ends.
        assert await org.scalar(
            "SELECT count(*) FROM attendance_records WHERE employee_id = :e AND check_in IS NOT NULL AND check_out IS NOT NULL",
            e=emp["employee"]) == 1

    async def test_a_web_check_in_and_a_desktop_start_at_the_same_moment_make_one_session(self, client, org):
        emp = await org.employee()
        web = client.post(f"{API}/attendance/check-in", json={"method": "manual"}, headers=emp["h"])
        desk = client.post(f"{API}/work-sessions/start", headers=emp["h"])
        a, b = await asyncio.gather(web, desk)
        # Whoever arrives second finds the other's check-in: the desktop start just
        # returns that session, the web check-in says "already checked in" (400).
        # What must never happen is a 500, or two sessions / two punches.
        assert {a.status_code, b.status_code} <= {200, 201, 400}, (a.text, b.text)
        assert 200 in (a.status_code, b.status_code) or 201 in (a.status_code, b.status_code)
        assert await org.scalar("SELECT count(*) FROM work_sessions WHERE employee_id = :e AND lower(status::text) != 'ended'", e=emp["employee"]) == 1
        assert await org.scalar("SELECT count(*) FROM attendance_records WHERE employee_id = :e", e=emp["employee"]) == 1

    async def test_a_break_started_on_one_interface_is_seen_by_a_fresh_reader(self, client, org):
        """The 'open the widget later' case: it reads the server, not local state."""
        emp = await org.employee(); sid = (await start(client, emp))["id"]
        await brk_start(client, emp, sid)
        fresh = await active(client, emp)                      # a brand-new client with no local state
        assert fresh["status"] == "on_break" and fresh["current_break_started_at"]


# ── Timers share the server's time base ───────────────────────────────────────

class TestServerTime:
    async def test_every_session_response_carries_the_servers_clock(self, client, org):
        emp = await org.employee()
        before = datetime.now(UTC)
        s = await start(client, emp)
        for body in (s, await active(client, emp), (await brk_start(client, emp, s["id"])).json(), (await brk_end(client, emp, s["id"])).json()):
            server_time = datetime.fromisoformat(body["server_time"])
            assert abs((server_time - before).total_seconds()) < 30
