"""
GET /dashboard/stats — the six numbers behind the Dashboard page's stat
cards. See app.services.dashboard for what each number means and why this
is one aggregate endpoint instead of six.

Open to any authenticated user (like /ai/chat) rather than gated by a
specific permission: it's the landing page every org member sees, self-
service employees included, and returns only aggregate counts — no
per-employee or otherwise sensitive rows.
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.permissions.dependencies import get_current_user, get_tenant_id
from app.services.dashboard import get_dashboard_stats

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/stats", summary="Aggregate counts for the dashboard stat cards")
async def dashboard_stats(
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await get_dashboard_stats(db, tenant_id)