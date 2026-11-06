"""Outgoing finance email. One seam so tests (and a future provider) can replace delivery."""
import asyncio
import logging

logger = logging.getLogger("ewmp.finance.mail")


async def deliver(to_email: str, subject: str, html_body: str) -> None:
    """Send through the platform SMTP settings. Raises if the server refuses, so callers can record the failure."""
    from app.workers.tasks.email import _send_smtp  # lazy: importing it pulls in celery
    await asyncio.to_thread(_send_smtp, to_email, subject, html_body)
