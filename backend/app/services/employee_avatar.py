"""
Profile photo for an employee (stored on the linked User, so the sidebar,
top bar and employee list all show it).

Same storage key and public URL as the self-service ``/auth/me/avatar`` upload
(``avatars/<user_id>.<ext>`` served by ``/auth/avatar/<user_id>``), with three
differences that matter once HR uploads photos for other people:

  * the file's real bytes are checked, not just the ``Content-Type`` the
    client claims;
  * an older photo with a different extension is deleted — the serving route
    tries png, jpg, webp in that order, so a leftover ``.png`` would keep being
    shown after a new ``.jpg`` was uploaded;
  * the stored URL carries ``?v=<time>`` so browsers fetch the new picture
    instead of showing a cached copy of the old one.
"""

import time
import uuid

from app.core.exceptions import BadRequestError
from app.core.storage import get_storage

MAX_AVATAR_BYTES = 5 * 1024 * 1024
_EXTENSIONS = ("png", "jpg", "webp")


def detect_image_type(content: bytes) -> str | None:
    """'png' / 'jpg' / 'webp' from the file's own signature, else None."""
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if len(content) > 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "webp"
    return None


def avatar_url_for(user_id: uuid.UUID) -> str:
    return f"/api/v1/auth/avatar/{user_id}?v={int(time.time())}"


async def store_avatar(user_id: uuid.UUID, content: bytes) -> str:
    """Validate and save; returns the URL to store on the user."""
    if not content:
        raise BadRequestError("Empty image upload")
    if len(content) > MAX_AVATAR_BYTES:
        raise BadRequestError("Photo exceeds the 5 MB upload limit")
    ext = detect_image_type(content)
    if ext is None:
        raise BadRequestError("Photo must be a PNG, JPEG or WebP image")

    storage = get_storage()
    await storage.save(f"avatars/{user_id}.{ext}", content)
    for other in _EXTENSIONS:
        if other != ext:
            await _delete_quietly(f"avatars/{user_id}.{other}")
    return avatar_url_for(user_id)


async def remove_avatar(user_id: uuid.UUID) -> None:
    for ext in _EXTENSIONS:
        await _delete_quietly(f"avatars/{user_id}.{ext}")


async def _delete_quietly(key: str) -> None:
    try:
        await get_storage().delete(key)
    except Exception:
        # Not there (or the backend can't tell us) — nothing to clean up.
        pass
