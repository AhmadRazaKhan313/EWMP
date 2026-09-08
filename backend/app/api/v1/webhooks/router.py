"""Incoming webhook handlers — for external integrations calling back into EWMP."""

from fastapi import APIRouter, Request, Header
from app.core.security import verify_webhook_signature

router = APIRouter(prefix="/webhooks/incoming", tags=["Webhooks"])


@router.post("/stripe", include_in_schema=False)
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)) -> dict:
    """Handle Stripe billing events."""
    payload = await request.body()
    # Verify signature, process event
    return {"received": True}
