"""
Database session management.

Uses SQLAlchemy 2.0 async engine with a connection pool tuned for
production workloads. Every request gets its own session via the
`get_db` dependency — sessions are always closed, even on exceptions.
"""

import sys
import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

# Windows' default ProactorEventLoop doesn't reliably support asyncpg's
# connection teardown (surfaces as "RuntimeError: Event loop is closed" or
# "'NoneType' object has no attribute 'send'" the moment a query tries to
# open a connection). SelectorEventLoop doesn't have this problem. This has
# to run before any event loop is created, so it lives at import time here
# rather than in a startup hook — this module is imported before the first
# `asyncio.run()` / uvicorn server loop starts, whether the entry point is
# `manage.py` or `uvicorn app.main:app`.
# Note: if you rely on `--reload`'s subprocess-based file watcher and hit
# issues with it after this change, running without `--reload` is the
# workaround until that's investigated further — DB connectivity working
# takes priority.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ── Engine ────────────────────────────────────────────────────────────────────
#
# asyncpg is the async PostgreSQL driver. We convert the standard postgres://
# DSN to postgresql+asyncpg:// format that SQLAlchemy expects.
#
_async_db_url = settings.database_url_str.replace(
    "postgresql://", "postgresql+asyncpg://"
).replace(
    "postgres://", "postgresql+asyncpg://"
)

engine = create_async_engine(
    _async_db_url,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_timeout=settings.DATABASE_POOL_TIMEOUT,
    pool_pre_ping=True,  # Verify connections before checkout to handle stale connections
    echo=settings.DEBUG,  # Log SQL in development; never in production
)

# ── Session Factory ───────────────────────────────────────────────────────────
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Keep objects usable after commit (important for async)
    autocommit=False,
    autoflush=False,
)


# ── Base Model ────────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    """
    All SQLAlchemy models inherit from this base.

    Keeping it in database.py (rather than a separate models/__init__.py)
    prevents circular imports when Alembic needs to discover all models.
    """
    pass


# ── Request-scoped Session Dependency ────────────────────────────────────────
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides a database session.

    Usage:
        @router.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db)):
            ...

    The session is always rolled back on exception and closed on exit,
    so callers never need to manage cleanup themselves.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ── Context Manager for Background Tasks ─────────────────────────────────────
@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager for use outside of FastAPI dependency injection.

    Use this in Celery tasks, CLI scripts, and WebSocket handlers where
    `Depends(get_db)` is not available.

    Usage:
        async with get_db_context() as db:
            result = await db.execute(select(User))
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
