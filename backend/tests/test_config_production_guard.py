"""Production start-up guard: weak or development-looking settings must refuse to boot."""
import pytest
from pydantic import ValidationError

from app.core.config import Settings

GOOD = dict(
    ENVIRONMENT="production",
    DEBUG=False,
    SECRET_KEY="s" * 40,
    AGENT_SECRET_KEY="a" * 40,
    ALLOWED_ORIGINS=["https://hr.example.com"],
    DATABASE_URL="postgresql+asyncpg://u:p@db:5432/ewmp",
    ENCRYPTION_KEY="e" * 44,
    SUPER_ADMIN_EMAIL="admin@example.com",
    SUPER_ADMIN_PASSWORD="Str0ng-Passw0rd-for-tests",
)


def make(**over):
    return Settings(_env_file=None, **{**GOOD, **over})


def test_good_production_settings_boot():
    assert make().is_production


@pytest.mark.parametrize(
    "over, needle",
    [
        ({"DEBUG": True}, "DEBUG"),
        ({"SECRET_KEY": "short"}, "SECRET_KEY"),
        ({"AGENT_SECRET_KEY": "short"}, "AGENT_SECRET_KEY"),
        ({"AGENT_SECRET_KEY": "s" * 40}, "differ"),
        ({"ALLOWED_ORIGINS": ["http://localhost:3000"]}, "localhost"),
        ({"ALLOWED_ORIGINS": ["http://hr.example.com"]}, "https"),
        ({"ALLOWED_ORIGINS": ["*"]}, "https"),
    ],
)
def test_weak_production_settings_are_rejected(over, needle):
    with pytest.raises((ValidationError, ValueError)) as e:
        make(**over)
    assert needle in str(e.value)


def test_development_is_not_restricted():
    s = make(ENVIRONMENT="development", DEBUG=True, SECRET_KEY="x", AGENT_SECRET_KEY="x",
             ALLOWED_ORIGINS=["http://localhost:3000"])
    assert s.is_development
