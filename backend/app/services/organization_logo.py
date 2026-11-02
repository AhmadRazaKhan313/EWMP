"""
Organization logo (O-01).

Modelled on the employee avatar service, with the extra care a logo needs:

  * the file's real bytes decide its type (PNG / JPEG / WebP / SVG), never the
    ``Content-Type`` the browser claims;
  * SVG is the dangerous one (it is XML that can carry <script>, event
    handlers and external references), so an SVG is only accepted if it has no
    DOCTYPE/ENTITY, no script-like elements, no ``on*`` attributes, and no
    reference to anything but an internal ``#id`` or an embedded raster image.
    It is also served with a locked-down Content-Security-Policy;
  * an older logo with a different extension is deleted, because the serving
    route tries the extensions in a fixed order and a leftover ``.png`` would
    keep being shown after a new ``.svg`` was uploaded;
  * the stored URL carries ``?v=<time>`` so browsers fetch the new picture.
"""
from __future__ import annotations

import io
import re
import time
import uuid
import xml.etree.ElementTree as ET

from app.core.exceptions import BadRequestError
from app.core.storage import get_storage

MAX_LOGO_BYTES = 2 * 1024 * 1024
MAX_SVG_BYTES = 512 * 1024
EXTENSIONS = ("png", "jpg", "webp", "svg")
MIME = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp", "svg": "image/svg+xml"}

_FORBIDDEN_TAGS = {
    "script", "foreignobject", "iframe", "embed", "object", "audio", "video",
    "animate", "animatemotion", "animatetransform", "set", "handler", "listener", "link", "meta",
}
_SAFE_DATA_URI = re.compile(r"^data:image/(png|jpe?g|webp);base64,[A-Za-z0-9+/=\s]+$", re.I)
_EXTERNAL_URL = re.compile(r"url\(\s*['\"]?\s*(?!#)", re.I)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def validate_svg(content: bytes) -> None:
    """Raise BadRequestError unless this is a plain, self-contained SVG."""
    if len(content) > MAX_SVG_BYTES:
        raise BadRequestError("SVG logo is too large (limit 512 KB)")
    upper = content.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise BadRequestError("This SVG is not allowed (it contains a DOCTYPE or entity)")
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        raise BadRequestError("Logo is not a valid SVG file")
    if _local(root.tag) != "svg":
        raise BadRequestError("Logo is not a valid SVG file")

    for el in root.iter():
        if not isinstance(el.tag, str):  # comments / processing instructions
            continue
        name = _local(el.tag)
        if name in _FORBIDDEN_TAGS:
            raise BadRequestError(f"This SVG is not allowed (it contains <{name}>)")
        if name == "style" and ("@import" in (el.text or "").lower() or _EXTERNAL_URL.search(el.text or "")):
            raise BadRequestError("This SVG is not allowed (its style loads something external)")
        for attr, value in el.attrib.items():
            key = _local(attr)
            compact = re.sub(r"\s+", "", value).lower()
            if key.startswith("on"):
                raise BadRequestError("This SVG is not allowed (it contains an event handler)")
            if "javascript:" in compact or "vbscript:" in compact:
                raise BadRequestError("This SVG is not allowed (it contains a script link)")
            if key == "href" and not (value.startswith("#") or _SAFE_DATA_URI.match(value.strip())):
                raise BadRequestError("This SVG is not allowed (it links to something outside the file)")
            if key == "style" and _EXTERNAL_URL.search(value):
                raise BadRequestError("This SVG is not allowed (its style loads something external)")


def detect_logo_type(content: bytes) -> str | None:
    """'png' / 'jpg' / 'webp' / 'svg' from the file's own bytes, else None."""
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if len(content) > 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "webp"
    head = content[:2048].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if head.startswith((b"<?xml", b"<svg")) and b"<svg" in content[:4096].lower():
        return "svg"
    return None


def logo_url_for(org_id: uuid.UUID) -> str:
    return f"/api/v1/organization/logo/{org_id}?v={int(time.time())}"


def _key(org_id: uuid.UUID, ext: str) -> str:
    return f"org-logos/{org_id}.{ext}"


async def store_logo(org_id: uuid.UUID, content: bytes) -> str:
    """Validate and save; returns the URL to store on the organization."""
    if not content:
        raise BadRequestError("Empty logo upload")
    if len(content) > MAX_LOGO_BYTES:
        raise BadRequestError("Logo exceeds the 2 MB upload limit")
    ext = detect_logo_type(content)
    if ext is None:
        raise BadRequestError("Logo must be a PNG, JPEG, WebP or SVG image")
    if ext == "svg":
        validate_svg(content)

    await get_storage().save(_key(org_id, ext), content)
    for other in EXTENSIONS:
        if other != ext:
            await _delete_quietly(_key(org_id, other))
    return logo_url_for(org_id)


async def remove_logo(org_id: uuid.UUID) -> None:
    for ext in EXTENSIONS:
        await _delete_quietly(_key(org_id, ext))


async def read_logo(org_id: uuid.UUID) -> tuple[bytes, str] | None:
    """(bytes, mime) of the stored logo, or None."""
    storage = get_storage()
    for ext in EXTENSIONS:
        try:
            return await storage.read(_key(org_id, ext)), MIME[ext]
        except Exception:
            continue
    return None


async def logo_for_pdf(org_id: uuid.UUID) -> bytes | None:
    """The logo as PNG/JPEG bytes the PDF library can embed, or None.

    WebP is converted with Pillow. SVG is left out of PDFs (no vector support
    in the PDF library); the payslip then simply has no logo.
    """
    found = await read_logo(org_id)
    if found is None:
        return None
    content, mime = found
    if mime in ("image/png", "image/jpeg"):
        return content
    if mime == "image/webp":
        try:
            from PIL import Image

            out = io.BytesIO()
            Image.open(io.BytesIO(content)).convert("RGBA").save(out, format="PNG")
            return out.getvalue()
        except Exception:
            return None
    return None


async def _delete_quietly(key: str) -> None:
    try:
        await get_storage().delete(key)
    except Exception:
        pass
