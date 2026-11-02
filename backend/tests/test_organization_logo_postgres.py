"""
O-01: organization logo. Real bytes decide the type, SVG is only accepted when
it is plain and self-contained, a replaced logo leaves no stale file behind,
only settings.manage may change it, and the payslip PDF embeds it.
Live Postgres, real HTTP, a throwaway local storage directory.
"""

import os
import uuid
from datetime import date, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.organization import Organization
from app.models.rbac import Role
from app.models.user import User
from app.workers.tasks import email as email_tasks

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp"
)
pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _no_email(monkeypatch):
    monkeypatch.setattr(email_tasks.send_verification_email, "delay", lambda to, token: None)


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


async def _make_org(engine) -> dict:
    org_id = uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        s.add(Organization(id=org_id, name="Shift Org", slug=f"shift-{org_id.hex[:8]}",
                           email=f"s-{org_id.hex[:8]}@example.com", timezone="Asia/Karachi"))
        await s.flush()
        staff = Role(organization_id=org_id, name="Staff", slug="staff", permissions=[])
        s.add(staff)
        email = f"owner-{uuid.uuid4().hex[:8]}@example.com"
        owner = User(organization_id=org_id, email=email, email_normalized=email,
                     password_hash=hash_password("x"), first_name="Owner", last_name="Test",
                     is_active=True, is_email_verified=True)
        s.add(owner)
        await s.flush()
        (await s.get(Organization, org_id)).owner_id = owner.id
        ids = {"org": org_id, "owner": owner.id, "role": staff.id}
        await s.commit()
    return ids


async def _drop_org(engine, ids):
    async with AsyncSession(engine) as s:
        o = {"o": ids["org"]}
        for sql in (
            "DELETE FROM auth_refresh_tokens WHERE user_id IN (SELECT id FROM users WHERE organization_id = :o)",
            "DELETE FROM attendance_records WHERE tenant_id = :o",
            "DELETE FROM employees WHERE tenant_id = :o",
            "DELETE FROM holidays WHERE tenant_id = :o",
            "DELETE FROM applicants WHERE tenant_id = :o",
            "DELETE FROM job_postings WHERE tenant_id = :o",
            "DELETE FROM goals WHERE tenant_id = :o",
            "DELETE FROM performance_reviews WHERE tenant_id = :o",
            "DELETE FROM support_tickets WHERE tenant_id = :o",
            "DELETE FROM shifts WHERE tenant_id = :o",
            "UPDATE organizations SET owner_id = NULL WHERE id = :o",
            "DELETE FROM users WHERE organization_id = :o",
            "DELETE FROM roles WHERE organization_id = :o",
            "DELETE FROM organizations WHERE id = :o",
        ):
            await s.execute(text(sql), o)
        await s.commit()


@pytest_asyncio.fixture
async def org(engine):
    ids = await _make_org(engine)
    yield ids
    await _drop_org(engine, ids)


@pytest_asyncio.fixture
async def other_org(engine):
    ids = await _make_org(engine)
    yield ids
    await _drop_org(engine, ids)


def _h(user_id) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


async def _shift(client, org, name="Day", start="09:00", end="18:00", **kw) -> str:
    r = await client.post("/api/v1/shifts", headers=_h(org["owner"]),
                          json={"name": name, "code": name[:3].upper(), "start_time": start, "end_time": end, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _employee(client, org, name) -> dict:
    r = await client.post("/api/v1/employees", headers=_h(org["owner"]), json={"first_name": name, "last_name": "Hire", "email": f"{name.lower()}-{uuid.uuid4().hex[:6]}@example.com", "date_of_joining": "2026-01-01", "role_id": str(org["role"])})
    assert r.status_code == 201, r.text
    return {"id": r.json()["id"]}


async def _role_user(engine, org, perms, name="Hr"):
    """A user in `org` whose role grants exactly `perms`."""
    async with AsyncSession(engine, expire_on_commit=False) as s:
        from sqlalchemy import select
        from app.models.rbac import Permission

        from app.database.seeds.permissions import PERMISSIONS_BY_CODENAME

        wanted = list((await s.execute(select(Permission).where(Permission.codename.in_(perms)))).scalars().all())
        for codename in set(perms) - {p.codename for p in wanted}:  # same rows `seed --permissions` creates
            d = PERMISSIONS_BY_CODENAME[codename]
            row = Permission(resource=d["resource"], action=d["action"], codename=codename, label=d["label"],
                             category=d["category"], is_sensitive=d.get("is_sensitive", False))
            s.add(row)
            wanted.append(row)
        role = Role(organization_id=org["org"], name=name, slug=f"{name.lower()}-{uuid.uuid4().hex[:5]}")
        role.permissions = list(wanted)
        s.add(role)
        await s.flush()
        email = f"{name.lower()}-{uuid.uuid4().hex[:8]}@example.com"
        u = User(organization_id=org["org"], email=email, email_normalized=email,
                 password_hash=hash_password("x"), first_name=name, last_name="User",
                 is_active=True, is_email_verified=True)
        u.roles.append(role)
        s.add(u)
        await s.flush()
        uid = u.id
        await s.commit()
    return uid


# ── S-01 ─────────────────────────────────────────────────────────────────────

import base64
import io
import struct
import zlib
from types import SimpleNamespace

from app.services import organization_logo as logo

def _png(width=40, height=20) -> bytes:
    def chunk(kind, data):
        c = struct.pack(">I", len(data)) + kind + data
        return c + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10" fill="#0a0"/></svg>'


@pytest.fixture(autouse=True)
def _storage(tmp_path, monkeypatch):
    from app.core import storage
    from app.core.config import settings
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "local")
    monkeypatch.setattr(settings, "STORAGE_LOCAL_DIR", str(tmp_path))
    monkeypatch.setattr(storage, "_storage_instance", None)
    yield
    monkeypatch.setattr(storage, "_storage_instance", None)


class TestFileChecks:
    def test_type_comes_from_the_bytes(self):
        assert logo.detect_logo_type(_png()) == "png"
        assert logo.detect_logo_type(b"\xff\xd8\xff\xe0xxxx") == "jpg"
        assert logo.detect_logo_type(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "webp"
        assert logo.detect_logo_type(SVG) == "svg"
        assert logo.detect_logo_type(b'<?xml version="1.0"?>\n' + SVG) == "svg"
        assert logo.detect_logo_type(b"MZ\x90\x00 not an image") is None
        assert logo.detect_logo_type(b"<html><body>hi</body></html>") is None

    @pytest.mark.parametrize("evil", [
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><rect onclick="x()"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><div/></foreignObject></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"><a xlink:href="javascript:alert(1)"><rect/></a></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><image href="https://evil.example/x.png"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><style>@import url(https://evil.example/a.css);</style></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:url(https://evil.example/x)"/></svg>',
        b'<!DOCTYPE svg [<!ENTITY a "aaaa">]><svg xmlns="http://www.w3.org/2000/svg">&a;</svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><set attributeName="href" to="javascript:x"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"',
    ])
    def test_unsafe_or_broken_svg_is_refused(self, evil):
        from app.core.exceptions import BadRequestError
        with pytest.raises(BadRequestError):
            logo.validate_svg(evil)

    def test_a_plain_svg_with_internal_references_is_fine(self):
        logo.validate_svg(b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
                          b'<defs><linearGradient id="g"/></defs><rect fill="url(#g)"/><use xlink:href="#g"/></svg>')
        b64 = base64.b64encode(_png()).decode()
        logo.validate_svg(f'<svg xmlns="http://www.w3.org/2000/svg"><image href="data:image/png;base64,{b64}"/></svg>'.encode())


def _upload(client, h, content, name="logo.png", ctype="image/png"):
    return client.post("/api/v1/organization/logo", headers=h, files={"file": (name, content, ctype)})


async def test_upload_serve_replace_and_delete(client, org):
    h = _h(org["owner"])
    r = await _upload(client, h, _png())
    assert r.status_code == 200, r.text
    url = r.json()["logo_url"]
    assert url.startswith(f"/api/v1/organization/logo/{org['org']}?v=")
    assert (await client.get("/api/v1/organization", headers=h)).json()["logo_url"] == url

    served = await client.get(url)                       # no auth header: works in a plain <img>
    assert served.status_code == 200 and served.content == _png()
    assert served.headers["content-type"] == "image/png"
    assert served.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in served.headers["content-security-policy"]

    r = await _upload(client, h, SVG, "logo.svg", "image/svg+xml")      # replace png with svg
    assert r.status_code == 200
    again = await client.get(f"/api/v1/organization/logo/{org['org']}")
    assert again.headers["content-type"] == "image/svg+xml" and again.content == SVG
    assert not any(p.name.endswith(".png") for p in __import__("pathlib").Path(
        __import__("app.core.config", fromlist=["settings"]).settings.STORAGE_LOCAL_DIR).rglob(f"{org['org']}.*"))

    r = await client.delete("/api/v1/organization/logo", headers=h)
    assert r.status_code == 200 and r.json()["logo_url"] is None
    assert (await client.get(f"/api/v1/organization/logo/{org['org']}")).status_code == 404


async def test_bad_uploads_are_refused(client, org):
    h = _h(org["owner"])
    assert (await _upload(client, h, b"MZ not an image", "logo.png", "image/png")).status_code == 400   # lying content-type
    assert (await _upload(client, h, b"")).status_code == 400
    assert (await _upload(client, h, _png() + b"0" * (logo.MAX_LOGO_BYTES + 1))).status_code == 400
    evil = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    assert (await _upload(client, h, evil, "x.svg", "image/svg+xml")).status_code == 400
    assert (await client.get("/api/v1/organization", headers=h)).json()["logo_url"] is None


async def test_only_settings_manage_can_change_the_logo(client, engine, org):
    viewer = await _role_user(engine, org, ["employees.view"], "Viewer")
    manager = await _role_user(engine, org, ["settings.manage"], "Mgr")
    assert (await _upload(client, _h(viewer), _png())).status_code == 403
    assert (await client.delete("/api/v1/organization/logo", headers=_h(viewer))).status_code == 403
    assert (await _upload(client, _h(manager), _png())).status_code == 200
    assert (await client.get("/api/v1/organization", headers=_h(viewer))).json()["logo_url"]      # anyone signed in can read it


async def test_logo_of_another_org_is_not_served_after_it_is_removed(client, engine, org):
    other = await _make_org(engine)
    try:
        await _upload(client, _h(other["owner"]), _png())
        await _upload(client, _h(org["owner"]), _png(10, 10))
        assert (await client.get(f"/api/v1/organization/logo/{other['org']}")).content == _png()
        assert (await client.get(f"/api/v1/organization/logo/{org['org']}")).content == _png(10, 10)
        assert (await client.get(f"/api/v1/organization/logo/{uuid.uuid4()}")).status_code == 404
    finally:
        await _drop_org(engine, other)


async def test_payslip_pdf_embeds_the_logo(client, org):
    from app.api.v1.hrms.payroll import _render_payslip_pdf
    from app.models.payroll import ComponentType
    h = _h(org["owner"])
    payslip = SimpleNamespace(working_days=22, present_days=21, absent_days=1, leave_days=0,
                              unpaid_leave_days=0, overtime_hours=0, gross_salary=100000,
                              total_deductions=5000, net_salary=95000)
    run = SimpleNamespace(period_start="2026-09-01", period_end="2026-09-30", pay_date="2026-10-01")
    lines = [SimpleNamespace(component_name="Basic", amount=100000, component_type=ComponentType.EARNING)]
    emp = SimpleNamespace(employee_code="E-1")
    user = SimpleNamespace(first_name="Dana", last_name="Hire")

    plain = _render_payslip_pdf(payslip, emp, user, run, lines)
    assert plain.startswith(b"%PDF")
    await _upload(client, h, _png(80, 40))
    with_logo = _render_payslip_pdf(payslip, emp, user, run, lines, await logo.logo_for_pdf(org["org"]))
    assert with_logo.startswith(b"%PDF") and len(with_logo) > len(plain)
    # a logo that cannot be embedded never breaks the payslip
    assert _render_payslip_pdf(payslip, emp, user, run, lines, b"not an image").startswith(b"%PDF")

    await _upload(client, h, SVG, "logo.svg", "image/svg+xml")
    assert await logo.logo_for_pdf(org["org"]) is None          # SVG is left out of PDFs


async def test_logo_is_revalidated_with_an_etag(client, org):
    await _upload(client, _h(org["owner"]), _png())
    first = await client.get(f"/api/v1/organization/logo/{org['org']}")
    assert first.headers["cache-control"] == "no-cache" and first.headers["etag"]
    again = await client.get(f"/api/v1/organization/logo/{org['org']}", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304 and again.content == b""
    await _upload(client, _h(org["owner"]), _png(10, 10))                       # replaced -> new etag, full body
    changed = await client.get(f"/api/v1/organization/logo/{org['org']}", headers={"If-None-Match": first.headers["etag"]})
    assert changed.status_code == 200 and changed.content == _png(10, 10)
