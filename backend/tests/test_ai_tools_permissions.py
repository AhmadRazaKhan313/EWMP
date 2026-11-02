"""
Regression tests: the AI assistant must not be a side door around RBAC.

Before the fix, /ai/chat was open to any logged-in user and every tool
(payroll totals, headcount, attrition ...) ran for everyone. Now each tool is
tied to the permission the same data needs elsewhere in the API, and is both
hidden from the model and refused at execution time without it.

Run:  cd backend && pytest tests/test_ai_tools_permissions.py -v
"""

import uuid
from types import SimpleNamespace

import pytest

from app.api.v1.ai import chat as chat_module
from app.services import ai_tools
from app.services.ai_tools import TOOL_REGISTRY, execute_tool, tools_for_user

TENANT = uuid.uuid4()


def _user(*perms: str, full_access: bool = False):
    held = set(perms)
    return SimpleNamespace(has_permission=lambda code: full_access or code in held)


# ── tools_for_user ───────────────────────────────────────────────────────────
class TestToolsForUser:
    def test_every_tool_declares_a_permission(self):
        for name, spec in TOOL_REGISTRY.items():
            assert spec.get("permission"), f"{name} has no permission mapping"

    def test_plain_employee_gets_no_tools(self):
        assert tools_for_user(_user()) == frozenset()

    def test_payroll_tool_needs_payroll_view(self):
        assert "get_payroll_summary" not in tools_for_user(_user("employees.view", "attendance.view"))
        assert "get_payroll_summary" in tools_for_user(_user("payroll.view"))

    def test_each_tool_only_unlocked_by_its_own_permission(self):
        for name, spec in TOOL_REGISTRY.items():
            allowed = tools_for_user(_user(spec["permission"]))
            assert name in allowed
            others = {n for n, s in TOOL_REGISTRY.items() if s["permission"] != spec["permission"]}
            assert not (allowed & others)

    def test_owner_or_admin_with_full_access_gets_everything(self):
        assert tools_for_user(_user(full_access=True)) == frozenset(TOOL_REGISTRY)


# ── execute_tool ─────────────────────────────────────────────────────────────
class TestExecuteTool:
    @pytest.mark.asyncio
    async def test_refuses_tool_not_in_allowed_set_and_never_calls_it(self, monkeypatch):
        calls = []

        async def spy(db, tenant_id, **kw):
            calls.append(kw)
            return {"secret": "total_net=123"}

        monkeypatch.setitem(TOOL_REGISTRY["get_payroll_summary"], "fn", spy)
        result = await execute_tool(
            "get_payroll_summary", {}, db=None, tenant_id=TENANT, allowed_tools=frozenset()
        )
        assert result == {"error": "You do not have permission to access this data."}
        assert calls == []  # the query function was never reached

    @pytest.mark.asyncio
    async def test_allowed_tool_runs(self, monkeypatch):
        async def ok(db, tenant_id, **kw):
            return {"ok": True, **kw}

        monkeypatch.setitem(TOOL_REGISTRY["get_leave_summary"], "fn", ok)
        result = await execute_tool(
            "get_leave_summary", {}, db=None, tenant_id=TENANT,
            allowed_tools=frozenset({"get_leave_summary"}),
        )
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        result = await execute_tool("drop_tables", {}, None, TENANT, allowed_tools=frozenset({"drop_tables"}))
        assert "Unknown tool" in result["error"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "raw, expected",
        [(30, 30), ("45", 45), (10**9, 365), (-5, 1), (0, 1)],
    )
    async def test_days_argument_is_coerced_and_clamped(self, monkeypatch, raw, expected):
        seen = {}

        async def spy(db, tenant_id, **kw):
            seen.update(kw)
            return {}

        monkeypatch.setitem(TOOL_REGISTRY["get_attendance_summary"], "fn", spy)
        await execute_tool(
            "get_attendance_summary", {"days": raw}, None, TENANT,
            allowed_tools=frozenset({"get_attendance_summary"}),
        )
        assert seen == {"days": expected}

    @pytest.mark.asyncio
    async def test_garbage_and_extra_arguments_are_dropped(self, monkeypatch):
        seen = {"called": False}

        async def spy(db, tenant_id, **kw):
            seen["called"] = True
            seen["kw"] = kw
            return {}

        monkeypatch.setitem(TOOL_REGISTRY["get_attendance_summary"], "fn", spy)
        await execute_tool(
            "get_attendance_summary",
            {"days": "lots", "tenant_id": "someone-else", "evil": 1},
            None, TENANT, allowed_tools=frozenset({"get_attendance_summary"}),
        )
        assert seen["called"] and seen["kw"] == {}


# ── tool payload builders ────────────────────────────────────────────────────
class TestToolPayloads:
    def test_no_allowed_tools_means_no_payload(self):
        assert chat_module._anthropic_tools(frozenset()) == []
        assert chat_module._openai_tools(frozenset()) == []

    def test_only_allowed_tools_are_offered(self):
        allowed = frozenset({"get_leave_summary"})
        assert [t["name"] for t in chat_module._anthropic_tools(allowed)] == ["get_leave_summary"]
        assert [t["function"]["name"] for t in chat_module._openai_tools(allowed)] == ["get_leave_summary"]


# ── the OpenAI-style loop end to end (fake client) ───────────────────────────
class _FakeCompletions:
    """First reply asks for a tool; second reply is the final text."""

    def __init__(self, tool_name):
        self.tool_name = tool_name
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            tc = SimpleNamespace(
                id="call_1",
                function=SimpleNamespace(name=self.tool_name, arguments="{}"),
                model_dump=lambda: {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": self.tool_name, "arguments": "{}"},
                },
            )
            msg = SimpleNamespace(content=None, tool_calls=[tc])
        else:
            msg = SimpleNamespace(content="done", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


class TestOpenAILoop:
    @pytest.mark.asyncio
    async def test_model_asking_for_forbidden_tool_gets_permission_error(self, monkeypatch):
        ran = []

        async def spy(db, tenant_id, **kw):
            ran.append(1)
            return {"total_net": "999999"}

        monkeypatch.setitem(TOOL_REGISTRY["get_payroll_summary"], "fn", spy)
        comps = _FakeCompletions("get_payroll_summary")
        client = SimpleNamespace(chat=SimpleNamespace(completions=comps))

        text, used = await chat_module._run_openai_compatible(
            client, "m", [{"role": "user", "content": "what is our payroll?"}], None, TENANT,
            allowed_tools=frozenset(),  # a plain employee
        )

        assert text == "done"
        assert ran == []  # payroll query never executed
        assert "tools" not in comps.calls[0]  # nothing offered -> param omitted entirely
        tool_msg = [m for m in comps.calls[1]["messages"] if m.get("role") == "tool"][0]
        assert "do not have permission" in tool_msg["content"]
        assert "999999" not in tool_msg["content"]

    @pytest.mark.asyncio
    async def test_permitted_user_still_gets_the_data(self, monkeypatch):
        async def spy(db, tenant_id, **kw):
            return {"total_net": "1234"}

        monkeypatch.setitem(TOOL_REGISTRY["get_payroll_summary"], "fn", spy)
        comps = _FakeCompletions("get_payroll_summary")
        client = SimpleNamespace(chat=SimpleNamespace(completions=comps))

        await chat_module._run_openai_compatible(
            client, "m", [{"role": "user", "content": "payroll?"}], None, TENANT,
            allowed_tools=frozenset({"get_payroll_summary"}),
        )
        assert [t["function"]["name"] for t in comps.calls[0]["tools"]] == ["get_payroll_summary"]
        tool_msg = [m for m in comps.calls[1]["messages"] if m.get("role") == "tool"][0]
        assert "1234" in tool_msg["content"]


# ── the endpoint wires the current user's permissions through ────────────────
class TestChatEndpoint:
    @pytest.mark.asyncio
    async def test_endpoint_passes_only_the_users_tools(self, monkeypatch):
        captured = {}

        async def fake_config(db, tenant_id):
            return SimpleNamespace(provider="ollama", api_key=None, model="m", base_url=None)

        async def fake_dispatch(*args, **kwargs):
            captured.update(kwargs)
            return "hi", []

        monkeypatch.setattr(chat_module, "resolve_ai_config", fake_config)
        monkeypatch.setattr(chat_module, "_dispatch_chat", fake_dispatch)

        req = chat_module.ChatRequest(message="hello", history=[])
        await chat_module.chat(req, _user("leave.view"), TENANT, None)
        assert captured["allowed_tools"] == frozenset({"get_leave_summary"})

        await chat_module.chat(req, _user(), TENANT, None)
        assert captured["allowed_tools"] == frozenset()

    @pytest.mark.asyncio
    async def test_dispatch_defaults_to_no_tools(self, monkeypatch):
        """Fail-closed: a caller that forgets allowed_tools gets none."""
        seen = {}

        async def fake_ollama(base_url, model, messages, db, tenant_id, allowed_tools=frozenset("SENTINEL")):
            seen["allowed"] = allowed_tools
            return "x", []

        monkeypatch.setattr(chat_module, "_chat_ollama", fake_ollama)
        await chat_module._dispatch_chat("ollama", "m", None, "http://x", [], db=None, tenant_id=TENANT)
        assert seen["allowed"] == frozenset()
