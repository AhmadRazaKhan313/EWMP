"""
Tests for the AI Assistant "completion" work:

  1. Per-organization AI Configuration (Organization.settings["ai"]) takes
     priority over the platform-wide .env default, and falls back cleanly
     when an org hasn't configured anything.
  2. API keys are encrypted at rest (app.core.crypto) and a tampered/undecryptable
     stored key degrades to "not configured" instead of 500ing every chat request.
  3. _dispatch_chat refuses to call out to a provider with no key, and rejects
     unknown providers, before any network call is attempted.
  4. AIConfigUpdate rejects providers outside the supported set.

Deliberately DB-free (fake session with only the `.get()` method resolve_ai_config
actually calls) — same pattern as test_employee_create_no_lazy_load.py.

Run:  cd backend && pytest tests/test_ai_assistant_config.py -v
"""

import uuid

import pytest
from pydantic import ValidationError

from app.core.crypto import decrypt_secret, encrypt_secret
from app.models.organization import Organization


# ── Crypto round trip ────────────────────────────────────────────────────────

def test_encrypt_decrypt_round_trip():
    secret = "sk-ant-super-secret-1234567890"
    ciphertext = encrypt_secret(secret)
    assert ciphertext != secret
    assert decrypt_secret(ciphertext) == secret


def test_decrypt_rejects_tampered_ciphertext():
    ciphertext = encrypt_secret("sk-ant-super-secret")
    tampered = ciphertext[:-4] + "abcd"
    with pytest.raises(ValueError):
        decrypt_secret(tampered)


def test_decrypt_rejects_garbage():
    with pytest.raises(ValueError):
        decrypt_secret("not-a-real-fernet-token")


# ── resolve_ai_config ─────────────────────────────────────────────────────────

class _FakeSession:
    """Stands in for AsyncSession — resolve_ai_config only ever calls .get()."""

    def __init__(self, org: Organization | None):
        self._org = org

    async def get(self, model, id):  # noqa: A002 - matches AsyncSession.get signature
        return self._org


def _org(settings_dict: dict | None = None) -> Organization:
    return Organization(
        id=uuid.uuid4(),
        name="Acme Inc",
        slug="acme",
        email="admin@acme.test",
        settings=settings_dict or {},
    )


@pytest.mark.asyncio
async def test_resolve_falls_back_to_platform_default_when_org_unconfigured(monkeypatch):
    from app.services import ai_config

    monkeypatch.setattr(ai_config.settings, "DEFAULT_AI_PROVIDER", "openai")
    monkeypatch.setattr(ai_config.settings, "DEFAULT_AI_MODEL", "gpt-4o-mini")
    monkeypatch.setattr(ai_config.settings, "OPENAI_API_KEY", "platform-wide-key")

    db = _FakeSession(_org())  # no "ai" key in settings at all
    cfg = await ai_config.resolve_ai_config(db, uuid.uuid4())

    assert cfg.using_platform_default is True
    assert cfg.provider == "openai"
    assert cfg.api_key == "platform-wide-key"


@pytest.mark.asyncio
async def test_resolve_prefers_org_config_over_platform_default(monkeypatch):
    from app.services import ai_config

    monkeypatch.setattr(ai_config.settings, "DEFAULT_AI_PROVIDER", "openai")
    monkeypatch.setattr(ai_config.settings, "OPENAI_API_KEY", "platform-wide-key")

    encrypted = encrypt_secret("org-own-anthropic-key")
    db = _FakeSession(_org({
        "ai": {"provider": "anthropic", "model": "claude-sonnet-5", "api_key_encrypted": encrypted}
    }))
    cfg = await ai_config.resolve_ai_config(db, uuid.uuid4())

    assert cfg.using_platform_default is False
    assert cfg.provider == "anthropic"
    assert cfg.model == "claude-sonnet-5"
    assert cfg.api_key == "org-own-anthropic-key"


@pytest.mark.asyncio
async def test_resolve_ollama_needs_no_key_and_uses_base_url(monkeypatch):
    from app.services import ai_config

    monkeypatch.setattr(ai_config.settings, "OLLAMA_BASE_URL", "http://localhost:11434")

    db = _FakeSession(_org({"ai": {"provider": "ollama", "model": "llama3.1"}}))
    cfg = await ai_config.resolve_ai_config(db, uuid.uuid4())

    assert cfg.provider == "ollama"
    assert cfg.api_key is None
    assert cfg.base_url == "http://localhost:11434"


@pytest.mark.asyncio
async def test_resolve_degrades_gracefully_on_corrupted_stored_key():
    from app.services import ai_config

    db = _FakeSession(_org({
        "ai": {"provider": "openai", "model": "gpt-4o-mini", "api_key_encrypted": "garbage-not-fernet"}
    }))
    cfg = await ai_config.resolve_ai_config(db, uuid.uuid4())

    # Must not raise — a corrupted key degrades to "not configured", not a 500.
    assert cfg.api_key is None
    assert cfg.provider == "openai"


@pytest.mark.asyncio
async def test_resolve_missing_organization_falls_back_to_platform_default(monkeypatch):
    from app.services import ai_config

    monkeypatch.setattr(ai_config.settings, "DEFAULT_AI_PROVIDER", "anthropic")
    monkeypatch.setattr(ai_config.settings, "ANTHROPIC_API_KEY", "")

    db = _FakeSession(None)  # org lookup returned nothing
    cfg = await ai_config.resolve_ai_config(db, uuid.uuid4())

    assert cfg.using_platform_default is True
    assert cfg.api_key is None  # empty platform key normalizes to None, not ""


# ── AIConfigUpdate validation ─────────────────────────────────────────────────

def test_ai_config_update_rejects_unsupported_provider():
    from app.api.v1.ai.chat import AIConfigUpdate

    with pytest.raises(ValidationError):
        AIConfigUpdate(provider="not-a-real-provider", model="whatever")


def test_ai_config_update_accepts_each_supported_provider():
    from app.api.v1.ai.chat import AIConfigUpdate, SUPPORTED_PROVIDERS

    for provider in SUPPORTED_PROVIDERS:
        cfg = AIConfigUpdate(provider=provider, model="m")
        assert cfg.provider == provider


# ── _dispatch_chat guard rails (no network reached) ───────────────────────────

@pytest.mark.asyncio
async def test_dispatch_chat_rejects_unsupported_provider():
    from app.api.v1.ai.chat import _dispatch_chat
    from app.core.exceptions import AIProviderError

    with pytest.raises(AIProviderError):
        await _dispatch_chat("carrier-pigeon", "m", "key", None, [], db=None, tenant_id=uuid.uuid4())


@pytest.mark.parametrize("provider", ["anthropic", "openai", "google"])
@pytest.mark.asyncio
async def test_dispatch_chat_requires_api_key_for_hosted_providers(provider):
    from app.api.v1.ai.chat import _dispatch_chat
    from app.core.exceptions import AIProviderError

    with pytest.raises(AIProviderError):
        await _dispatch_chat(provider, "m", None, None, [], db=None, tenant_id=uuid.uuid4())


# ── Key preview masking ───────────────────────────────────────────────────────

def test_preview_masks_long_key_showing_only_first_and_last_four():
    from app.api.v1.ai.chat import _preview

    assert _preview("sk-ant-1234567890abcdef") == "sk-a••••••cdef"


def test_preview_fully_masks_short_key():
    from app.api.v1.ai.chat import _preview

    assert _preview("short") == "•" * 5


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))