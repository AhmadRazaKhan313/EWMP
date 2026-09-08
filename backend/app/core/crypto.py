"""
Symmetric encryption for secrets stored at rest.

Currently used for one thing: per-organization AI provider API keys saved
via Settings → AI Configuration (app/api/v1/ai/chat.py). Before this
existed, the only way to configure the AI Assistant was the platform-wide
OPENAI_API_KEY / ANTHROPIC_API_KEY in the backend's own .env — every tenant
shared one key. Org-level keys need to live in the database, and a key
sitting in plaintext in Organization.settings (a JSON column any DB dump or
backup exposes) would repeat the exact mistake flagged elsewhere in this
codebase (the agent token stored in a plaintext, world-readable file).

Uses Fernet (AES-128-CBC + HMAC, from the `cryptography` package) keyed off
SECRET_KEY so no new secret needs to be provisioned or rotated separately —
SECRET_KEY already gets the same operational care as JWT signing.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet() -> Fernet:
    # Fernet requires a 32-byte urlsafe-base64-encoded key. Derive one
    # deterministically from SECRET_KEY rather than requiring a second
    # secret to be generated and kept in sync across environments.
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret for storage. Returns an opaque, ASCII-safe string."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a secret previously produced by encrypt_secret.

    Raises:
        ValueError: if the ciphertext is malformed, was encrypted under a
            different SECRET_KEY, or has been tampered with.
    """
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Could not decrypt stored secret — it may be corrupted or was encrypted under a different SECRET_KEY") from exc