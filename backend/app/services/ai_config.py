"""
Resolve which AI provider/model/key/base_url the AI Assistant should use
for a given organization.

Priority:
  1. Organization.settings["ai"] — set via Settings → AI Configuration
     (app/api/v1/ai/chat.py config endpoints). Each org can point the
     assistant at its own OpenAI / Anthropic / Google / Ollama account.
  2. The platform-wide default from environment variables
     (DEFAULT_AI_PROVIDER / *_API_KEY). This is the entire pre-existing
     behavior, kept as the fallback so organizations that never touch the
     new settings screen keep working exactly as before.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import decrypt_secret
from app.models.organization import Organization


@dataclass
class ResolvedAIConfig:
    provider: str
    model: str
    api_key: str | None
    base_url: str | None
    using_platform_default: bool


def _platform_default_key(provider: str) -> str | None:
    return {
        "openai": settings.OPENAI_API_KEY,
        "anthropic": settings.ANTHROPIC_API_KEY,
        "google": settings.GOOGLE_AI_API_KEY,
        "ollama": None,  # local — no key needed
    }.get(provider) or None


async def resolve_ai_config(db: AsyncSession, tenant_id: UUID) -> ResolvedAIConfig:
    org = await db.get(Organization, tenant_id)
    ai_cfg = (org.settings or {}).get("ai") if org else None

    if ai_cfg and ai_cfg.get("provider"):
        provider = ai_cfg["provider"]
        api_key = None
        encrypted = ai_cfg.get("api_key_encrypted")
        if encrypted:
            try:
                api_key = decrypt_secret(encrypted)
            except ValueError:
                # Corrupted/undecryptable stored key — treat as unset rather
                # than 500ing every chat request for this org.
                api_key = None
        return ResolvedAIConfig(
            provider=provider,
            model=ai_cfg.get("model") or settings.DEFAULT_AI_MODEL,
            api_key=api_key,
            base_url=ai_cfg.get("base_url") or (settings.OLLAMA_BASE_URL if provider == "ollama" else None),
            using_platform_default=False,
        )

    provider = settings.DEFAULT_AI_PROVIDER
    return ResolvedAIConfig(
        provider=provider,
        model=settings.DEFAULT_AI_MODEL,
        api_key=_platform_default_key(provider),
        base_url=settings.OLLAMA_BASE_URL if provider == "ollama" else None,
        using_platform_default=True,
    )