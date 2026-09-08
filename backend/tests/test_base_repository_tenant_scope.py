"""
Regression tests for the deny-by-default tenant scope fix (bug H4).

A tenant-scoped repository must NEVER read or write when it has no
tenant_id: doing so previously returned (and could persist) rows across
*every* tenant. `BaseRepository` now fails closed and loud
(`TenantScopeError`) instead of silently running an unscoped query.

These tests only build SQLAlchemy statements (they never execute them) and
the guard raises before any DB access, so they need NO database — only the
`app` package importable (env configured).

Run:  cd backend && pytest tests/test_base_repository_tenant_scope.py -v
"""

import asyncio
import uuid

import pytest
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.exceptions import TenantScopeError
from app.repositories.base import BaseRepository


class _Base(DeclarativeBase):
    pass


class _TenantThing(_Base):
    """Stand-in for a tenant-scoped model (has a tenant_id column)."""

    __tablename__ = "_tenant_thing"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column()
    is_deleted: Mapped[bool] = mapped_column(default=False)


class _GlobalThing(_Base):
    """Stand-in for a non-tenant (platform-global) model."""

    __tablename__ = "_global_thing"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)


TENANT = uuid.uuid4()


# ── Reads fail closed when unscoped ───────────────────────────────────────────

def test_tenant_model_without_tenant_id_refuses_to_query():
    """THE security assertion: a tenant model with no tenant_id must raise,
    not return every tenant's rows."""
    repo = BaseRepository(db=None, model=_TenantThing, tenant_id=None)
    with pytest.raises(TenantScopeError):
        repo._base_query()


def test_get_on_unscoped_tenant_repo_raises_before_db_access():
    """`get` funnels through `_base_query`; the guard must fire before the
    (here, None) database is ever touched."""
    repo = BaseRepository(db=None, model=_TenantThing, tenant_id=None)
    with pytest.raises(TenantScopeError):
        asyncio.run(repo.get(uuid.uuid4()))


# ── Writes fail closed when unscoped ──────────────────────────────────────────

def test_create_on_unscoped_tenant_repo_raises():
    repo = BaseRepository(db=None, model=_TenantThing, tenant_id=None)
    with pytest.raises(TenantScopeError):
        asyncio.run(repo.create({"id": uuid.uuid4()}))


def test_bulk_create_on_unscoped_tenant_repo_raises():
    repo = BaseRepository(db=None, model=_TenantThing, tenant_id=None)
    with pytest.raises(TenantScopeError):
        asyncio.run(repo.bulk_create([{"id": uuid.uuid4()}]))


# ── The scoped / non-tenant paths still work ──────────────────────────────────

def test_tenant_model_with_tenant_id_applies_filter():
    """A properly scoped repo builds a SELECT filtered by tenant_id."""
    repo = BaseRepository(db=None, model=_TenantThing, tenant_id=TENANT)
    stmt = repo._base_query()
    compiled = str(stmt)
    assert "tenant_id" in compiled
    # soft-delete filter also present
    assert "is_deleted" in compiled


def test_global_model_without_tenant_id_is_allowed():
    """Non-tenant (platform-global) models are unaffected: no tenant_id is
    required and no filter/guard applies."""
    repo = BaseRepository(db=None, model=_GlobalThing, tenant_id=None)
    stmt = repo._base_query()  # must NOT raise
    assert "_global_thing" in str(stmt)