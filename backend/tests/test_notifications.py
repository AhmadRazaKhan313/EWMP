"""
Notifications: the on/off rules, recipients, and that sending can never break
the action that triggered it. No database needed.

Run:  cd backend && pytest tests/test_notifications.py -v
"""

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.api.v1.notifications.router as router_mod
import app.services.notify as notify_mod

TENANT = uuid.uuid4()
ALI, SARA = uuid.uuid4(), uuid.uuid4()


def _user(uid, prefs=None):
    return SimpleNamespace(id=uid, preferences=prefs if prefs is not None else {}, organization_id=TENANT)


def _run(coro):
    return asyncio.run(coro)


# ── preference rules ──────────────────────────────────────────────────────

def test_everything_is_on_by_default():
    assert all(notify_mod.preference_map(_user(ALI)).values())
    assert set(notify_mod.preference_map(_user(ALI))) == set(notify_mod.CATEGORIES)


def test_turning_one_off_leaves_the_rest_on_and_keeps_other_preferences():
    u = _user(ALI, {"theme": "dark"})
    out = notify_mod.set_preferences(u, {"leave": False})
    assert out["leave"] is False and out["payroll"] is True
    assert u.preferences["theme"] == "dark"                   # untouched
    assert notify_mod.is_enabled(u, "leave") is False
    notify_mod.set_preferences(u, {"leave": True})
    assert notify_mod.is_enabled(u, "leave") is True


def test_unknown_category_is_rejected():
    with pytest.raises(ValueError):
        notify_mod.set_preferences(_user(ALI), {"gossip": False})


def test_preferences_column_is_reassigned_not_mutated():
    """A JSON column only saves if the attribute is replaced, not edited in place."""
    u = _user(ALI, {})
    before = u.preferences
    notify_mod.set_preferences(u, {"leave": False})
    assert u.preferences is not before


# ── notify(): who gets a row ──────────────────────────────────────────────

class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


class _Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeDB:
    def __init__(self, users, explode=False):
        self.users, self.added, self.explode = users, [], False
        self.explode = explode

    def begin_nested(self):
        return _Nested()

    async def execute(self, stmt):
        if self.explode:
            raise RuntimeError("database fell over")
        return _Result(self.users)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass


def _send(db, ids, category="leave"):
    return _run(notify_mod.notify(db, TENANT, ids, category=category, title="Hello", body="b"))


def test_only_people_who_have_it_on_get_a_notification():
    db = _FakeDB([_user(ALI), _user(SARA, {"notifications": {"leave": False}})])
    assert _send(db, [ALI, SARA]) == 1
    assert [n.user_id for n in db.added] == [ALI]
    assert db.added[0].type == "leave" and db.added[0].tenant_id == TENANT


def test_other_categories_are_not_affected_by_one_being_off():
    db = _FakeDB([_user(SARA, {"notifications": {"leave": False}})])
    assert _send(db, [SARA], category="payroll") == 1


def test_no_recipients_means_no_query_and_no_rows():
    db = _FakeDB([_user(ALI)])
    assert _send(db, [None, None]) == 0
    assert db.added == []


def test_unknown_category_creates_nothing():
    db = _FakeDB([_user(ALI)])
    assert _send(db, [ALI], category="nope") == 0 and db.added == []


def test_a_database_failure_never_breaks_the_caller():
    db = _FakeDB([_user(ALI)], explode=True)
    assert _send(db, [ALI]) == 0          # returned 0, did not raise


def test_title_is_cut_to_the_column_size():
    db = _FakeDB([_user(ALI)])
    _run(notify_mod.notify(db, TENANT, [ALI], category="leave", title="x" * 400))
    assert len(db.added[0].title) == 255


# ── preferences API ───────────────────────────────────────────────────────

def test_get_preferences_lists_every_category_with_labels():
    out = _run(router_mod.get_preferences(current_user=_user(ALI, {"notifications": {"helpdesk": False}})))
    by_key = {i.key: i for i in out.items}
    assert set(by_key) == set(notify_mod.CATEGORIES)
    assert by_key["helpdesk"].enabled is False and by_key["leave"].enabled is True
    assert by_key["leave"].label == "Leave" and by_key["leave"].description


def test_put_preferences_saves_and_returns_the_new_state():
    saved = []
    db = SimpleNamespace(add=saved.append, flush=lambda: asyncio.sleep(0))
    u = _user(ALI)
    out = _run(router_mod.update_preferences(
        router_mod.PreferencesIn(preferences={"payroll": False}), db=db, current_user=u))
    assert {i.key: i.enabled for i in out.items}["payroll"] is False
    assert saved == [u]


def test_put_preferences_rejects_unknown_category_with_422():
    db = SimpleNamespace(add=lambda x: None, flush=lambda: asyncio.sleep(0))
    with pytest.raises(HTTPException) as e:
        _run(router_mod.update_preferences(
            router_mod.PreferencesIn(preferences={"gossip": True}), db=db, current_user=_user(ALI)))
    assert e.value.status_code == 422
