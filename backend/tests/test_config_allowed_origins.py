"""
Regression tests: `ALLOWED_ORIGINS` must parse from a real .env file the way
its own field_validator promises — JSON array OR comma-separated — instead of
crashing before that validator ever runs.

Root cause: pydantic-settings tries its own `json.loads()` on any environment
value feeding a `list[str]` field BEFORE `parse_cors_origins()` in config.py
gets a chance to run. That made the validator's documented comma-separated
fallback ("a,b" -> ["a", "b"]) unreachable dead code, and made even a
byte-perfect JSON array fragile: the app failed to start (SettingsError) the
moment the value picked up one stray byte — a trailing Windows \\r, or text
reshaped by docker-compose's own `${VAR}` substitution.

The fix adds `NoDecode` so the raw string always reaches the validator, which
now handles both formats and strips stray whitespace/\\r defensively.

Run:  cd backend && pytest tests/test_config_allowed_origins.py -v
"""

import os

import pytest


def _settings_with(raw_value):
    """Build a fresh Settings instance as if ALLOWED_ORIGINS=<raw_value> were
    the only thing set via the environment, isolated from the real os.environ
    and from pydantic-settings' internal @lru_cache on get_settings()."""
    import importlib

    from app.core import config as config_module

    other_env = {
        "SECRET_KEY": "x" * 40,
        "ENCRYPTION_KEY": "y" * 32,
        "AGENT_SECRET_KEY": "z" * 32,
        "DATABASE_URL": "postgresql://u:p@localhost:5432/db",
        "SUPER_ADMIN_EMAIL": "a@b.com",
        "SUPER_ADMIN_PASSWORD": "pw",
    }
    saved = {k: os.environ.get(k) for k in (*other_env, "ALLOWED_ORIGINS")}
    try:
        os.environ.update(other_env)
        if raw_value is None:
            os.environ.pop("ALLOWED_ORIGINS", None)
        else:
            os.environ["ALLOWED_ORIGINS"] = raw_value
        importlib.reload(config_module)
        return config_module.Settings()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        importlib.reload(config_module)


class TestJSONArrayFormat:
    def test_exact_two_origins(self):
        s = _settings_with('["http://localhost:3000","http://localhost:5173"]')
        assert s.ALLOWED_ORIGINS == ["http://localhost:3000", "http://localhost:5173"]

    def test_single_origin(self):
        s = _settings_with('["http://localhost:3000"]')
        assert s.ALLOWED_ORIGINS == ["http://localhost:3000"]

    def test_survives_a_trailing_windows_carriage_return(self):
        """This exact byte is what broke a real user's docker-compose setup on
        Windows: the .env file had CRLF line endings."""
        s = _settings_with('["http://localhost:3000","http://localhost:5173"]\r')
        assert s.ALLOWED_ORIGINS == ["http://localhost:3000", "http://localhost:5173"]

    def test_survives_surrounding_whitespace(self):
        s = _settings_with('  ["http://localhost:3000"]  \n')
        assert s.ALLOWED_ORIGINS == ["http://localhost:3000"]

    def test_survives_internal_whitespace_after_commas(self):
        s = _settings_with('["http://localhost:3000", "http://localhost:5173"]')
        assert s.ALLOWED_ORIGINS == ["http://localhost:3000", "http://localhost:5173"]

    def test_genuinely_malformed_json_raises_a_clear_error_not_a_crash(self):
        with pytest.raises(Exception) as exc:
            _settings_with('["http://localhost:3000')
        assert "ALLOWED_ORIGINS" in str(exc.value)

    def test_json_array_of_non_strings_is_rejected(self):
        with pytest.raises(Exception):
            _settings_with('["http://localhost:3000", 5173]')


class TestCommaSeparatedFormat:
    """The format the validator's own docstring has always promised — proven
    completely unreachable before this fix (pydantic-settings' auto JSON
    decode raised SettingsError before the validator ever ran)."""

    def test_two_origins(self):
        s = _settings_with("http://localhost:3000,http://localhost:5173")
        assert s.ALLOWED_ORIGINS == ["http://localhost:3000", "http://localhost:5173"]

    def test_strips_whitespace_around_each_entry(self):
        s = _settings_with("http://localhost:3000 , http://localhost:5173")
        assert s.ALLOWED_ORIGINS == ["http://localhost:3000", "http://localhost:5173"]

    def test_single_origin_no_brackets_no_comma(self):
        """The exact shape of docker-compose.yml's own fallback default:
        ALLOWED_ORIGINS=${ALLOWED_ORIGINS:-http://localhost:3000}"""
        s = _settings_with("http://localhost:3000")
        assert s.ALLOWED_ORIGINS == ["http://localhost:3000"]

    def test_trailing_comma_does_not_produce_an_empty_origin(self):
        s = _settings_with("http://localhost:3000,")
        assert s.ALLOWED_ORIGINS == ["http://localhost:3000"]


class TestDefaultAndDirectAssignment:
    def test_unset_uses_the_class_default(self):
        s = _settings_with(None)
        assert s.ALLOWED_ORIGINS == ["http://localhost:3000"]

    def test_direct_list_assignment_still_works(self):
        """Not an env var at all — e.g. Settings(ALLOWED_ORIGINS=[...]) in code
        or in a test — must keep working since NoDecode only affects the
        environment-variable source, not programmatic construction."""
        from app.core.config import Settings

        s = Settings(
            SECRET_KEY="x" * 40, ENCRYPTION_KEY="y" * 32, AGENT_SECRET_KEY="z" * 32,
            DATABASE_URL="postgresql://u:p@localhost:5432/db",
            SUPER_ADMIN_EMAIL="a@b.com", SUPER_ADMIN_PASSWORD="pw",
            ALLOWED_ORIGINS=["http://example.com"],
        )
        assert s.ALLOWED_ORIGINS == ["http://example.com"]
