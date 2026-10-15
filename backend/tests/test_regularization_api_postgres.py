"""
Tests for audit finding M-7 (part B): the regularization API, and HR's manual
attendance entry going through punches.

Before: a regularization service and table existed but no API — after the
sweep marked a forgotten check-out MISSED_PUNCH (0 hours) nobody could get
the hours back. HR's manual POST /attendance wrote the day's columns
directly, so the next recalculation from punches silently wiped it out.

The last class carries over, one for one, the six behaviours of HR manual
entry the old fake-session tests pinned down (times saved, HH:MM:SS, bad
input, check-out before check-in, same row on a second edit, partial edit).

Asia/Karachi = UTC+5. Live Postgres via TEST_DATABASE_URL.
"""

import os
import uuid
from datetime import UTC, date, datetime, time, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.attendance import (
    AttendancePunch, AttendanceRecord, AttendanceRegularization, AttendanceStatus, Shift,
)
from app.models.employee import Employee, EmploymentStatus, EmploymentType
from app.models.organization import Organization
from app.models.rbac import Permission, Role
from app.models.user import User
from app.services.attendance_punches import open_punch, recalculate_from_punches
from app.services.attendance_sync import sweep_stale_attendance

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp",
)

pytestmark = pytest.mark.asyncio

REG = "/api/v1/attendance/regularizations"
DAY = date(2026, 9, 17)


def pkt(d: int, hh: int, mm: int = 0, ss: int = 0) -> datetime:
    return datetime(2026, 9, d, hh, mm, ss, tzinfo=UTC) - timedelta(hours=5)


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


async def _permission(s, codename):
    perm = (await s.execute(select(Permission).where(Permission.codename == codename))).scalar_one_or_none()
    if perm is None:
        resource, action = codename.split(".", 1)
        perm = Permission(resource=resource, action=action, codename=codename, label=codename, category=resource)
        s.add(perm)
        await s.flush()
    return perm


async def _make_org(engine, label):
    org_id = uuid.uuid4()
    ids = {"org": org_id}
    async with AsyncSession(engine, expire_on_commit=False) as s:
        s.add(Organization(id=org_id, name=f"Reg {label}", slug=f"reg-{label}-{org_id.hex[:8]}",
                           email=f"reg-{org_id.hex[:8]}@example.com", timezone="Asia/Karachi"))
        await s.flush()
        hr_role = Role(organization_id=org_id, name="HR", slug="hr",
                       permissions=[await _permission(s, "attendance.regularize")])
        day = Shift(tenant_id=org_id, name="Day", code=f"D{org_id.hex[:4]}", start_time=time(9, 0),
                    end_time=time(18, 0), weekly_hours=45, late_grace_minutes=10)
        night = Shift(tenant_id=org_id, name="Night", code=f"N{org_id.hex[:4]}", start_time=time(22, 0),
                      end_time=time(6, 0), weekly_hours=45, is_overnight=True)
        s.add_all([hr_role, day, night])
        await s.flush()
        for name, roles, shift in (("hr", [hr_role], day), ("emp", [], day), ("nightemp", [], night)):
            email = f"{name}-{uuid.uuid4().hex[:8]}@example.com"
            u = User(organization_id=org_id, email=email, email_normalized=email, password_hash="x",
                     first_name=name, last_name="T", is_active=True, is_email_verified=True, roles=roles)
            s.add(u)
            await s.flush()
            e = Employee(tenant_id=org_id, user_id=u.id, employee_code=f"E-{uuid.uuid4().hex[:6]}",
                         employment_type=EmploymentType.FULL_TIME, employment_status=EmploymentStatus.ACTIVE,
                         date_of_joining=date(2026, 1, 1), default_shift_id=shift.id)
            s.add(e)
            await s.flush()
            ids[name], ids[f"{name}_emp"], ids[f"{name}_shift"] = u.id, e.id, shift.id
        await s.commit()
    return ids


async def _drop_org(engine, org_id):
    async with AsyncSession(engine) as s:
        for model in (AttendanceRegularization, AttendancePunch, AttendanceRecord, Employee, Shift):
            await s.execute(delete(model).where(model.tenant_id == org_id))
        await s.execute(delete(User).where(User.organization_id == org_id))
        await s.execute(delete(Role).where(Role.organization_id == org_id))
        await s.execute(delete(Organization).where(Organization.id == org_id))
        await s.commit()


@pytest_asyncio.fixture
async def org(engine):
    ids = await _make_org(engine, "a")
    yield ids
    await _drop_org(engine, ids["org"])


def H(org, who) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(org[who]))}"}


async def forgotten_checkout(engine, org, who="emp", start=None):
    """Checked in, never checked out, swept: forced punch, MISSED_PUNCH, 0h."""
    start = start or pkt(17, 9)
    async with AsyncSession(engine, expire_on_commit=False) as s:
        punch, _ = await open_punch(s, org["org"], org[f"{who}_emp"], at=start, shift_id=org[f"{who}_shift"])
        await s.commit()
    async with AsyncSession(engine) as s:
        await sweep_stale_attendance(s, now=start + timedelta(days=2))
        await s.commit()
    return punch.id


async def day_of(engine, employee_id, on=DAY) -> AttendanceRecord:
    async with AsyncSession(engine) as s:
        return (await s.execute(select(AttendanceRecord).where(
            AttendanceRecord.employee_id == employee_id, AttendanceRecord.date == on))).scalar_one()


async def punches_of(engine, employee_id):
    async with AsyncSession(engine) as s:
        return (await s.execute(select(AttendancePunch).where(AttendancePunch.employee_id == employee_id)
                                .order_by(AttendancePunch.punch_in))).scalars().all()


class TestEmployeeAsksManagerApproves:
    async def test_forgotten_check_out_gets_its_hours_back_only_after_approval(self, client, engine, org):
        punch_id = await forgotten_checkout(engine, org)
        assert (await day_of(engine, org["emp_emp"])).status == AttendanceStatus.MISSED_PUNCH

        r = await client.post(REG, headers=H(org, "emp"), json={
            "date": "2026-09-17", "punch_id": str(punch_id), "check_out": "18:05", "reason": "Forgot to check out"})
        assert r.status_code == 201, r.text
        assert r.json()["status"] == "pending"
        # An unapproved claim must not move payable hours.
        day = await day_of(engine, org["emp_emp"])
        assert (day.status, day.total_minutes) == (AttendanceStatus.MISSED_PUNCH, 0)

        a = await client.post(f"{REG}/{r.json()['id']}/approve", headers=H(org, "hr"), json={"comments": "ok"})
        assert a.status_code == 200, a.text
        assert a.json()["status"] == "approved"
        day = await day_of(engine, org["emp_emp"])
        assert day.total_minutes == 9 * 60 + 5
        assert day.status == AttendanceStatus.PRESENT and day.is_regularized
        punch = (await punches_of(engine, org["emp_emp"]))[0]
        assert punch.punch_out == pkt(17, 18, 5)
        assert punch.is_forced_checkout, "the forced flag stays for audit"

    async def test_rejected_request_changes_nothing(self, client, engine, org):
        punch_id = await forgotten_checkout(engine, org)
        r = await client.post(REG, headers=H(org, "emp"), json={
            "date": "2026-09-17", "punch_id": str(punch_id), "check_out": "18:00", "reason": "x" * 5})
        rej = await client.post(f"{REG}/{r.json()['id']}/reject", headers=H(org, "hr"), json={"comments": "no"})
        assert rej.json()["status"] == "rejected"
        assert (await day_of(engine, org["emp_emp"])).total_minutes == 0

    async def test_employee_can_withdraw_and_it_can_no_longer_be_approved(self, client, engine, org):
        punch_id = await forgotten_checkout(engine, org)
        r = await client.post(REG, headers=H(org, "emp"), json={
            "date": "2026-09-17", "punch_id": str(punch_id), "check_out": "18:00", "reason": "oops"})
        assert (await client.post(f"{REG}/{r.json()['id']}/cancel", headers=H(org, "emp"))).json()["status"] == "cancelled"
        assert (await client.post(f"{REG}/{r.json()['id']}/approve", headers=H(org, "hr"))).status_code == 409

    async def test_nobody_approves_their_own_correction(self, client, engine, org):
        punch_id = await forgotten_checkout(engine, org, who="hr")
        r = await client.post(REG, headers=H(org, "hr"), json={
            "date": "2026-09-17", "punch_id": str(punch_id), "check_out": "18:00", "reason": "mine"})
        assert (await client.post(f"{REG}/{r.json()['id']}/approve", headers=H(org, "hr"))).status_code == 403

    async def test_plain_employee_cannot_approve(self, client, engine, org):
        punch_id = await forgotten_checkout(engine, org)
        r = await client.post(REG, headers=H(org, "emp"), json={
            "date": "2026-09-17", "punch_id": str(punch_id), "check_out": "18:00", "reason": "mine"})
        assert (await client.post(f"{REG}/{r.json()['id']}/approve", headers=H(org, "emp"))).status_code == 403

    async def test_one_pending_request_per_day(self, client, engine, org):
        punch_id = await forgotten_checkout(engine, org)
        body = {"date": "2026-09-17", "punch_id": str(punch_id), "check_out": "18:00", "reason": "first"}
        assert (await client.post(REG, headers=H(org, "emp"), json=body)).status_code == 201
        assert (await client.post(REG, headers=H(org, "emp"), json=body)).status_code == 409

    async def test_a_running_punch_or_a_missing_day_cannot_be_regularized(self, client, engine, org):
        async with AsyncSession(engine, expire_on_commit=False) as s:
            punch, _ = await open_punch(s, org["org"], org["emp_emp"], at=pkt(17, 9))
            await s.commit()
        running = await client.post(REG, headers=H(org, "emp"), json={
            "date": "2026-09-17", "punch_id": str(punch.id), "check_out": "18:00", "reason": "early"})
        assert running.status_code == 409
        missing = await client.post(REG, headers=H(org, "emp"), json={
            "date": "2026-09-10", "check_in": "09:00", "check_out": "18:00", "reason": "no day"})
        assert missing.status_code == 404

    async def test_adding_a_missing_punch_and_overlaps_are_refused(self, client, engine, org):
        forced_id = await forgotten_checkout(engine, org)
        ok = await client.post(REG, headers=H(org, "emp"), json={
            "date": "2026-09-17", "check_in": "19:00", "check_out": "21:00", "reason": "came back"})
        assert (await client.post(f"{REG}/{ok.json()['id']}/approve", headers=H(org, "hr"))).status_code == 200
        assert len(await punches_of(engine, org["emp_emp"])) == 2

        clash = await client.post(REG, headers=H(org, "emp"), json={
            "date": "2026-09-17", "check_in": "20:00", "check_out": "22:00", "reason": "overlap"})
        assert (await client.post(f"{REG}/{clash.json()['id']}/approve", headers=H(org, "hr"))).status_code == 409
        # The failed approval leaves it pending; the manager rejects it.
        await client.post(f"{REG}/{clash.json()['id']}/reject", headers=H(org, "hr"))

        # …and the forced punch can't now be "corrected" to run into it either.
        late = await client.post(REG, headers=H(org, "emp"), json={
            "date": "2026-09-17", "punch_id": str(forced_id), "check_out": "20:00", "reason": "left late"})
        assert (await client.post(f"{REG}/{late.json()['id']}/approve", headers=H(org, "hr"))).status_code == 409

    async def test_overnight_shift_check_out_is_next_morning(self, client, engine, org):
        punch_id = await forgotten_checkout(engine, org, who="nightemp", start=pkt(17, 22))
        r = await client.post(REG, headers=H(org, "nightemp"), json={
            "date": "2026-09-17", "punch_id": str(punch_id), "check_out": "06:00", "reason": "night"})
        assert r.status_code == 201, r.text
        await client.post(f"{REG}/{r.json()['id']}/approve", headers=H(org, "hr"))
        assert (await day_of(engine, org["nightemp_emp"])).total_minutes == 8 * 60

    async def test_day_shift_check_out_before_check_in_is_rejected(self, client, engine, org):
        punch_id = await forgotten_checkout(engine, org)
        r = await client.post(REG, headers=H(org, "emp"), json={
            "date": "2026-09-17", "punch_id": str(punch_id), "check_out": "08:00", "reason": "typo"})
        assert r.status_code == 400

    async def test_listing_is_own_for_employees_and_all_for_managers(self, client, engine, org):
        p1 = await forgotten_checkout(engine, org)
        p2 = await forgotten_checkout(engine, org, who="hr")
        await client.post(REG, headers=H(org, "emp"), json={"date": "2026-09-17", "punch_id": str(p1), "check_out": "18:00", "reason": "a b"})
        await client.post(REG, headers=H(org, "hr"), json={"date": "2026-09-17", "punch_id": str(p2), "check_out": "18:00", "reason": "c d"})
        assert (await client.get(REG, headers=H(org, "emp"))).json()["total"] == 1
        assert (await client.get(REG, headers=H(org, "hr"))).json()["total"] == 2
        assert (await client.get(REG, headers=H(org, "hr"), params={"status": "pending"})).json()["total"] == 2


def manual(org, **params):
    base = {"employee_id": str(org["emp_emp"]), "date": "2026-09-17"}
    base.update(params)
    return base


class TestHrManualEntry:
    """The six behaviours the old tests pinned down, now against real punches."""

    async def test_check_in_and_check_out_times_are_actually_saved(self, client, engine, org):
        r = await client.post("/api/v1/attendance", headers=H(org, "hr"),
                              params=manual(org, check_in="09:15", check_out="17:45"))
        assert r.status_code == 201, r.text
        assert r.json()["created"] is True
        day = await day_of(engine, org["emp_emp"])
        assert (day.check_in, day.check_out) == (pkt(17, 9, 15), pkt(17, 17, 45))
        assert day.total_minutes == 8 * 60 + 30

    async def test_accepts_hh_mm_ss_format_too(self, client, engine, org):
        await client.post("/api/v1/attendance", headers=H(org, "hr"),
                          params=manual(org, check_in="09:15:30", check_out="17:00"))
        assert (await day_of(engine, org["emp_emp"])).check_in == pkt(17, 9, 15, 30)

    async def test_rejects_malformed_time_string(self, client, org):
        r = await client.post("/api/v1/attendance", headers=H(org, "hr"),
                              params=manual(org, check_in="9am", check_out="17:00"))
        assert r.status_code == 400

    async def test_rejects_check_out_before_check_in(self, client, org):
        r = await client.post("/api/v1/attendance", headers=H(org, "hr"),
                              params=manual(org, check_in="17:00", check_out="09:00"))
        assert r.status_code == 400

    async def test_regularizing_twice_updates_the_same_day_not_a_new_one(self, client, engine, org):
        first = await client.post("/api/v1/attendance", headers=H(org, "hr"),
                                  params=manual(org, check_in="09:00", check_out="17:00"))
        second = await client.post("/api/v1/attendance", headers=H(org, "hr"),
                                   params=manual(org, check_in="09:30", check_out="18:00"))
        assert second.json() == {"id": first.json()["id"], "created": False}
        assert len(await punches_of(engine, org["emp_emp"])) == 1
        day = await day_of(engine, org["emp_emp"])
        assert (day.check_in, day.check_out) == (pkt(17, 9, 30), pkt(17, 18))

    async def test_partial_update_preserves_the_other_existing_time(self, client, engine, org):
        await forgotten_checkout(engine, org)  # 09:00 in, never out
        r = await client.post("/api/v1/attendance", headers=H(org, "hr"), params=manual(org, check_out="17:30"))
        assert r.status_code == 201, r.text
        day = await day_of(engine, org["emp_emp"])
        assert day.check_in == pkt(17, 9)            # untouched
        assert day.check_out == pkt(17, 17, 30)      # updated
        assert day.status == AttendanceStatus.PRESENT and day.total_minutes == 8 * 60 + 30


class TestHrEntrySurvivesRecalculation:
    async def test_hr_fix_is_not_wiped_by_the_next_recalculation(self, client, engine, org):
        """THE bug: HR wrote the day's columns; the next rebuild from punches
        (a later check-in, the sweep, a regularization) erased it."""
        await forgotten_checkout(engine, org)
        await client.post("/api/v1/attendance", headers=H(org, "hr"), params=manual(org, check_out="17:30"))
        async with AsyncSession(engine) as s:
            day = (await s.execute(select(AttendanceRecord).where(AttendanceRecord.employee_id == org["emp_emp"]))).scalar_one()
            await recalculate_from_punches(s, day)
            await s.commit()
        day = await day_of(engine, org["emp_emp"])
        assert day.check_out == pkt(17, 17, 30) and day.total_minutes == 8 * 60 + 30

    async def test_each_hr_change_leaves_an_approved_audit_entry(self, client, engine, org):
        await client.post("/api/v1/attendance", headers=H(org, "hr"), params=manual(org, check_in="09:00", check_out="17:00"))
        async with AsyncSession(engine) as s:
            regs = (await s.execute(select(AttendanceRegularization).where(
                AttendanceRegularization.employee_id == org["emp_emp"]))).scalars().all()
        assert len(regs) == 1
        assert regs[0].status.value == "approved" and regs[0].reason == "Recorded by HR"
        assert regs[0].requested_by_id == org["hr"] == regs[0].reviewed_by_id

    async def test_status_only_entry_sets_the_day(self, client, engine, org):
        r = await client.post("/api/v1/attendance", headers=H(org, "hr"),
                              params=manual(org, attendance_status="on_leave"))
        assert r.status_code == 201, r.text
        assert (await day_of(engine, org["emp_emp"])).status == AttendanceStatus.ON_LEAVE

    async def test_a_day_with_several_punches_must_be_fixed_punch_by_punch(self, client, engine, org):
        await client.post("/api/v1/attendance", headers=H(org, "hr"), params=manual(org, check_in="09:00", check_out="12:00"))
        ok = await client.post(REG, headers=H(org, "hr"), json={
            "date": "2026-09-17", "employee_id": str(org["emp_emp"]),
            "check_in": "13:00", "check_out": "17:00", "reason": "afternoon"})
        # HR approves; HR is not the employee whose day this is.
        assert (await client.post(f"{REG}/{ok.json()['id']}/approve", headers=H(org, "hr"))).status_code == 200
        r = await client.post("/api/v1/attendance", headers=H(org, "hr"), params=manual(org, check_out="18:00"))
        assert r.status_code == 409

    async def test_employee_of_another_organisation_is_not_found(self, client, engine, org):
        other = await _make_org(engine, "b")
        try:
            r = await client.post("/api/v1/attendance", headers=H(org, "hr"),
                                  params={"employee_id": str(other["emp_emp"]), "date": "2026-09-17",
                                          "check_in": "09:00", "check_out": "17:00"})
            assert r.status_code == 404
            async with AsyncSession(engine) as s:
                assert (await s.execute(select(func.count()).select_from(AttendanceRecord).where(
                    AttendanceRecord.tenant_id == other["org"]))).scalar_one() == 0
        finally:
            await _drop_org(engine, other["org"])
