"""
Organisation settings for the caller's own organisation — audit finding H-17.

There used to be no endpoint that could change an organisation after
registration: its timezone, currency, contact details and work hours were
frozen at sign-up, and the Settings → General screen was a mock whose Save
button did nothing.

  GET   /organization   any signed-in member (timezone, currency, work week
                        and hours are needed to display things correctly)
  PATCH /organization   settings.manage

Only a fixed set of fields is ever read or written. `Organization.settings`
is a JSON blob shared with other features (e.g. settings["ai"] holds the
organisation's ENCRYPTED AI provider key), so it is never returned as-is and
updates MERGE the known keys into it instead of replacing it.

Stored under `settings`:
  work_days                    ["mon", ..., "sun"] — same format as Shift.work_days
  standard_work_hours_per_day  number — already read by leave (hourly leave
                               → day conversion)

Slug, limits, trial/billing state and feature flags are NOT editable here:
the slug is the organisation's URL identity, and the rest are platform
concerns.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models.organization import Organization
from app.models.user import User
from app.permissions.dependencies import get_current_user, get_tenant_id, require_permission
from app.services.organization_logo import read_logo, remove_logo, store_logo

router = APIRouter(prefix="/organization", tags=["Organization"])

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DEFAULT_WORK_DAYS = ["mon", "tue", "wed", "thu", "fri"]
DEFAULT_HOURS_PER_DAY = 8.0

# Columns that may never be set to null (NOT NULL in the table, or
# meaningless when empty). Sending `null` for one of these is a 422, not a
# database error.
_NOT_NULLABLE = {"name", "email", "timezone", "currency", "work_days", "standard_work_hours_per_day"}


class OrganizationSettingsResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    email: str
    phone: str | None
    website: str | None
    country: str | None
    timezone: str
    currency: str
    work_days: list[str]
    standard_work_hours_per_day: float
    logo_url: str | None = None


class OrganizationSettingsUpdate(BaseModel):
    """Partial update — send only the fields that change."""

    name: str | None = Field(None, min_length=1, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=50)
    website: str | None = Field(None, max_length=255)
    country: str | None = Field(None, max_length=100)
    timezone: str | None = Field(None, max_length=100)
    currency: str | None = None
    work_days: list[str] | None = None
    standard_work_hours_per_day: float | None = Field(None, gt=0, le=24)

    @model_validator(mode="before")
    @classmethod
    def _reject_nulls_for_required_fields(cls, data):
        if isinstance(data, dict):
            nulled = sorted(k for k in _NOT_NULLABLE if k in data and data[k] is None)
            if nulled:
                raise ValueError(f"These fields cannot be empty: {', '.join(nulled)}")
        return data

    @field_validator("name", "phone", "country", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("website")
    @classmethod
    def _website_is_http(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not v.lower().startswith(("http://", "https://")):
            raise ValueError("website must start with http:// or https://")
        return v

    @field_validator("timezone")
    @classmethod
    def _valid_iana_timezone(cls, v: str | None) -> str | None:
        """Must be an IANA name ("Asia/Karachi"). An invalid value would make
        every timezone-aware computation silently fall back to UTC."""
        if v is None:
            return v
        v = v.strip()
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"'{v}' is not a valid IANA timezone (e.g. Asia/Karachi)")
        return v

    @field_validator("currency")
    @classmethod
    def _iso_currency(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", v):
            raise ValueError("currency must be a 3-letter ISO 4217 code (e.g. PKR, USD)")
        return v

    @field_validator("work_days")
    @classmethod
    def _valid_work_days(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        days = {d.strip().lower() for d in v}
        unknown = sorted(days - set(WEEKDAYS))
        if unknown:
            raise ValueError(f"Unknown day(s): {', '.join(unknown)} — use mon..sun")
        if not days:
            raise ValueError("At least one working day is required")
        return [d for d in WEEKDAYS if d in days]  # canonical Mon→Sun order, no duplicates


def _hours_from_settings(org_settings: dict) -> float:
    raw = org_settings.get("standard_work_hours_per_day")
    try:
        value = float(raw)
        return value if value > 0 else DEFAULT_HOURS_PER_DAY
    except (TypeError, ValueError):
        return DEFAULT_HOURS_PER_DAY


def _serialize(org: Organization) -> OrganizationSettingsResponse:
    org_settings = org.settings or {}
    work_days = org_settings.get("work_days")
    if not isinstance(work_days, list) or not work_days:
        work_days = DEFAULT_WORK_DAYS
    return OrganizationSettingsResponse(
        id=org.id, name=org.name, slug=org.slug, email=org.email,
        phone=org.phone, website=org.website, country=org.country,
        timezone=org.timezone, currency=org.currency,
        work_days=list(work_days),
        standard_work_hours_per_day=_hours_from_settings(org_settings),
        logo_url=org.logo_url,
    )


async def _load(db: AsyncSession, tenant_id: uuid.UUID) -> Organization:
    org = (
        await db.execute(
            select(Organization).where(
                Organization.id == tenant_id,
                Organization.is_deleted == False,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if org is None:
        raise NotFoundError("Organization not found")
    return org


@router.get("", response_model=OrganizationSettingsResponse, summary="Get my organization's settings")
async def get_organization_settings(
    current_user: User = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> OrganizationSettingsResponse:
    return _serialize(await _load(db, tenant_id))


@router.patch("", response_model=OrganizationSettingsResponse, summary="Update my organization's settings")
async def update_organization_settings(
    body: OrganizationSettingsUpdate,
    current_user: User = Depends(require_permission("settings.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> OrganizationSettingsResponse:
    """Changing the timezone affects everything computed from now on (e.g.
    which calendar day a check-in belongs to); records already stored are
    not re-dated."""
    org = await _load(db, tenant_id)
    changes = body.model_dump(exclude_unset=True)

    for column in ("name", "email", "phone", "website", "country", "timezone", "currency"):
        if column in changes:
            setattr(org, column, changes[column])

    json_changes = {k: changes[k] for k in ("work_days", "standard_work_hours_per_day") if k in changes}
    if json_changes:
        # Reassign a NEW dict: SQLAlchemy doesn't detect in-place mutation of
        # a plain JSON column, and other keys (settings["ai"], …) must survive.
        org.settings = {**(org.settings or {}), **json_changes}

    await db.flush()
    return _serialize(org)


# ── Logo (O-01) ──────────────────────────────────────────────────────────────

@router.post("/logo", response_model=OrganizationSettingsResponse, summary="Upload the organization logo")
async def upload_organization_logo(
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission("settings.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> OrganizationSettingsResponse:
    """PNG, JPEG, WebP or SVG up to 2 MB. The file's real bytes are checked."""
    org = await _load(db, tenant_id)
    org.logo_url = await store_logo(org.id, await file.read())
    await db.flush()
    return _serialize(org)


@router.delete("/logo", response_model=OrganizationSettingsResponse, summary="Remove the organization logo")
async def delete_organization_logo(
    current_user: User = Depends(require_permission("settings.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> OrganizationSettingsResponse:
    org = await _load(db, tenant_id)
    await remove_logo(org.id)
    org.logo_url = None
    await db.flush()
    return _serialize(org)


@router.get("/logo/{org_id}", summary="Serve an organization's logo image (public, like avatars)")
async def serve_organization_logo(
    org_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)
) -> Response:
    """Unauthenticated on purpose: a logo is not sensitive and has to work in a
    plain <img src>. SVG is served with a CSP that forbids scripts and sandboxes
    the document, and every type with nosniff."""
    org = (
        await db.execute(
            select(Organization).where(Organization.id == org_id, Organization.is_deleted == False)  # noqa: E712
        )
    ).scalar_one_or_none()
    found = await read_logo(org_id) if org is not None and org.logo_url else None
    if found is None:
        raise NotFoundError("Logo not found")
    content, mime = found
    # Revalidate on every use (cheap 304) so a replaced logo shows up
    # immediately in the sidebar, which has no ?v= to bust the cache with.
    etag = '"' + hashlib.sha256(content).hexdigest()[:32] + '"'
    headers = {
        "ETag": etag,
        "Cache-Control": "no-cache",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=content, media_type=mime, headers=headers)
