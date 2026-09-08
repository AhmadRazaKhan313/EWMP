"""
Regression tests for device-fleet bugs that need a REAL database:

1. Action-queue lost-update race — every device action endpoint
   (lock/restart/shutdown/message/screenshot) used to do a plain
   read-modify-write on `pending_actions` with no locking:
       actions = list(device.pending_actions or [])
       actions.append(...)
       device.pending_actions = actions
   Two admins queuing actions for the same device at nearly the same time
   race: both read the same starting list, whichever write commits second
   silently overwrites the first — that action is lost even though the
   admin got a "queued" success response. Fixed with `.with_for_update()`
   row-level locking (see `_queue_device_action`).

2. Fleet-list metrics scan — `list_devices` used to fetch EVERY historical
   `DeviceMetric` row for the current page's devices with no LIMIT, just to
   keep one (the latest) per device in a Python dict. A device heartbeats
   roughly every 60s, so a long-running device could have hundreds of
   thousands of rows. Fixed with a `row_number()` window-function subquery
   that bounds the query to exactly one row per device at the SQL level.

Neither of these is reproducible with a mocked/fake DB session — the first
is genuine PostgreSQL row-locking behavior across two real concurrent
connections, and the second is about what actually comes back from a real
query plan, not application logic. This file spins up a real
PostgreSQL-backed AsyncSession (already migrated during this engagement's
work) and cleans up its own rows.

Run:  cd backend && pytest tests/test_device_queue_race_and_metrics.py -v
      (requires the local PostgreSQL instance + `alembic upgrade head`)
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.devices import Device, DeviceMetric, DeviceOS, DeviceStatus
from app.models.organization import Organization

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp",
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(DATABASE_URL)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def org(engine):
    org_id = uuid.uuid4()
    async with AsyncSession(engine) as session:
        session.add(Organization(
            id=org_id, name="Test Org", slug=f"test-org-{org_id.hex[:8]}",
            email=f"test-{org_id.hex[:8]}@example.com",
        ))
        await session.commit()
    yield org_id
    async with AsyncSession(engine) as session:
        await session.execute(delete(Organization).where(Organization.id == org_id))
        await session.commit()


@pytest_asyncio.fixture
async def device(engine, org):
    device_id = uuid.uuid4()
    async with AsyncSession(engine) as session:
        session.add(Device(
            id=device_id, tenant_id=org, hostname="TEST-HOST", agent_id=f"agent-{device_id.hex[:8]}",
            agent_token_hash="x" * 64, os_type=DeviceOS.WINDOWS, status=DeviceStatus.ONLINE,
            pending_actions=[],
        ))
        await session.commit()
    yield device_id
    async with AsyncSession(engine) as session:
        await session.execute(delete(DeviceMetric).where(DeviceMetric.device_id == device_id))
        await session.execute(delete(Device).where(Device.id == device_id))
        await session.commit()


# ── 1. Action-queue race condition ──────────────────────────────────────────
async def _old_buggy_queue_action(engine, device_id: uuid.UUID, action: dict, both_read_barrier: asyncio.Barrier):
    """Mirrors the OLD code exactly: plain read, then wait at a barrier so
    BOTH concurrent calls are guaranteed to have read before either writes
    (deterministic interleaving, not timing-dependent), then write. No
    locking."""
    async with AsyncSession(engine) as session:
        result = await session.execute(select(Device).where(Device.id == device_id))
        dev = result.scalar_one()
        actions = list(dev.pending_actions or [])
        await both_read_barrier.wait()  # guarantees interleaving deterministically
        actions.append(action)
        dev.pending_actions = actions
        await session.flush()
        await session.commit()


async def _new_locked_queue_action(engine, device_id: uuid.UUID, action: dict, delay: float):
    """Mirrors the FIX: real production code path (_queue_device_action)."""
    from app.api.v1.hrms import assets  # noqa: F401  (import ordering no-op)
    from app.api.v1.devices.devices import _queue_device_action

    async with AsyncSession(engine) as session:
        # Same artificial delay injected via a monkeypatched sleep hook so
        # both concurrent calls still race for the lock at the same point;
        # the row lock (not timing) is what should save us here.
        original_execute = session.execute

        async def _delayed_execute(*args, **kwargs):
            result = await original_execute(*args, **kwargs)
            await asyncio.sleep(delay)
            return result

        session.execute = _delayed_execute  # type: ignore[method-assign]
        await _queue_device_action(session, device_id, org_id_holder["tenant_id"], action)
        await session.commit()


# A little awkward: _queue_device_action needs tenant_id, stash it via closure
org_id_holder: dict = {}


class TestActionQueueRace:
    async def test_old_pattern_loses_an_update_under_concurrency(self, engine, org, device):
        """Proves the BUG mechanism: two concurrent unlocked
        read-modify-writes on the same row lose one of them. Uses a
        barrier (not a fixed sleep) so the interleaving is guaranteed
        regardless of system load — not a timing-dependent flake."""
        barrier = asyncio.Barrier(2)
        await asyncio.gather(
            _old_buggy_queue_action(engine, device, {"action": "lock"}, barrier),
            _old_buggy_queue_action(engine, device, {"action": "restart"}, barrier),
        )
        async with AsyncSession(engine) as session:
            dev = (await session.execute(select(Device).where(Device.id == device))).scalar_one()
            # THE BUG: only one of the two actions survived.
            assert len(dev.pending_actions) < 2, (
                "Expected the old unlocked pattern to lose an update under "
                "concurrency, but both actions survived."
            )

    async def test_fixed_pattern_never_loses_an_update_under_concurrency(self, engine, org, device):
        """THE fix assertion: with .with_for_update() locking, both
        concurrent action-queue calls must survive — no lost updates."""
        org_id_holder["tenant_id"] = org
        await asyncio.gather(
            _new_locked_queue_action(engine, device, {"action": "lock"}, delay=0.05),
            _new_locked_queue_action(engine, device, {"action": "restart"}, delay=0.05),
        )
        async with AsyncSession(engine) as session:
            dev = (await session.execute(select(Device).where(Device.id == device))).scalar_one()
            actions_by_type = {a["action"] for a in dev.pending_actions}
            assert actions_by_type == {"lock", "restart"}, (
                f"Expected both queued actions to survive, got: {dev.pending_actions}"
            )

    async def test_heartbeat_dequeue_is_also_locked_against_a_concurrent_queue(self, engine, org, device):
        """The heartbeat's dequeue-and-clear must not race with a
        concurrently-arriving admin action queue either."""
        from app.api.v1.devices.devices import _queue_device_action

        async with AsyncSession(engine) as session:
            dev = (await session.execute(select(Device).where(Device.id == device))).scalar_one()
            dev.pending_actions = [{"action": "lock"}]
            await session.commit()

        async def _heartbeat_dequeue():
            async with AsyncSession(engine) as session:
                locked = (
                    await session.execute(select(Device).where(Device.id == device).with_for_update())
                ).scalar_one()
                actions = list(locked.pending_actions or [])
                await asyncio.sleep(0.05)
                locked.pending_actions = []
                await session.flush()
                await session.commit()
                return actions

        async def _queue_more():
            async with AsyncSession(engine) as session:
                await _queue_device_action(session, device, org, {"action": "restart"})
                await session.commit()

        dequeued, _ = await asyncio.gather(_heartbeat_dequeue(), _queue_more())

        async with AsyncSession(engine) as session:
            dev = (await session.execute(select(Device).where(Device.id == device))).scalar_one()

        # Either the restart was queued before the heartbeat's lock was
        # acquired (dequeued contains it, final queue empty) or after
        # (dequeued is just the original lock, final queue has restart) —
        # what must NEVER happen is the restart vanishing entirely.
        all_seen_actions = {a["action"] for a in dequeued} | {a["action"] for a in dev.pending_actions}
        assert "restart" in all_seen_actions, "The concurrently-queued restart action was lost."


# ── 2. Fleet metrics scan boundedness ────────────────────────────────────────
class TestFleetMetricsScanIsBounded:
    async def test_query_returns_exactly_one_row_per_device_not_full_history(self, engine, org, device):
        now = datetime.now(timezone.utc)
        async with AsyncSession(engine) as session:
            # Seed a large-ish history — the old code would fetch all of these.
            for i in range(50):
                session.add(DeviceMetric(
                    tenant_id=org, device_id=device,
                    recorded_at=now - timedelta(minutes=i),
                    cpu_usage_percent=float(i),
                ))
            await session.commit()

        from sqlalchemy import func
        from sqlalchemy.orm import aliased

        async with AsyncSession(engine) as session:
            row_number_col = (
                func.row_number()
                .over(partition_by=DeviceMetric.device_id, order_by=DeviceMetric.recorded_at.desc())
                .label("rn")
            )
            ranked_subq = (
                select(DeviceMetric, row_number_col).where(DeviceMetric.device_id.in_([device])).subquery()
            )
            latest_alias = aliased(DeviceMetric, ranked_subq)
            rows = (
                await session.execute(select(latest_alias).where(ranked_subq.c.rn == 1))
            ).scalars().all()

        assert len(rows) == 1, f"Expected exactly 1 row (the latest) per device, got {len(rows)}"
        assert rows[0].cpu_usage_percent == 0.0  # i=0 -> now -> the most recent one

    async def test_list_devices_endpoint_uses_the_bounded_query(self):
        """Source-level guard: the endpoint must use the windowed subquery,
        not an unbounded per-device history scan."""
        import inspect

        from app.api.v1.devices import devices as devices_mod

        source = inspect.getsource(devices_mod.list_devices)
        assert "row_number" in source, "list_devices no longer uses the bounded row_number() query (bug regressed)."
        assert ".order_by(DeviceMetric.device_id, DeviceMetric.recorded_at.desc())" not in source, (
            "list_devices still uses the old unbounded 'fetch everything, dedupe in Python' pattern."
        )