"""
Notifications against a real (in-memory SQLite) database: who counts as an
approver, that rows are saved, and that each person's on/off choice is honoured.

Run:  cd backend && pytest tests/test_notifications_db.py -v
"""

import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import select

import app.services.notify as notify

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db():
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.database import Base
    import app.models.attendance  # noqa: F401
    import app.models.employee  # noqa: F401
    import app.models.organization  # noqa: F401
    import app.models.rbac  # noqa: F401
    import app.models.user  # noqa: F401
    import app.models.workflows  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


async def _org(db, owner_id=None):
    from app.models.organization import Organization

    org = Organization(id=uuid.uuid4(), name="Acme", slug=f"acme-{uuid.uuid4().hex[:6]}", email="hr@acme.test", owner_id=owner_id)
    db.add(org)
    await db.flush()
    return org


async def _user(db, org_id, *, active=True, prefs=None, first="Ali", last="Raza", roles=()):
    from app.models.user import User

    email = f"{uuid.uuid4().hex[:8]}@example.com"
    u = User(
        id=uuid.uuid4(), email=email, email_normalized=email, password_hash="x", first_name=first, last_name=last,
        organization_id=org_id, is_active=active, preferences=prefs or {},
    )
    db.add(u)
    await db.flush()
    for role in roles:
        await db.execute(notify.user_roles.insert().values(user_id=u.id, role_id=role.id))
    return u


async def _role(db, org_id, *, perms=(), is_super=False):
    from app.models.rbac import Permission, Role

    role = Role(id=uuid.uuid4(), organization_id=org_id, name=f"r-{uuid.uuid4().hex[:4]}",
                slug=f"r-{uuid.uuid4().hex[:6]}", is_super=is_super)
    db.add(role)
    await db.flush()
    for codename in perms:
        resource, action = codename.split(".")
        found = (await db.execute(select(Permission).where(Permission.codename == codename))).scalar_one_or_none()
        if found is None:
            found = Permission(id=uuid.uuid4(), resource=resource, action=action, codename=codename,
                               label=codename, category="Test")
            db.add(found)
            await db.flush()
        await db.execute(notify.role_permissions.insert().values(role_id=role.id, permission_id=found.id))
    return role


async def test_approvers_are_role_holders_super_roles_and_the_owner(db):
    org = await _org(db)
    other_org = await _org(db)
    approver_role = await _role(db, org.id, perms=["leave.approve"])
    viewer_role = await _role(db, org.id, perms=["leave.view"])
    super_role = await _role(db, org.id, is_super=True)

    approver = await _user(db, org.id, roles=[approver_role])
    viewer = await _user(db, org.id, roles=[viewer_role])
    boss = await _user(db, org.id, roles=[super_role])
    owner = await _user(db, org.id)
    org.owner_id = owner.id
    inactive = await _user(db, org.id, active=False, roles=[approver_role])
    outsider = await _user(db, other_org.id, roles=[await _role(db, other_org.id, perms=["leave.approve"])])
    await db.flush()

    ids = await notify.user_ids_with_permission(db, org.id, "leave.approve")
    assert set(ids) == {approver.id, boss.id, owner.id}
    assert viewer.id not in ids and inactive.id not in ids and outsider.id not in ids


async def test_exclude_removes_the_person_who_did_the_action(db):
    org = await _org(db)
    role = await _role(db, org.id, perms=["helpdesk.manage"])
    a = await _user(db, org.id, roles=[role])
    b = await _user(db, org.id, roles=[role])
    ids = await notify.user_ids_with_permission(db, org.id, "helpdesk.manage", exclude=[a.id, None])
    assert ids == [b.id]


async def test_notify_saves_rows_and_honours_each_persons_choice(db):
    from app.models.workflows import Notification

    org = await _org(db)
    on = await _user(db, org.id)
    off = await _user(db, org.id, prefs={"notifications": {"leave": False}})
    gone = await _user(db, org.id, active=False)
    outsider = await _user(db, (await _org(db)).id)

    made = await notify.notify(db, org.id, [on.id, off.id, gone.id, outsider.id], category="leave",
                               title="New leave request", body="Ali asked for 2 days", action_url="/leave",
                               metadata={"x": 1})
    assert made == 1
    rows = (await db.execute(select(Notification))).scalars().all()
    assert [r.user_id for r in rows] == [on.id]
    r = rows[0]
    assert (r.type, r.title, r.action_url, r.is_read, r.metadata_) == ("leave", "New leave request", "/leave", False, {"x": 1})
    assert r.tenant_id == org.id


async def test_a_notification_shows_in_the_users_own_inbox_and_unread_count(db):
    from app.repositories.notification import NotificationRepository

    org = await _org(db)
    u = await _user(db, org.id)
    await notify.notify(db, org.id, [u.id], category="payroll", title="Salary paid")
    repo = NotificationRepository(db, org.id)
    items, total, unread = await repo.list_for_user(u.id)
    assert (total, unread, items[0].title) == (1, 1, "Salary paid")


async def test_employee_lookups(db):
    from app.models.employee import Employee, EmploymentStatus, EmploymentType, JobNature

    org = await _org(db)
    u = await _user(db, org.id, first="Sara", last="Khan")
    emp = Employee(tenant_id=org.id, user_id=u.id, employee_code="E1", employment_type=EmploymentType.FULL_TIME,
                   job_nature=JobNature.PERMANENT, employment_status=EmploymentStatus.ACTIVE,
                   date_of_joining=date(2024, 1, 1))
    db.add(emp)
    await db.flush()

    assert await notify.user_id_for_employee(db, org.id, emp.id) == u.id
    assert await notify.user_id_for_employee(db, org.id, uuid.uuid4()) is None
    assert await notify.user_id_for_employee(db, org.id, None) is None
    assert await notify.user_id_for_employee(db, uuid.uuid4(), emp.id) is None      # other organisation
    assert await notify.employee_name(db, org.id, emp.id) == "Sara Khan"
    assert await notify.employee_name(db, org.id, None) == "An employee"
    assert await notify.user_ids_for_employees(db, org.id, [emp.id, None]) == [u.id]
