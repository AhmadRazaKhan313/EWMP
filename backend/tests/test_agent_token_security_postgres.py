"""
Regression tests for audit finding H-12 (device agent tokens + screenshots).

Before the fix:
  * an agent token was a 10-year JWT whose stored hash was never compared, so it
    could not be revoked and every re-enrollment left all earlier tokens valid;
  * there was no rotation;
  * the screenshot upload trusted the client's mime_type (text/html was stored
    and served back as a page -- stored XSS), read the whole body before the size
    check, and crashed (500) / let the caller forge the audit trail via
    `requested_by`.

Real HTTP stack + live Postgres (TEST_DATABASE_URL), like the other *_postgres
tests. Only HTTP, raw SQL and the public token helpers are used so the same file
can be run against the pre-fix code.
"""

import hashlib
import os
import struct
import uuid
import zlib
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from jose import jwt
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, create_device_enrollment_token, hash_password
from app.main import app
from app.models.organization import Organization
from app.models.user import User

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp"
)
pytestmark = pytest.mark.asyncio


def _png() -> bytes:
    """A real 1x1 PNG."""
    def chunk(kind, data):
        c = struct.pack(">I", len(data)) + kind + data
        return c + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))


JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
HTML = b"<html><script>fetch('/steal')</script></html>"


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
    email = f"adm-{uuid.uuid4().hex[:8]}@example.com"
    async with AsyncSession(engine, expire_on_commit=False) as s:
        s.add(Organization(id=org_id, name="Agent Org", slug=f"agent-{org_id.hex[:8]}",
                           email=f"a-{org_id.hex[:8]}@example.com"))
        await s.flush()
        user = User(organization_id=org_id, email=email, email_normalized=email,
                    password_hash=hash_password("x"), first_name="Adm", last_name="In",
                    is_active=True, is_email_verified=True)
        s.add(user)
        await s.flush()
        (await s.get(Organization, org_id)).owner_id = user.id
        ids = {"org": org_id, "user": user.id}
        await s.commit()
    return ids


async def _drop_org(engine, ids):
    async with AsyncSession(engine) as s:
        for tbl in ("device_screenshots", "device_metrics", "device_alerts"):
            await s.execute(text(f"DELETE FROM {tbl} WHERE tenant_id = :o"), {"o": ids["org"]})
        await s.execute(text("DELETE FROM devices WHERE tenant_id = :o"), {"o": ids["org"]})
        await s.execute(text("UPDATE organizations SET owner_id = NULL WHERE id = :o"), {"o": ids["org"]})
        await s.execute(delete(User).where(User.organization_id == ids["org"]))
        await s.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": ids["org"]})
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


def _admin(ids) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(ids['user']))}"}


def _bearer(tok) -> dict:
    return {"Authorization": f"Bearer {tok}"}


async def _enroll(client, org) -> dict:
    r = await client.post("/api/v1/devices/enroll", json={
        "enrollment_token": create_device_enrollment_token(str(org["org"])),
        "hostname": f"pc-{uuid.uuid4().hex[:6]}"})
    assert r.status_code == 200, r.text
    return r.json()


async def _heartbeat(client, tok):
    return await client.post("/api/v1/devices/heartbeat", json={"cpu_usage_percent": 5}, headers=_bearer(tok))


def _mint(device_id, *, iat_ago=timedelta(0), lifetime=timedelta(days=90)) -> str:
    """A validly signed agent JWT with chosen timestamps (what an old or
    forged token looks like)."""
    iat = datetime.now(UTC) - iat_ago
    return jwt.encode({"sub": device_id, "type": "agent", "iat": iat, "exp": iat + lifetime},
                      settings.AGENT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


async def _sql(engine, sql, **p):
    async with AsyncSession(engine) as s:
        res = await s.execute(text(sql), p)
        await s.commit()
        return res


async def _install_token(engine, device_id, token):
    """Make `token` the device's currently-issued token (as an enrollment would)."""
    await _sql(engine, "UPDATE devices SET agent_token_hash = :h WHERE id = :d",
               h=hashlib.sha256(token.encode()).hexdigest(), d=device_id)


# ── The token is bound to the device and can be replaced / revoked ────────────

class TestTokenBinding:
    async def test_the_issued_token_works(self, client, org):
        dev = await _enroll(client, org)
        assert (await _heartbeat(client, dev["agent_token"])).status_code == 200

    async def test_a_validly_signed_token_that_was_not_issued_is_rejected(self, client, org):
        """Anyone with the signing key material or an older token must not be
        able to authenticate as the device: only the CURRENT token is valid."""
        dev = await _enroll(client, org)
        stray = _mint(dev["device_id"], iat_ago=timedelta(seconds=7))
        assert stray != dev["agent_token"]
        assert (await _heartbeat(client, stray)).status_code == 401, (
            "a signed token that is not the device's issued token was accepted"
        )

    async def test_a_new_token_replaces_the_old_one(self, client, engine, org):
        dev = await _enroll(client, org)
        old = dev["agent_token"]
        new = _mint(dev["device_id"], iat_ago=timedelta(seconds=3))
        await _install_token(engine, dev["device_id"], new)  # what re-enrollment does
        assert (await _heartbeat(client, new)).status_code == 200
        assert (await _heartbeat(client, old)).status_code == 401, "the replaced token still works"

    async def test_decommissioning_kills_the_token(self, client, org):
        dev = await _enroll(client, org)
        r = await client.post(f"/api/v1/devices/{dev['device_id']}/decommission", headers=_admin(org))
        assert r.status_code == 200, r.text
        assert (await _heartbeat(client, dev["agent_token"])).status_code == 401


# ── Lifetime and rotation ─────────────────────────────────────────────────────

class TestLifetimeAndRotation:
    async def test_new_tokens_are_not_ten_year_tokens(self, client, org):
        dev = await _enroll(client, org)
        claims = jwt.get_unverified_claims(dev["agent_token"])
        assert timedelta(seconds=claims["exp"] - claims["iat"]) <= timedelta(days=settings.AGENT_TOKEN_EXPIRE_DAYS + 1)

    async def test_a_fresh_token_is_not_rotated(self, client, org):
        dev = await _enroll(client, org)
        r = await _heartbeat(client, dev["agent_token"])
        assert "agent_token" not in r.json()

    async def test_a_legacy_ten_year_token_is_replaced_via_the_heartbeat(self, client, engine, org):
        dev = await _enroll(client, org)
        legacy = _mint(dev["device_id"], iat_ago=timedelta(days=2), lifetime=timedelta(days=3650))
        await _install_token(engine, dev["device_id"], legacy)
        r = await _heartbeat(client, legacy)
        assert r.status_code == 200
        assert r.json().get("agent_token"), "a 10-year token was not offered a replacement"

    async def test_an_old_token_is_replaced_before_it_expires(self, client, engine, org):
        dev = await _enroll(client, org)
        aging = _mint(dev["device_id"], iat_ago=timedelta(days=settings.AGENT_TOKEN_ROTATE_AFTER_DAYS + 5))
        await _install_token(engine, dev["device_id"], aging)
        assert (await _heartbeat(client, aging)).json().get("agent_token")

    async def test_rotation_never_locks_out_an_agent_that_ignores_it(self, client, engine, org):
        dev = await _enroll(client, org)
        legacy = _mint(dev["device_id"], iat_ago=timedelta(days=2), lifetime=timedelta(days=3650))
        await _install_token(engine, dev["device_id"], legacy)
        assert (await _heartbeat(client, legacy)).json().get("agent_token")
        # An agent that did not store the new token keeps using the old one.
        again = await _heartbeat(client, legacy)
        assert again.status_code == 200 and again.json().get("agent_token")

    async def test_adopting_the_new_token_retires_the_old_one(self, client, engine, org):
        dev = await _enroll(client, org)
        legacy = _mint(dev["device_id"], iat_ago=timedelta(days=2), lifetime=timedelta(days=3650))
        await _install_token(engine, dev["device_id"], legacy)
        new = (await _heartbeat(client, legacy)).json()["agent_token"]
        assert (await _heartbeat(client, new)).status_code == 200      # adopted
        assert (await _heartbeat(client, legacy)).status_code == 401   # old one is now dead
        r = await _heartbeat(client, new)
        assert r.status_code == 200 and "agent_token" not in r.json()  # fresh: not rotated again


# ── Screenshot upload / serving ───────────────────────────────────────────────

async def _upload(client, tok, content, *, mime="image/png", name="screenshot.png", **form):
    return await client.post("/api/v1/devices/screenshots/upload", headers=_bearer(tok),
                             files={"file": (name, content, mime)}, data={"mime_type": mime, **form})


class TestScreenshotUpload:
    async def test_html_cannot_be_uploaded_as_a_screenshot(self, client, org):
        dev = await _enroll(client, org)
        r = await _upload(client, dev["agent_token"], HTML, mime="text/html", name="x.html")
        assert r.status_code == 400, r.text

    async def test_html_labelled_as_png_is_still_refused(self, client, org):
        dev = await _enroll(client, org)
        r = await _upload(client, dev["agent_token"], HTML, mime="image/png", name="x.png")
        assert r.status_code == 400, "non-image bytes were accepted because the label said PNG"

    async def test_a_real_png_is_stored_and_served_as_an_inert_image(self, client, org):
        dev = await _enroll(client, org)
        # The client LIES about the type; the bytes decide.
        r = await _upload(client, dev["agent_token"], _png(), mime="text/html", name="../../evil.html")
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        img = await client.get(f"/api/v1/devices/{dev['device_id']}/screenshots/{sid}/image", headers=_admin(org))
        assert img.status_code == 200
        assert img.headers["content-type"] == "image/png"
        assert img.headers["x-content-type-options"] == "nosniff"
        assert "sandbox" in img.headers["content-security-policy"]
        assert img.content == _png()

    async def test_jpeg_is_stored_as_jpeg(self, client, org):
        dev = await _enroll(client, org)
        sid = (await _upload(client, dev["agent_token"], JPEG, mime="image/png")).json()["id"]
        img = await client.get(f"/api/v1/devices/{dev['device_id']}/screenshots/{sid}/image", headers=_admin(org))
        assert img.headers["content-type"] == "image/jpeg"

    async def test_oversized_upload_is_refused(self, client, org, monkeypatch):
        from app.api.v1.devices import devices as devmod
        monkeypatch.setattr(devmod, "MAX_SCREENSHOT_BYTES", 1024, raising=False)
        dev = await _enroll(client, org)
        r = await _upload(client, dev["agent_token"], _png() + b"\x00" * 4096)
        assert r.status_code == 400

    async def test_absurd_dimensions_are_refused(self, client, org):
        dev = await _enroll(client, org)
        r = await _upload(client, dev["agent_token"], _png(), width="-5", height="999999999")
        assert r.status_code == 422


class TestScreenshotAttribution:
    async def _row(self, engine, sid):
        return (await _sql(engine, "SELECT requested_by_id FROM device_screenshots WHERE id = :i", i=sid)).scalar_one()

    async def test_a_malformed_requested_by_does_not_crash_the_upload(self, client, engine, org):
        dev = await _enroll(client, org)
        r = await _upload(client, dev["agent_token"], _png(), requested_by="not-a-uuid")
        assert r.status_code == 200, r.text  # used to be a 500
        assert await self._row(engine, r.json()["id"]) is None

    async def test_requested_by_from_another_tenant_cannot_be_forged(self, client, engine, org, other_org):
        dev = await _enroll(client, org)
        r = await _upload(client, dev["agent_token"], _png(), requested_by=str(other_org["user"]))
        assert r.status_code == 200, r.text
        assert await self._row(engine, r.json()["id"]) is None, "the audit trail named another tenant's user"

    async def test_a_genuine_requester_in_the_same_tenant_is_recorded(self, client, engine, org):
        dev = await _enroll(client, org)
        r = await _upload(client, dev["agent_token"], _png(), requested_by=str(org["user"]))
        assert r.status_code == 200, r.text
        assert await self._row(engine, r.json()["id"]) == org["user"]


class TestLegacyRowsAreServedSafely:
    async def test_a_stored_html_screenshot_is_served_as_a_download_not_a_page(self, client, engine, org):
        """Rows written before validation existed may hold HTML labelled text/html."""
        from app.core.storage import get_storage
        dev = await _enroll(client, org)
        key = f"devices/{org['org']}/{dev['device_id']}/screenshots/{uuid.uuid4().hex}.png"
        await get_storage().save(key, HTML)
        sid = uuid.uuid4()
        await _sql(engine,
                   "INSERT INTO device_screenshots (id, tenant_id, device_id, storage_key, mime_type, "
                   "file_size_bytes, captured_at, is_deleted, created_at, updated_at) "
                   "VALUES (:i, :t, :d, :k, 'text/html', :n, now(), false, now(), now())",
                   i=sid, t=org["org"], d=dev["device_id"], k=key, n=len(HTML))
        img = await client.get(f"/api/v1/devices/{dev['device_id']}/screenshots/{sid}/image", headers=_admin(org))
        assert img.status_code == 200
        assert img.headers["content-type"] != "text/html"
        assert "attachment" in img.headers["content-disposition"]
        assert img.headers["x-content-type-options"] == "nosniff"
