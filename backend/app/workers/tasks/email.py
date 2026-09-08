"""
Email background tasks.

All emails are sent via Celery workers so that HTTP requests
are never blocked waiting for SMTP. Each task has retry logic
with exponential backoff for transient SMTP failures.
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.workers.celery_app import celery_app
from app.core.config import settings

logger = logging.getLogger("ewmp.email")


def _send_smtp(to_email: str, subject: str, html_body: str) -> None:
    """Low-level SMTP send. Raises on failure so Celery can retry."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.EMAILS_FROM_NAME} <{settings.EMAILS_FROM_ADDRESS}>"
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as smtp:
        smtp.ehlo()
        smtp.starttls()
        if settings.SMTP_USER:
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        smtp.sendmail(settings.EMAILS_FROM_ADDRESS, to_email, msg.as_string())


@celery_app.task(
    name="email.send_verification",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def send_verification_email(self, to_email: str, token: str) -> None:
    """Send email verification link."""
    verify_url = f"https://app.ewmp.io/verify-email?token={token}"
    html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto;">
      <h2 style="color: #111827;">Verify your email address</h2>
      <p style="color: #6B7280;">Click the button below to verify your email and activate your EWMP account.</p>
      <a href="{verify_url}"
         style="display:inline-block;background:#111827;color:#fff;padding:12px 24px;
                border-radius:6px;text-decoration:none;font-weight:600;margin:16px 0;">
        Verify Email
      </a>
      <p style="color:#9CA3AF;font-size:12px;">
        This link expires in 24 hours. If you didn't create an account, you can safely ignore this email.
      </p>
    </div>
    """
    try:
        _send_smtp(to_email, "Verify your EWMP email address", html)
        logger.info("Verification email sent to %s", to_email)
    except Exception as exc:
        logger.warning("Failed to send verification email to %s: %s", to_email, exc)
        raise self.retry(exc=exc)


@celery_app.task(
    name="email.send_employee_invite",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def send_employee_invite_email(self, to_email: str, first_name: str, invite_token: str) -> None:
    """
    Send a new employee a link to set their own password.

    No password is ever generated or transmitted by EWMP — the employee
    picks their own via the same token-based flow as forgot-password,
    just with a longer validity window (see INVITE_TOKEN_VALID_FOR).
    """
    set_password_url = f"https://app.ewmp.io/reset-password?token={invite_token}"
    html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto;">
      <h2 style="color: #111827;">Welcome to EWMP, {first_name}!</h2>
      <p style="color: #6B7280;">
        An account has been created for you. Click the button below to set
        your password and log in for the first time.
      </p>
      <a href="{set_password_url}"
         style="display:inline-block;background:#111827;color:#fff;padding:12px 24px;
                border-radius:6px;text-decoration:none;font-weight:600;margin:16px 0;">
        Set your password
      </a>
      <p style="color:#9CA3AF;font-size:12px;">
        This link expires in 7 days. If you weren't expecting this account,
        contact your HR administrator.
      </p>
    </div>
    """
    try:
        _send_smtp(to_email, "Welcome to EWMP — set your password", html)
        logger.info("Invite email sent to %s", to_email)
    except Exception as exc:
        logger.warning("Failed to send invite email to %s: %s", to_email, exc)
        raise self.retry(exc=exc)


@celery_app.task(
    name="email.send_password_reset",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def send_password_reset_email(self, to_email: str, token: str) -> None:
    """Send password reset link."""
    reset_url = f"https://app.ewmp.io/reset-password?token={token}"
    html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto;">
      <h2 style="color: #111827;">Reset your password</h2>
      <p style="color: #6B7280;">We received a request to reset your EWMP password.</p>
      <a href="{reset_url}"
         style="display:inline-block;background:#111827;color:#fff;padding:12px 24px;
                border-radius:6px;text-decoration:none;font-weight:600;margin:16px 0;">
        Reset Password
      </a>
      <p style="color:#9CA3AF;font-size:12px;">
        This link expires in 2 hours. If you didn't request a reset, you can safely ignore this email.
      </p>
    </div>
    """
    try:
        _send_smtp(to_email, "Reset your EWMP password", html)
        logger.info("Password reset email sent to %s", to_email)
    except Exception as exc:
        logger.warning("Failed to send reset email to %s: %s", to_email, exc)
        raise self.retry(exc=exc)
