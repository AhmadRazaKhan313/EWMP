"""
Regression tests for the async lazy-load crash in EmployeeService.create_employee.

Background
----------
Making role assignment mandatory on employee create (EWMP-EMP-ROLE) introduced
an HTTP 500 on every "Add Employee" call. The cause was not the role logic
itself but *how* the role got attached:

    user = User(...)          # freshly constructed, never SELECTed
    await db.flush()
    if role not in user.roles:   # <-- boom
        user.roles.append(role)

`User.roles` is declared `lazy="selectin"`. selectin eager-loading only kicks
in when the User is *fetched by a query*; for an object we constructed and
flushed ourselves the collection is unloaded, so reading it emits a lazy SELECT.
Under the async engine a lazy SELECT from non-async context raises
`MissingGreenlet`, which surfaced to the frontend as "something went wrong".

The fix uses two patterns, one per code path:
  * new user   → pass `roles=[role]` to the `User(...)` constructor, which
                 populates the collection in memory, so nothing is ever loaded.
  * linked user → fetch via `UserRepository.get_with_roles()`, which
                 `selectinload`s roles before the membership check.

These tests lock both patterns in. They are deliberately DB-free — no engine,
no session, no network — because the bug is about *avoiding* a DB round-trip:
if the code under test ever needs one again, constructing the object here would
be the only place it could come from, and there is none.
"""

import uuid

import pytest

# Import the registry so every mapper is configured before we inspect
# relationships — String-based relationship targets are resolved lazily and
# would fail on first access if a related class were still unimported.
import app.models  # noqa: F401
from app.models.rbac import Role
from app.models.user import User
from app.repositories.user import UserRepository


def _role(name: str = "HR Manager") -> Role:
    return Role(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        name=name,
        slug=name.lower().replace(" ", "-"),
    )


def _user(**overrides) -> User:
    kwargs = {
        "organization_id": uuid.uuid4(),
        "email": "new.hire@example.com",
        "email_normalized": "new.hire@example.com",
        "password_hash": "not-a-real-hash",
        "first_name": "New",
        "last_name": "Hire",
        "is_active": True,
        "is_email_verified": False,
    }
    kwargs.update(overrides)
    return User(**kwargs)


class TestRolesAtConstruction:
    """The new-user path: roles must be assignable as a constructor kwarg."""

    def test_roles_kwarg_populates_collection_in_memory(self):
        role = _role()
        user = _user(roles=[role])

        # Reading .roles here must NOT need a DB. If this line ever starts
        # requiring a session, create_employee's new-user path is broken again.
        assert list(user.roles) == [role]

    def test_membership_check_works_without_a_session(self):
        """`role not in user.roles` — the exact expression that used to crash."""
        role = _role()
        other = _role("Finance")
        user = _user(roles=[role])

        assert role in user.roles
        assert other not in user.roles

    def test_appending_a_second_role_stays_in_memory(self):
        role = _role()
        extra = _role("Recruiter")
        user = _user(roles=[role])

        user.roles.append(extra)

        assert list(user.roles) == [role, extra]

    def test_user_built_without_roles_still_has_an_empty_collection(self):
        """Sanity: a transient User exposes a list, not None."""
        user = _user()
        assert list(user.roles) == []


class TestRelationshipConfiguration:
    """Why the patterns above are required — documents the mapping itself."""

    def test_roles_relationship_is_selectin(self):
        rel = User.__mapper__.relationships["roles"]
        assert rel.lazy == "selectin", (
            "User.roles is expected to be lazy='selectin'. If this changed, "
            "re-check create_employee: selectin only populates on a query, "
            "so a constructed-then-flushed User has it unloaded."
        )

    def test_roles_relationship_is_not_plain_lazy_select(self):
        """`lazy='select'` would make *every* async read a MissingGreenlet risk."""
        rel = User.__mapper__.relationships["roles"]
        assert rel.lazy != "select"


class TestLinkedUserPath:
    """The existing-user path: the repo must eager-load roles."""

    def test_repository_exposes_get_with_roles(self):
        assert hasattr(UserRepository, "get_with_roles")
        assert callable(UserRepository.get_with_roles)

    def test_get_with_roles_eager_loads_roles(self):
        import inspect

        source = inspect.getsource(UserRepository.get_with_roles)
        assert "selectinload" in source, (
            "get_with_roles must eager-load User.roles; create_employee relies "
            "on it so the membership check never triggers a lazy load."
        )
        assert "User.roles" in source


class TestCreateEmployeeSourceContract:
    """
    Guards the two call sites directly, so a future refactor that reverts to
    `db.get()` + `.roles` fails here instead of in production.
    """

    def test_new_user_path_passes_roles_to_constructor(self):
        import inspect

        from app.services.employee import EmployeeService

        source = inspect.getsource(EmployeeService.create_employee)
        assert "roles=[role]" in source, (
            "The new-user branch must assign roles at User(...) construction. "
            "Appending after flush triggers an async lazy load (MissingGreenlet)."
        )

    def test_linked_user_path_uses_get_with_roles(self):
        import inspect

        from app.services.employee import EmployeeService

        source = inspect.getsource(EmployeeService.create_employee)
        assert "get_with_roles" in source, (
            "The linked-user branch must load the user with roles eager-loaded "
            "before checking membership."
        )

    def test_role_is_validated_before_anything_is_created(self):
        """A bad/cross-org role id should fail fast, not after a User exists."""
        import inspect

        from app.services.employee import EmployeeService

        source = inspect.getsource(EmployeeService.create_employee)
        role_lookup = source.index("select(Role)")
        user_construction = source.index("User(")
        assert role_lookup < user_construction, (
            "Validate the role before constructing the User so an invalid "
            "role_id never leaves a half-built record behind."
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))