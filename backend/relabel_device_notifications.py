"""One-off: rewrite the existing "<DEVICE> triggered N activity alert(s)" notifications so
they name the employee who holds that device.   Run from backend\\ :  python relabel_device_notifications.py
Safe to run twice."""
import asyncio
import re
from uuid import UUID

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.devices import Device
from app.models.workflows import Notification
from app.services.device_alerts import holder_label

BODY = re.compile(r"^.*? triggered (\d+) activity alert\(s\)\.")


async def main() -> None:
    changed = 0
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(Notification).where(Notification.type == "device_alert"))).scalars().all()
        cache: dict = {}
        for n in rows:
            raw = (n.metadata_ or {}).get("device_id")
            if not raw or not n.body or not BODY.match(n.body):
                continue
            if raw not in cache:
                dev = (await db.execute(select(Device).where(Device.id == UUID(raw)))).scalar_one_or_none()
                cache[raw] = (await holder_label(db, dev) or "An unassigned device") if dev else None
            label = cache[raw]
            if label is None:
                continue
            new = BODY.sub(lambda m: f"{label} triggered {m.group(1)} activity alert(s).", n.body, count=1)
            if new != n.body:
                n.body = new
                changed += 1
        await db.commit()
    print(f"relabelled {changed} notification(s)")


if __name__ == "__main__":
    asyncio.run(main())
