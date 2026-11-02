"""Set the organisation timezone.  Run from the backend folder:
    python set_org_timezone.py                  -> shows each organisation's timezone
    python set_org_timezone.py Asia/Karachi     -> sets ALL organisations to that zone
"""
import asyncio
import logging
import sys
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.core.database import AsyncSessionLocal

logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


async def main(zone: str | None) -> None:
    async with AsyncSessionLocal() as s:
        if zone:
            ZoneInfo(zone)  # fails loudly on a typo
            await s.execute(text("UPDATE organizations SET timezone = :z"), {"z": zone})
            await s.commit()
            print(f"All organisations set to {zone}\n")
        rows = (await s.execute(text("SELECT name, timezone FROM organizations WHERE is_deleted = false ORDER BY name"))).all()
        for name, tz in rows:
            print(f"{name:<30} {tz}")


asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
