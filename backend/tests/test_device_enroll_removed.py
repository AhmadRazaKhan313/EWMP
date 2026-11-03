"""The unattended agent enrollment path is gone: devices are added by desktop-app login only."""
from app.main import app


def _paths():
    return app.openapi()["paths"]


def test_agent_enroll_and_token_routes_do_not_exist():
    paths = _paths()
    assert not any(p.endswith("/devices/enroll") for p in paths)
    assert not any(p.endswith("/devices/enrollment-token") for p in paths)


def test_desktop_app_self_enroll_still_exists():
    hits = [p for p in _paths() if p.endswith("/devices/self-enroll")]
    assert hits and "post" in _paths()[hits[0]]
