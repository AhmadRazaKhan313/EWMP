"""
Privilege-escalation guards for anything that grants or removes roles.

`roles.manage` and `employees.create` / `employees.update` are ordinary,
delegable permissions. Without these guards, anyone holding them could hand
themselves (or an account they control) a role with more power than they
have — including an `is_super` role, which is full org access.

Rules (identical wherever a role changes hands):
  * Only a full-access user (platform admin, org owner, or holder of an
    `is_super` role) may assign, remove, create, modify or delete a super role.
  * Everyone else may only grant permissions they themselves hold.

Used by app/api/v1/hrms/roles.py (the /roles endpoints) and by
app/services/employee.py (role chosen on employee create / edit). Keeping one
implementation means the two paths cannot drift apart again (audit finding
C-1: the employee endpoints used to skip these checks entirely).
"""

from collections.abc import Iterable

from app.core.exceptions import PermissionDeniedError
from app.models.rbac import Role
from app.models.user import User


def held_codenames(user: User) -> set[str]:
    """Every permission codename the user holds through their assigned roles."""
    return {p.codename for role in user.roles for p in role.permissions}


def require_full_access_for_super(user: User, action: str) -> None:
    if not user.has_full_access:
        raise PermissionDeniedError(
            f"Only an organization owner or a full-access user can {action} a "
            "full-access (super) role."
        )


def require_can_grant(user: User, codenames: Iterable[str]) -> None:
    """A non-full-access user cannot hand out permissions they do not hold."""
    if user.has_full_access:
        return
    missing = sorted(set(codenames) - held_codenames(user))
    if missing:
        raise PermissionDeniedError(
            "You cannot grant permissions you do not hold yourself: "
            + ", ".join(missing)
        )


def assert_can_assign_role(actor: User, role: Role) -> None:
    """The actor may give `role` to someone (including themselves)."""
    if role.is_super:
        require_full_access_for_super(actor, "assign")
    else:
        require_can_grant(actor, role.permission_codenames)


def assert_can_remove_roles(actor: User, roles: Iterable[Role]) -> None:
    """The actor may take these roles away from someone. Removing a super
    role is as privileged as granting one — otherwise a delegated admin
    could demote the people above them."""
    if any(role.is_super for role in roles):
        require_full_access_for_super(actor, "remove")
