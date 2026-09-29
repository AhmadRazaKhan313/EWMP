"""
Employee service.

Orchestrates employee lifecycle operations:
  - create: links User → Employee, auto-generates code, sends welcome email
  - update: partial field updates with audit logging
  - offboard: status transition + exit data recording
  - search: delegates to repository with pagination
"""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.core.security import generate_password_reset_token, hash_password
from app.models.employee import Employee, EmploymentStatus, JobNature
from app.models.organization import Organization
from app.models.rbac import Role
from app.models.user import User
from app.permissions.role_guards import assert_can_assign_role, assert_can_remove_roles
from app.services.auth import new_email_verification_fields, queue_verification_email
from app.repositories.employee import EmployeeRepository
from app.repositories.user import UserRepository
from app.schemas.employee import (
    EmployeeCreateSchema,
    EmployeeDetailSchema,
    EmployeeListItemSchema,
    EmployeeListResponse,
    EmployeeUpdateSchema,
)


# Statuses that mean the person no longer works here. While an employee is in
# one of these their LOGIN must be disabled: before this, offboarding only changed
# a label on the Employee row and the linked User stayed fully active, so a
# terminated employee could still sign in, clock in and read payslips.
_EXITED_STATUSES = (EmploymentStatus.TERMINATED, EmploymentStatus.RESIGNED)


class EmployeeService:
    def __init__(self, db: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.repo = EmployeeRepository(db, tenant_id)
        self.user_repo = UserRepository(db)

    async def create_employee(
        self,
        data: EmployeeCreateSchema,
        created_by_id: uuid.UUID,
        *,
        actor: User,
    ) -> tuple[Employee, str | None]:
        """
        Create a new employee profile, atomically with its linked User account.

        Everything here runs inside the single request-scoped DB session
        (see app.core.database.get_db), which commits once at the end of the
        request and rolls back the *entire* transaction on any exception.
        That means: if Employee creation fails after the User row was
        `flush()`-ed, the rollback removes the User too — no more orphaned
        login accounts with no Employee profile (see HANDOFF bug #10).

        Two supported flows:
          - data.user_id is None  → create a brand-new User + Employee together.
          - data.user_id is set   → link an existing User to a new Employee
                                     profile (e.g. promoting a contractor).

        `actor` is the user performing the request. The chosen role goes
        through the same guards as POST /roles/{id}/users/{uid}: only a
        full-access user may hand out an `is_super` role, and nobody may hand
        out permissions they don't hold (audit finding C-1 — before this,
        plain `employees.create` could create an account holding the Owner
        role and receive its temporary password).

        Returns:
            (employee, temporary_password) — temporary_password is only set
            when a new User was created here; None when linking an existing user.
        """
        temporary_password: str | None = None

        # Validate the required role up-front (tenant-scoped, mirrors the
        # roles-assign endpoint) so a cross-org / unknown role id fails fast
        # before we create anything. Assigned to the user below. Every employee
        # must have a role — a role-less user has zero permissions and an
        # unusable app. All of this runs in the single request transaction, so
        # any failure rolls the whole create back (no orphan User/Employee).
        role = (
            await self.db.execute(
                select(Role).where(
                    Role.id == data.role_id,
                    Role.organization_id == self.tenant_id,
                )
            )
        ).scalar_one_or_none()
        if role is None:
            raise NotFoundError(f"Role {data.role_id} not found in this organization")
        assert_can_assign_role(actor, role)

        if data.user_id is not None:
            # Link an existing user. Load WITH roles so the membership check
            # below runs against an in-memory collection — User.roles is
            # lazy="selectin", which only populates when the user is fetched via
            # a query. A bare get() would leave it unloaded and appending/
            # checking it here would trigger an async lazy-load (MissingGreenlet).
            user = await self.user_repo.get_with_roles(data.user_id)
            if user is None:
                raise NotFoundError(f"User {data.user_id} not found")
            if user.organization_id != self.tenant_id:
                raise ConflictError("User does not belong to this organization")

            existing = await self.repo.get_by_user_id(data.user_id)
            if existing is not None:
                raise ConflictError(
                    f"User {data.user_id} already has an employee profile "
                    f"({existing.employee_code})"
                )

            if role not in user.roles:
                user.roles.append(role)
                await self.db.flush()
        else:
            # Create a brand-new user in the same transaction, with the role
            # assigned at construction (roles=[role]). Assigning the collection
            # up-front initializes it in memory, so there is no post-flush
            # relationship read that could trigger an async lazy-load.
            if await self.user_repo.email_exists(data.email):
                raise ConflictError(f"An account with email {data.email} already exists")

            temporary_password = generate_password_reset_token()[:12] + "Aa1!"
            user = User(
                organization_id=self.tenant_id,
                email=data.email,
                email_normalized=data.email.lower().strip(),
                password_hash=hash_password(temporary_password),
                first_name=data.first_name,
                last_name=data.last_name,
                is_active=True,
                is_email_verified=False,
                must_change_password=True,
                roles=[role],
                **new_email_verification_fields(),
            )
            self.db.add(user)
            await self.db.flush()  # assigns user.id, still inside this transaction

        # Generate sequential code. Wrapped in a small retry loop: the
        # unique constraint on (tenant_id, employee_code) (migration
        # 3e338fd61f00) means two near-simultaneous creates that both
        # compute the same next code will have one succeed and one hit an
        # IntegrityError here — rather than surfacing that as a 500, just
        # regenerate (now that the other row committed, the MAX-based
        # generator will produce a different code) and try again.
        employee_payload_base = {
            "user_id": user.id,
            "department_id": data.department_id,
            "designation_id": data.designation_id,
            "branch_id": data.branch_id,
            "team_id": data.team_id,
            "manager_id": data.manager_id,
            "employment_type": data.employment_type,
            "job_nature": data.job_nature,
            "employment_status": (
                EmploymentStatus.PROBATION
                if data.job_nature == JobNature.PROBATIONARY
                else EmploymentStatus.ACTIVE
            ),
            "date_of_joining": data.date_of_joining,
            "date_of_birth": data.date_of_birth,
            "gender": data.gender,
            "work_phone": data.phone,
            "work_location": data.work_location,
            "is_remote": data.is_remote,
            "current_salary": data.current_salary,
            "currency": data.currency,
        }

        max_attempts = 3
        employee = None
        for attempt in range(1, max_attempts + 1):
            employee_code = await self.repo.get_next_employee_code()
            try:
                # A SAVEPOINT (nested transaction), not a full rollback:
                # `user` was already flushed earlier in this same outer
                # transaction, and a plain db.rollback() here would discard
                # that too. begin_nested() lets a failed attempt roll back
                # to just before it, leaving the user creation intact for
                # the retry (and for the caller's eventual commit).
                async with self.db.begin_nested():
                    employee = await self.repo.create({**employee_payload_base, "employee_code": employee_code})
                break
            except IntegrityError:
                if attempt == max_attempts:
                    raise ConflictError(
                        "Could not generate a unique employee code after several attempts — please retry"
                    )
                continue

        # A brand-new account (not a linked existing user) needs a way to
        # verify its email — otherwise, with REQUIRE_EMAIL_VERIFICATION on,
        # it can never use the app (audit C-3). Queued only now, after the
        # employee row exists too, so a failed create never emails a link to
        # a user that was rolled back. Best-effort: never blocks creation;
        # the user can also hit POST /auth/resend-verification.
        if temporary_password is not None:
            queue_verification_email(user.email, user.email_verification_token)

        return employee, temporary_password

    async def update_employee(
        self,
        employee_id: uuid.UUID,
        data: EmployeeUpdateSchema,
        updated_by_id: uuid.UUID,
        *,
        can_manage_exit: bool = False,
        actor: User | None = None,
    ) -> Employee:
        """
        Partial update. Only provided fields are changed.

        Moving an employee INTO or OUT OF an exited status (terminated/resigned)
        changes whether they can log in, so it needs `can_manage_exit` (the API
        passes `employees.delete` — the same permission /offboard needs). It
        defaults to False so any caller that forgets to decide fails closed.

        first_name/last_name are columns on User, not Employee — passing them
        straight to repo.update() used to silently no-op (setattr on an
        unmapped attribute never persists). They're split out here and applied
        to the linked User row instead, in the same transaction.

        role_id is likewise not an Employee column — it lives on the
        underlying User via the roles many-to-many. Reassigning it here
        replaces the user's current role set with the single new role
        (see the "exactly one role" model established at creation), rather
        than adding to it, so an employee is never left holding a stale role
        alongside the new one. Because it is a grant AND a removal, it goes
        through both role guards (audit finding C-1): the new role must be
        one `actor` is allowed to hand out, and any super role being taken
        away requires a full-access actor. A role change without an `actor`
        is refused (fails closed).
        """
        employee = await self.repo.get_or_raise(employee_id)

        update_data = data.model_dump(exclude_unset=True, exclude_none=False)
        if not update_data:
            return employee

        # Exit-status transition (checked before anything is written).
        new_status = update_data.get("employment_status")
        crosses_exit_boundary = False
        will_be_exited = False
        if new_status is not None:
            was_exited = employee.employment_status in _EXITED_STATUSES
            will_be_exited = new_status in _EXITED_STATUSES
            crosses_exit_boundary = was_exited != will_be_exited
            if crosses_exit_boundary:
                if not can_manage_exit:
                    raise PermissionDeniedError(
                        "Moving an employee to or from Terminated/Resigned requires "
                        "the 'employees.delete' permission (use Offboard)."
                    )
                if will_be_exited:
                    await self._guard_can_disable_login(employee, updated_by_id)

        first_name = update_data.pop("first_name", None)
        last_name = update_data.pop("last_name", None)
        role_id = update_data.pop("role_id", None)

        if first_name is not None or last_name is not None or role_id is not None:
            user = await self.user_repo.get_with_roles(employee.user_id)
            if user is not None:
                if first_name is not None:
                    user.first_name = first_name
                if last_name is not None:
                    user.last_name = last_name
                if role_id is not None:
                    role = (
                        await self.db.execute(
                            select(Role).where(
                                Role.id == role_id,
                                Role.organization_id == self.tenant_id,
                            )
                        )
                    ).scalar_one_or_none()
                    if role is None:
                        raise NotFoundError(f"Role {role_id} not found in this organization")
                    if actor is None:
                        raise PermissionDeniedError(
                            "Changing an employee's role requires an acting user."
                        )
                    assert_can_assign_role(actor, role)
                    assert_can_remove_roles(
                        actor, [r for r in user.roles if r.id != role.id]
                    )
                    user.roles = [role]
                await self.db.flush()

        if not update_data:
            return await self.repo.get_or_raise(employee_id)

        updated = await self.repo.update(employee_id, update_data)
        if crosses_exit_boundary:
            # Terminated/resigned -> login off. Rehired -> login back on.
            await self._set_login_active(employee, active=not will_be_exited)
        return updated

    async def get_employee(self, employee_id: uuid.UUID) -> Employee:
        """Fetch full employee detail with all relations."""
        employee = await self.repo.get_with_relations(employee_id)
        if employee is None:
            raise NotFoundError(f"Employee {employee_id} not found")
        return employee

    async def list_employees(
        self,
        *,
        query: str | None = None,
        department_id: uuid.UUID | None = None,
        branch_id: uuid.UUID | None = None,
        team_id: uuid.UUID | None = None,
        designation_id: uuid.UUID | None = None,
        manager_id: uuid.UUID | None = None,
        status: EmploymentStatus | None = None,
        employment_type: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> EmployeeListResponse:
        items, total = await self.repo.search(
            query=query,
            department_id=department_id,
            branch_id=branch_id,
            team_id=team_id,
            designation_id=designation_id,
            manager_id=manager_id,
            status=status,
            employment_type=employment_type,
            page=page,
            page_size=page_size,
        )

        total_pages = max(1, -(-total // page_size))  # ceiling division

        return EmployeeListResponse(
            items=[EmployeeListItemSchema.from_employee(e) for e in items],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    # ── Login access follows employment status ──────────────────────────────
    # Disabling User.is_active is what actually cuts access: login, token refresh
    # and get_current_user (which reads the DB on every request, so even an
    # already-issued access token stops working immediately) all reject inactive
    # users.

    async def _guard_can_disable_login(
        self, employee: Employee, acting_user_id: uuid.UUID
    ) -> None:
        """Refuse the two cases where disabling a login would be a disaster.

        Runs BEFORE anything is changed, so a refusal leaves no partial update.
        """
        if employee.user_id == acting_user_id:
            raise ConflictError(
                "You cannot offboard or delete your own account. "
                "Ask another administrator to do it."
            )
        owner_id = (
            await self.db.execute(
                select(Organization.owner_id).where(Organization.id == self.tenant_id)
            )
        ).scalar_one_or_none()
        if owner_id is not None and owner_id == employee.user_id:
            raise ConflictError(
                "This employee is the organization owner. Disabling their login "
                "would lock everyone out of full administration, so it is not "
                "allowed."
            )

    async def _set_login_active(self, employee: Employee, active: bool) -> None:
        """Enable/disable the login of the User linked to this employee."""
        user = (
            await self.db.execute(
                select(User).where(
                    User.id == employee.user_id,
                    User.organization_id == self.tenant_id,
                )
            )
        ).scalar_one_or_none()
        if user is None or user.is_active == active:
            return
        user.is_active = active
        await self.db.flush()

    async def delete_employee(
        self, employee_id: uuid.UUID, deleted_by_id: uuid.UUID
    ) -> None:
        """Soft-delete an employee AND disable their login (same guards as offboarding)."""
        employee = await self.repo.get_or_raise(employee_id)
        await self._guard_can_disable_login(employee, deleted_by_id)
        await self._set_login_active(employee, False)
        await self.repo.delete(employee_id)

    async def offboard_employee(
        self,
        employee_id: uuid.UUID,
        date_of_leaving: date,
        exit_reason: str,
        offboarded_by_id: uuid.UUID,
    ) -> Employee:
        """
        Trigger offboarding: set status, record exit date and reason.
        Downstream: workflow engine triggers offboarding checklist.
        """
        employee = await self.repo.get_or_raise(employee_id)

        if employee.employment_status in _EXITED_STATUSES:
            raise ConflictError("Employee is already offboarded")

        await self._guard_can_disable_login(employee, offboarded_by_id)

        updated = await self.repo.update(employee_id, {
            "employment_status": EmploymentStatus.TERMINATED,
            "date_of_leaving": date_of_leaving,
            "exit_reason": exit_reason,
        })
        await self._set_login_active(employee, False)

        # Trigger offboarding workflow via Celery
        try:
            from app.workers.tasks.notifications import trigger_workflow_event
            trigger_workflow_event.delay(
                str(self.tenant_id),
                "employee_offboarded",
                {"employee_id": str(employee_id)},
            )
        except Exception:
            pass

        return updated

    async def get_dashboard_stats(self) -> dict:
        """Return quick stats for the HR Dashboard header cards."""
        by_status = await self.repo.count_by_status()
        by_dept = await self.repo.count_by_department()

        return {
            "total_active": by_status.get("active", 0),
            "on_probation": by_status.get("probation", 0),
            "on_leave": by_status.get("on_leave", 0),
            "notice_period": by_status.get("notice_period", 0),
            "by_department": by_dept,
        }