"""Onboarding emails and the daily onboarding sweep (N-01)."""
import asyncio
import html as html_lib
import logging

from app.core.database import worker_db_session
from app.workers.celery_app import celery_app
from app.workers.tasks.email import _send_smtp

logger = logging.getLogger("ewmp.onboarding")


def _button(url: str, label: str) -> str:
    return (f'<a href="{html_lib.escape(url, quote=True)}" style="display:inline-block;background:#7F56D9;color:#fff;'
            f'padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600;margin:16px 0;">{html_lib.escape(label)}</a>')


def _wrap(inner: str) -> str:
    return f'<div style="font-family:-apple-system,sans-serif;max-width:600px;margin:0 auto;color:#344054;">{inner}</div>'


@celery_app.task(name="onboarding.send_offer_email", bind=True, max_retries=3, default_retry_delay=60)
def send_offer_email(self, to_email: str, name: str, job_title: str, company: str, link: str, expires_at: str) -> None:
    e = html_lib.escape
    body = _wrap(
        f"<h2 style='color:#101828'>Your offer from {e(company)}</h2>"
        f"<p>Hi {e(name)}, we are pleased to offer you the position of <b>{e(job_title)}</b>.</p>"
        f"{_button(link, 'View and respond to your offer')}"
        f"<p style='color:#667085;font-size:13px'>This link is personal to you and expires on {e(expires_at[:10])}.</p>"
    )
    try:
        _send_smtp(to_email, f"Your offer from {company}", body)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Offer email to %s failed: %s", to_email, exc)
        raise self.retry(exc=exc)


@celery_app.task(name="onboarding.send_preboarding_email", bind=True, max_retries=3, default_retry_delay=60)
def send_preboarding_email(self, to_email: str, name: str, link: str, joining_date: str) -> None:
    e = html_lib.escape
    body = _wrap(
        f"<h2 style='color:#101828'>Welcome, {e(name)}!</h2>"
        f"<p>Your joining date is <b>{e(joining_date)}</b>. Please complete your details and upload your documents "
        f"before your first day.</p>{_button(link, 'Complete pre-boarding')}"
        "<p style='color:#667085;font-size:13px'>This link is personal to you.</p>"
    )
    try:
        _send_smtp(to_email, "Complete your pre-boarding", body)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Pre-boarding email to %s failed: %s", to_email, exc)
        raise self.retry(exc=exc)


@celery_app.task(name="onboarding.send_welcome_email", bind=True, max_retries=3, default_retry_delay=60)
def send_welcome_email(self, to_email: str, name: str, message: str) -> None:
    e = html_lib.escape
    body = _wrap(f"<h2 style='color:#101828'>Welcome{', ' + e(name) if name else ''}!</h2>"
                 f"<p style='white-space:pre-line'>{e(message)}</p>")
    try:
        _send_smtp(to_email, "Welcome aboard", body)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Welcome email to %s failed: %s", to_email, exc)
        raise self.retry(exc=exc)


async def _sweep() -> dict:
    from app.services.onboarding import run_daily_sweep

    async with worker_db_session() as db:
        result = await run_daily_sweep(db)
        await db.commit()
    return result


@celery_app.task(name="onboarding.daily_sweep")
def daily_sweep() -> dict:
    result = asyncio.run(_sweep())
    if any(result.values()):
        logger.info("Onboarding sweep: %s", result)
    return result
