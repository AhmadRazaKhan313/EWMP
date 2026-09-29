"""
Application configuration.

All settings are loaded from environment variables (or a .env file).
Pydantic Settings v2 validates every value at startup — the app will
refuse to start if a required variable is missing or malformed.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ─────────────────────────────────────────────
    APP_NAME: str = "EWMP — Enterprise Workforce Management Platform"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # ── Security ─────────────────────────────────────────────────
    SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ENCRYPTION_KEY: str  # 32-byte key for field-level encryption

    # ── CORS ─────────────────────────────────────────────────────
    # NoDecode: pydantic-settings normally tries its own json.loads() on any
    # env var feeding a list[str] field BEFORE parse_cors_origins() below ever
    # runs — and raises SettingsError immediately if that isn't byte-perfect
    # JSON, meaning the comma-separated fallback that validator implements
    # was unreachable dead code. This was invisible with a hand-written
    # (LF-only, no stray bytes) JSON array in .env, but broke the moment the
    # value picked up so much as a trailing character (e.g. a Windows \r, or
    # docker-compose's own ${VAR} substitution reformatting it) — or if
    # anyone wrote a comma-separated value the way the validator's docstring
    # says is supported. NoDecode hands the raw string straight to the
    # validator instead, so it decides how to parse it.
    ALLOWED_ORIGINS: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    # ── Database ─────────────────────────────────────────────────
    DATABASE_URL: PostgresDsn
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 40
    DATABASE_POOL_TIMEOUT: int = 30

    # ── Redis ────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ── Storage ──────────────────────────────────────────────────
    STORAGE_BACKEND: Literal["s3", "r2", "minio", "local"] = "local"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "us-east-1"
    S3_BUCKET_NAME: str = "ewmp-files"
    S3_ENDPOINT_URL: str = ""  # For MinIO / Cloudflare R2
    STORAGE_LOCAL_DIR: str = "storage/uploads"  # Used when STORAGE_BACKEND=local
    MAX_DOCUMENT_UPLOAD_MB: int = 15

    # ── Device Activity Watchlist ────────────────────────────────────
    # Default set of domains/app-window-title keywords the agent flags as
    # non-work activity (FEAT: Device Alerts). Platform-wide default;
    # an organization can override this via the /devices/activity-watchlist
    # endpoint if a per-org list is configured later. Kept short and
    # explicit rather than an exhaustive blocklist — the goal is catching
    # obvious policy violations, not building a comprehensive web filter.
    DEVICE_ACTIVITY_WATCHLIST: list[str] = [
        "facebook.com", "instagram.com", "tiktok.com", "twitter.com", "x.com",
        "reddit.com", "snapchat.com", "youtube.com", "netflix.com", "twitch.tv",
        "whatsapp.com",
    ]

    # ── Device Online/Offline Detection ──────────────────────────────
    # The desktop app/agent pings POST /devices/heartbeat roughly every
    # DEVICE_HEARTBEAT_INTERVAL_SECONDS while running. A device only ever
    # gets flipped to ONLINE by a heartbeat (or enrollment) arriving — it
    # never flips itself back to OFFLINE when the app quits or the machine
    # loses power, since there's no "goodbye" signal to rely on. The
    # `device_health.mark_stale_devices_offline` Celery beat task is what
    # actually detects that and marks it OFFLINE, once
    # DEVICE_OFFLINE_AFTER_SECONDS has passed with no heartbeat. Kept well
    # above the ping interval so one or two dropped/delayed heartbeats
    # don't flap a device's status.
    DEVICE_HEARTBEAT_INTERVAL_SECONDS: int = 60
    DEVICE_OFFLINE_AFTER_SECONDS: int = 180

    # ── Email ────────────────────────────────────────────────────
    # Brevo's free tier (300 emails/day, no card required) — see .env for
    # the signup + SMTP-key setup steps. SMTP_USER/PASSWORD still need to
    # be filled in per-environment; this default only saves re-typing the
    # host/port every time.
    SMTP_HOST: str = "smtp-relay.brevo.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    EMAILS_FROM_ADDRESS: str = "noreply@ewmp.io"
    EMAILS_FROM_NAME: str = "EWMP Platform"

    # ── AI Providers ─────────────────────────────────────────────
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    GOOGLE_AI_API_KEY: str = ""
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    DEFAULT_AI_PROVIDER: Literal["openai", "anthropic", "google", "ollama"] = "openai"
    DEFAULT_AI_MODEL: str = "gpt-4o-mini"

    # ── Platform Super Admin ─────────────────────────────────────
    SUPER_ADMIN_EMAIL: str
    SUPER_ADMIN_PASSWORD: str

    # ── Rate Limiting ─────────────────────────────────────────────
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 100  # reserved (no global limiter yet)
    # Per-IP cap for the low-volume public endpoints that send email or create
    # accounts: /auth/register, /forgot-password, /reset-password, /verify-email.
    RATE_LIMIT_AUTH_REQUESTS_PER_MINUTE: int = 10
    # /auth/login is limited on two axes. Per-IP is deliberately generous: a whole
    # office often shares ONE public IP (NAT) and signs in around the same minute.
    # Per-email is tight: it is what actually stops password guessing on an account.
    RATE_LIMIT_LOGIN_PER_IP_PER_MINUTE: int = 30
    RATE_LIMIT_LOGIN_PER_EMAIL_PER_MINUTE: int = 5
    # Password-reset emails per address per HOUR (stops inbox-bombing a victim).
    RATE_LIMIT_FORGOT_PASSWORD_PER_EMAIL_PER_HOUR: int = 3
    # Master switch (set false only for local debugging / load tests).
    RATE_LIMIT_ENABLED: bool = True

    # ── Account lockout ───────────────────────────────────────────
    # 5 consecutive failures lock the account for 30 minutes (see
    # UserRepository.record_failed_login). ON by default; the gate used to be
    # commented out "for testing" — set LOGIN_LOCKOUT_ENABLED=false in a dev
    # .env instead of editing code.
    LOGIN_LOCKOUT_ENABLED: bool = True

    # ── Reverse proxy ─────────────────────────────────────────────
    # How many trusted reverse proxies sit in front of the API (0 = none; the API
    # is reached directly, e.g. docker-compose port 8000). Only when > 0 is the
    # X-Forwarded-For header believed — otherwise any client could forge it to
    # dodge per-IP rate limits and spoof `last_login_ip`. Behind the bundled
    # nginx (which appends the real client IP) set this to 1.
    TRUSTED_PROXY_COUNT: int = 0

    # ── Agent Communication ───────────────────────────────────────
    AGENT_SECRET_KEY: str  # Shared secret for desktop agent auth
    AGENT_HEARTBEAT_INTERVAL_SECONDS: int = 30

    # ── Billing ──────────────────────────────────────────────────
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""

    # ── Integrations ─────────────────────────────────────────────
    SLACK_CLIENT_ID: str = ""
    SLACK_CLIENT_SECRET: str = ""
    TEAMS_CLIENT_ID: str = ""
    TEAMS_CLIENT_SECRET: str = ""
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    JIRA_CLIENT_ID: str = ""
    JIRA_CLIENT_SECRET: str = ""

    # ── Feature Flags ─────────────────────────────────────────────
    FEATURE_AI_ASSISTANT: bool = True
    FEATURE_WORKFLOW_ENGINE: bool = True
    FEATURE_MARKETPLACE: bool = True
    FEATURE_BILLING: bool = True
    FEATURE_DEVICE_MANAGEMENT: bool = True

    # Defaults to True (secure). Set to False only for local/dev environments
    # where SMTP isn't configured, so the "verify your email" gate — which
    # depends on a real email actually being delivered — doesn't block
    # everyone from using the app. Must stay True in production; there is no
    # per-user bypass, this is a single org-wide switch.
    REQUIRE_EMAIL_VERIFICATION: bool = True

    # Public base URL of the web app. Every link inside an email (verify
    # email, reset password, invite) is built from it, so it MUST match where
    # the frontend is actually served — e.g. https://hr.yourcompany.com in
    # production. Links used to be hardcoded to https://app.ewmp.io, which
    # made verification impossible on any other domain (including localhost).
    FRONTEND_URL: str = "http://localhost:3000"

    @field_validator("FRONTEND_URL")
    @classmethod
    def _strip_frontend_url(cls, v: str) -> str:
        return v.strip().rstrip("/")

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        """Accepts either a JSON array ('["a","b"]') or a plain
        comma-separated list ('a,b') — and is defensive about whitespace and
        stray \\r (a Windows-edited .env, or docker-compose's own ${VAR}
        substitution, can both add bytes a strict json.loads() rejects)."""
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                try:
                    import json

                    parsed = json.loads(v)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"ALLOWED_ORIGINS looks like a JSON array but failed to "
                        f"parse: {exc}. Value was: {v!r}"
                    ) from exc
                if not isinstance(parsed, list) or not all(isinstance(x, str) for x in parsed):
                    raise ValueError("ALLOWED_ORIGINS JSON array must contain only strings")
                return [origin.strip() for origin in parsed]
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.ENVIRONMENT == "production":
            if self.DEBUG:
                raise ValueError("DEBUG must be False in production")
            if not self.SECRET_KEY or len(self.SECRET_KEY) < 32:
                raise ValueError("SECRET_KEY must be at least 32 characters in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"

    @property
    def database_url_str(self) -> str:
        return str(self.DATABASE_URL)


@lru_cache
def get_settings() -> Settings:
    """
    Returns a cached Settings instance.

    Using lru_cache ensures the .env file is read only once per process,
    which matters for performance in production with many concurrent workers.
    """
    return Settings()


settings = get_settings()