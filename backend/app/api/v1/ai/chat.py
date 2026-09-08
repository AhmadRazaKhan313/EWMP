"""
AI Assistant API endpoint.

Backed by real tenant data via app.services.ai_tools — the model can call
get_headcount_summary / get_attendance_summary / get_leave_summary /
get_payroll_summary / get_attrition_summary and reason over the actual
numbers instead of talking in generalities. Previously this endpoint was a
plain LLM passthrough whose system prompt admitted "you would normally
query the live database" — it never did.

Also owns the per-organization AI Configuration (provider/model/API key),
so each org can point the assistant at its own account instead of every
tenant sharing one platform-wide key from the backend's .env file. See
app.services.ai_config for the resolution order and app.core.crypto for
how the key is encrypted at rest.
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import encrypt_secret
from app.core.database import get_db
from app.core.exceptions import AIProviderError, NotFoundError
from app.models.organization import Organization
from app.models.user import User
from app.permissions.dependencies import get_current_user, get_tenant_id, require_permission
from app.services.ai_config import resolve_ai_config
from app.services.ai_tools import TOOL_REGISTRY, execute_tool

router = APIRouter(prefix="/ai", tags=["AI Assistant"])

MAX_TOOL_ROUNDTRIPS = 3
SUPPORTED_PROVIDERS = {"openai", "anthropic", "google", "ollama"}


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


class ChatResponse(BaseModel):
    response: str
    tools_used: list[str] = []


SYSTEM_PROMPT = """You are EWMP AI Assistant, an intelligent HR and workforce management assistant.
You help HR managers, admins, and employees with:
- Workforce analytics and insights (headcount, attrition, department breakdowns)
- Attendance and leave data interpretation
- Payroll summaries and cost analysis
- Policy explanations

You have tools available to pull real, live numbers from this organization's
data — always call the relevant tool before answering a question about
counts, rates, or totals rather than guessing or speaking in generalities.
Cite the actual numbers the tools return. Be concise, professional, and
data-focused. Keep responses under 300 words."""


def _anthropic_tools() -> list[dict]:
    return [
        {
            "name": name,
            "description": spec["description"],
            "input_schema": spec["parameters"],
        }
        for name, spec in TOOL_REGISTRY.items()
    ]


def _openai_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": spec["description"],
                "parameters": spec["parameters"],
            },
        }
        for name, spec in TOOL_REGISTRY.items()
    ]


async def _chat_anthropic(
    api_key: str, model: str, messages: list[dict], db: AsyncSession, tenant_id: UUID
) -> tuple[str, list[str]]:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    tools = _anthropic_tools()
    tools_used: list[str] = []
    conversation = list(messages)

    for _ in range(MAX_TOOL_ROUNDTRIPS):
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=conversation,
            tools=tools,
        )

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        if not tool_use_blocks:
            text_blocks = [b.text for b in response.content if b.type == "text"]
            return "\n".join(text_blocks), tools_used

        conversation.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in tool_use_blocks:
            tools_used.append(block.name)
            result = await execute_tool(block.name, block.input or {}, db, tenant_id)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": str(result),
            })
        conversation.append({"role": "user", "content": tool_results})

    return "I gathered the data but ran out of turns synthesizing an answer — please try rephrasing your question.", tools_used


async def _run_openai_compatible(
    client, model: str, messages: list[dict], db: AsyncSession, tenant_id: UUID
) -> tuple[str, list[str]]:
    """Shared tool-calling loop for any client speaking the OpenAI chat-completions
    wire format — used for both real OpenAI and (via a different base_url/api_key)
    local Ollama, whose /v1 endpoint is OpenAI-compatible."""
    import json as _json

    tools = _openai_tools()
    tools_used: list[str] = []
    conversation = [{"role": "system", "content": SYSTEM_PROMPT}] + list(messages)

    for _ in range(MAX_TOOL_ROUNDTRIPS):
        response = client.chat.completions.create(
            model=model,
            messages=conversation,
            tools=tools,
            max_tokens=1024,
        )
        choice = response.choices[0].message

        if not choice.tool_calls:
            return choice.content or "", tools_used

        conversation.append({
            "role": "assistant",
            "content": choice.content,
            "tool_calls": [tc.model_dump() for tc in choice.tool_calls],
        })
        for tc in choice.tool_calls:
            tools_used.append(tc.function.name)
            args = _json.loads(tc.function.arguments or "{}")
            result = await execute_tool(tc.function.name, args, db, tenant_id)
            conversation.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": str(result),
            })

    return "I gathered the data but ran out of turns synthesizing an answer — please try rephrasing your question.", tools_used


async def _chat_openai(
    api_key: str, model: str, messages: list[dict], db: AsyncSession, tenant_id: UUID
) -> tuple[str, list[str]]:
    import openai

    client = openai.OpenAI(api_key=api_key)
    return await _run_openai_compatible(client, model, messages, db, tenant_id)


async def _chat_ollama(
    base_url: str, model: str, messages: list[dict], db: AsyncSession, tenant_id: UUID
) -> tuple[str, list[str]]:
    """Ollama serves an OpenAI-compatible /v1 endpoint, so the OpenAI SDK works
    against it unmodified — only base_url changes, and the API key is a
    placeholder since local Ollama doesn't check it. Tool calling requires a
    model that supports it (e.g. llama3.1+, qwen2.5); older/smaller models
    will just answer without calling tools."""
    import openai

    normalized = base_url.rstrip("/")
    if not normalized.endswith("/v1"):
        normalized = f"{normalized}/v1"
    client = openai.OpenAI(api_key="ollama", base_url=normalized)
    return await _run_openai_compatible(client, model or "llama3.1", messages, db, tenant_id)


async def _chat_google(
    api_key: str, model: str, messages: list[dict], db: AsyncSession, tenant_id: UUID
) -> tuple[str, list[str]]:
    """Uses google-genai, the current unified SDK — google-generativeai (the
    older `import google.generativeai as genai` package) reached end of life
    and prints a FutureWarning on import; shipping the assistant on it would
    just mean redoing this the moment it's actually removed."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    tools_used: list[str] = []

    function_declarations = [
        types.FunctionDeclaration(
            name=name, description=spec["description"], parameters=spec["parameters"]
        )
        for name, spec in TOOL_REGISTRY.items()
    ]
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=[types.Tool(function_declarations=function_declarations)],
        # We drive the tool loop ourselves (execute_tool is async and
        # tenant-scoped) rather than letting the SDK call plain Python
        # functions automatically.
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    # Gemini's chat API keeps prior turns separate from the newest message:
    # everything but the last message seeds the chat's history, the last
    # message is what gets sent.
    history = [
        types.Content(
            role="model" if m["role"] == "assistant" else "user",
            parts=[types.Part.from_text(text=m["content"])],
        )
        for m in messages[:-1]
    ]
    chat = client.chats.create(model=model or "gemini-2.0-flash", config=config, history=history)
    response = chat.send_message(messages[-1]["content"])

    for _ in range(MAX_TOOL_ROUNDTRIPS):
        calls = response.function_calls or []
        if not calls:
            break
        response_parts = []
        for call in calls:
            tools_used.append(call.name)
            args = dict(call.args) if call.args else {}
            result = await execute_tool(call.name, args, db, tenant_id)
            response_parts.append(
                types.Part.from_function_response(name=call.name, response={"result": result})
            )
        response = chat.send_message(response_parts)

    return response.text or "", tools_used


async def _dispatch_chat(
    provider: str,
    model: str,
    api_key: str | None,
    base_url: str | None,
    messages: list[dict],
    db: AsyncSession,
    tenant_id: UUID,
) -> tuple[str, list[str]]:
    """Single entry point both /ai/chat and /ai/config/test call — keeps the
    provider-specific wiring in exactly one place."""
    if provider == "anthropic":
        if not api_key:
            raise AIProviderError("Anthropic API key not configured")
        m = model if model and model.startswith("claude") else "claude-sonnet-5"
        return await _chat_anthropic(api_key, m, messages, db, tenant_id)
    if provider == "openai":
        if not api_key:
            raise AIProviderError("OpenAI API key not configured")
        return await _chat_openai(api_key, model or "gpt-4o-mini", messages, db, tenant_id)
    if provider == "google":
        if not api_key:
            raise AIProviderError("Google AI API key not configured")
        return await _chat_google(api_key, model or "gemini-1.5-flash", messages, db, tenant_id)
    if provider == "ollama":
        return await _chat_ollama(base_url or settings.OLLAMA_BASE_URL, model, messages, db, tenant_id)
    raise AIProviderError(f"Unsupported AI provider: {provider!r}")


@router.post("/chat", response_model=ChatResponse, summary="Chat with AI assistant")
async def chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """Send a message to the AI assistant and receive a data-grounded response."""

    messages = [{"role": m.role, "content": m.content} for m in request.history]
    messages.append({"role": "user", "content": request.message})

    cfg = await resolve_ai_config(db, tenant_id)

    if cfg.provider != "ollama" and not cfg.api_key:
        return ChatResponse(
            response=(
                "AI Assistant is not configured. Please add your API key in Settings → "
                "AI Configuration. Supported providers: OpenAI, Anthropic Claude, Google Gemini, Ollama."
            ),
            tools_used=[],
        )

    try:
        content, tools_used = await _dispatch_chat(
            cfg.provider, cfg.model, cfg.api_key, cfg.base_url, messages, db, tenant_id
        )
        return ChatResponse(response=content, tools_used=tools_used)

    except AIProviderError:
        raise
    except Exception as exc:
        raise AIProviderError(f"AI provider error: {str(exc)}") from exc


# ── Per-organization AI Configuration ───────────────────────────────────────


class AIConfigOut(BaseModel):
    provider: str
    model: str
    base_url: str | None = None
    has_api_key: bool
    api_key_preview: str | None = None
    using_platform_default: bool


class AIConfigUpdate(BaseModel):
    provider: str
    model: str
    api_key: str | None = None
    base_url: str | None = None

    @field_validator("provider")
    @classmethod
    def _valid_provider(cls, v: str) -> str:
        if v not in SUPPORTED_PROVIDERS:
            raise ValueError(f"provider must be one of {sorted(SUPPORTED_PROVIDERS)}")
        return v


class AIConfigTest(BaseModel):
    provider: str
    model: str
    api_key: str | None = None
    base_url: str | None = None

    @field_validator("provider")
    @classmethod
    def _valid_provider(cls, v: str) -> str:
        if v not in SUPPORTED_PROVIDERS:
            raise ValueError(f"provider must be one of {sorted(SUPPORTED_PROVIDERS)}")
        return v


class AIConfigTestResult(BaseModel):
    ok: bool
    message: str


def _preview(raw_key: str) -> str:
    if len(raw_key) <= 8:
        return "•" * len(raw_key)
    return f"{raw_key[:4]}{'•' * 6}{raw_key[-4:]}"


async def _get_org_or_404(db: AsyncSession, tenant_id: UUID) -> Organization:
    org = await db.get(Organization, tenant_id)
    if org is None:
        raise NotFoundError("Organization not found")
    return org


def _build_config_out(org: Organization) -> AIConfigOut:
    ai_cfg = (org.settings or {}).get("ai") or {}
    if not ai_cfg.get("provider"):
        return AIConfigOut(
            provider=settings.DEFAULT_AI_PROVIDER,
            model=settings.DEFAULT_AI_MODEL,
            base_url=None,
            has_api_key=False,
            api_key_preview=None,
            using_platform_default=True,
        )

    encrypted = ai_cfg.get("api_key_encrypted")
    preview = None
    if encrypted:
        from app.core.crypto import decrypt_secret
        try:
            preview = _preview(decrypt_secret(encrypted))
        except ValueError:
            preview = None

    return AIConfigOut(
        provider=ai_cfg["provider"],
        model=ai_cfg.get("model") or settings.DEFAULT_AI_MODEL,
        base_url=ai_cfg.get("base_url"),
        has_api_key=bool(encrypted),
        api_key_preview=preview,
        using_platform_default=False,
    )


@router.get(
    "/config",
    response_model=AIConfigOut,
    summary="Get this organization's AI Assistant configuration",
)
async def get_ai_config(
    current_user: User = Depends(require_permission("settings.view")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> AIConfigOut:
    org = await _get_org_or_404(db, tenant_id)
    return _build_config_out(org)


@router.patch(
    "/config",
    response_model=AIConfigOut,
    summary="Update this organization's AI Assistant configuration",
)
async def update_ai_config(
    body: AIConfigUpdate,
    current_user: User = Depends(require_permission("settings.manage")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> AIConfigOut:
    org = await _get_org_or_404(db, tenant_id)

    # Reassign (rather than mutate in place) so SQLAlchemy's change-tracking
    # on the JSON column actually notices the update.
    org_settings = dict(org.settings or {})
    ai_cfg = dict(org_settings.get("ai") or {})

    ai_cfg["provider"] = body.provider
    ai_cfg["model"] = body.model
    ai_cfg["base_url"] = body.base_url or None

    if body.api_key:
        ai_cfg["api_key_encrypted"] = encrypt_secret(body.api_key)
    elif body.provider == "ollama":
        # Local Ollama needs no key — clear any stale one left over from a
        # previously configured provider.
        ai_cfg.pop("api_key_encrypted", None)
    # else: no new key was typed in, keep whatever is already stored.

    org_settings["ai"] = ai_cfg
    org.settings = org_settings
    await db.commit()
    await db.refresh(org)

    return _build_config_out(org)


@router.delete(
    "/config",
    response_model=AIConfigOut,
    summary="Reset this organization back to the platform-default AI configuration",
)
async def reset_ai_config(
    current_user: User = Depends(require_permission("settings.manage")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> AIConfigOut:
    org = await _get_org_or_404(db, tenant_id)
    org_settings = dict(org.settings or {})
    org_settings.pop("ai", None)
    org.settings = org_settings
    await db.commit()
    await db.refresh(org)
    return _build_config_out(org)


@router.post(
    "/config/test",
    response_model=AIConfigTestResult,
    summary="Test an AI provider connection before saving it",
)
async def test_ai_config(
    body: AIConfigTest,
    current_user: User = Depends(require_permission("settings.manage")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> AIConfigTestResult:
    api_key = body.api_key
    if not api_key and body.provider != "ollama":
        # No new key typed in the form — test against whatever is already
        # saved for this org, so "Test connection" works on an unmodified
        # existing config too.
        org = await _get_org_or_404(db, tenant_id)
        ai_cfg = (org.settings or {}).get("ai") or {}
        encrypted = ai_cfg.get("api_key_encrypted")
        if encrypted:
            from app.core.crypto import decrypt_secret
            try:
                api_key = decrypt_secret(encrypted)
            except ValueError:
                return AIConfigTestResult(ok=False, message="Stored key could not be decrypted — please re-enter it.")

    if body.provider != "ollama" and not api_key:
        return AIConfigTestResult(ok=False, message="No API key provided.")

    try:
        content, _ = await _dispatch_chat(
            body.provider,
            body.model,
            api_key,
            body.base_url,
            [{"role": "user", "content": "Reply with only the word OK."}],
            db,
            tenant_id,
        )
        return AIConfigTestResult(ok=True, message=content[:200] or "Connection succeeded.")
    except Exception as exc:
        return AIConfigTestResult(ok=False, message=str(exc)[:300])