"""Test helper: create an enrolled device straight in the DB.

Devices are only added by signing in to the desktop app (POST /devices/self-enroll),
so tests that just need a device row with a valid agent token build it here.
"""
import hashlib
import os
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.security import create_agent_token
from app.models.devices import Device, DeviceOS, DeviceStatus

_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp")


async def make_device(org, hostname: str | None = None) -> dict:
    hostname = hostname or f"pc-{uuid.uuid4().hex[:6]}"
    engine = create_async_engine(_URL)
    try:
        async with AsyncSession(engine) as s:
            now = datetime.now(timezone.utc)
            dev = Device(
                tenant_id=org["org"], hostname=hostname, device_name=hostname,
                agent_id=str(uuid.uuid4()), agent_version="test", agent_token_hash="",
                os_type=DeviceOS.WINDOWS, status=DeviceStatus.ONLINE,
                last_seen_at=now, last_heartbeat_at=now, is_enrolled=True,
            )
            s.add(dev)
            await s.flush()
            dev_id = str(dev.id)
            tok = create_agent_token(dev_id)
            dev.agent_token_hash = hashlib.sha256(tok.encode()).hexdigest()
            dev.next_agent_token_hash = None
            await s.commit()
            return {"device_id": dev_id, "agent_token": tok}
    finally:
        await engine.dispose()
