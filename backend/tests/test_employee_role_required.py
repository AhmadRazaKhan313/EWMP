"""
Regression tests for "every employee must have a role" (employee-section fix).

A role-less user has zero permissions and an unusable app (empty sidebar, no
attendance/leave), so role assignment is now mandatory at creation rather than
a separate, forgettable step. This is enforced in two layers:

  1. Schema  — `EmployeeCreateSchema.role_id` is a REQUIRED UUID (this file).
  2. Service — `EmployeeService.create_employee` does a tenant-scoped lookup of
     that role and attaches it atomically, rolling the whole create back if the
     role id is invalid / cross-org (covered by service-level tests elsewhere).

These tests exercise the pydantic schema directly — no database, no FastAPI.

Run:  cd backend && pytest tests/test_employee_role_required.py -v
"""

import uuid
from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas.employee import EmployeeCreateSchema, EmployeeUpdateSchema


def _base_payload(**overrides):
    """A minimal, otherwise-valid create payload. Callers drop/override keys."""
    payload = {
        "first_name": "Jane",
        "last_name": "Doe",
        "email": "jane.doe@example.com",
        "date_of_joining": date(2026, 1, 15),
        "role_id": uuid.uuid4(),
    }
    payload.update(overrides)
    return payload


def test_role_id_is_required_on_create():
    """Omitting role_id must fail validation — it is not optional."""
    payload = _base_payload()
    del payload["role_id"]

    with pytest.raises(ValidationError) as exc:
        EmployeeCreateSchema(**payload)

    # The error must specifically be about the missing role_id.
    errors = exc.value.errors()
    assert any(e["loc"] == ("role_id",) and e["type"] == "missing" for e in errors), errors


def test_role_id_cannot_be_none():
    """An explicit null role_id is also rejected (field is UUID, not UUID | None)."""
    with pytest.raises(ValidationError):
        EmployeeCreateSchema(**_base_payload(role_id=None))


def test_role_id_must_be_a_valid_uuid():
    """Garbage that isn't a UUID is rejected."""
    with pytest.raises(ValidationError):
        EmployeeCreateSchema(**_base_payload(role_id="not-a-uuid"))


def test_valid_payload_parses_and_keeps_role_id():
    """A well-formed payload parses and round-trips the role_id as a UUID."""
    rid = uuid.uuid4()
    schema = EmployeeCreateSchema(**_base_payload(role_id=rid))
    assert schema.role_id == rid
    assert isinstance(schema.role_id, uuid.UUID)


def test_role_id_accepts_uuid_string():
    """A UUID given as a string is coerced to a UUID (typical JSON payload)."""
    rid = uuid.uuid4()
    schema = EmployeeCreateSchema(**_base_payload(role_id=str(rid)))
    assert schema.role_id == rid


def test_extra_unknown_fields_still_ignored():
    """model_config extra='ignore' must survive the new required field."""
    schema = EmployeeCreateSchema(**_base_payload(some_unknown_field="whatever"))
    assert not hasattr(schema, "some_unknown_field")


def test_update_schema_now_accepts_role_id_for_the_edit_form_reassignment_feature():
    """Role reassignment moved from Roles-manager-only to also being
    available on the employee Edit form (see EmployeeUpdateSchema.role_id
    and its docstring) — the schema now deliberately ACCEPTS role_id.

    The safety net is no longer "the schema drops it silently"; it's the
    router-level permission gate in PATCH /employees/{id} (app/api/v1/hrms/
    employees.py), which requires 'roles.manage' before honoring a role_id
    in the payload — see test_employee_update_role_permission.py for that
    guard's own regression coverage. This test now just documents that the
    schema itself is a pass-through, not a security boundary, for this field.
    """
    schema = EmployeeUpdateSchema(role_id=uuid.uuid4(), first_name="Jane")
    assert schema.role_id is not None