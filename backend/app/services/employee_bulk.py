"""Bulk employee CSV export / import (E-08)."""
from __future__ import annotations

import csv
import io
import uuid
from datetime import date

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EWMPException, ValidationError
from app.models.employee import EmployeeStatusHistory
from app.models.organization_structure import Branch, Department, Designation
from app.models.rbac import Role
from app.models.user import User
from app.permissions.role_guards import assert_can_assign_role
from app.schemas.employee import EmployeeCreateSchema
from app.services.employee import EmployeeService

MAX_IMPORT_ROWS = 500
MAX_IMPORT_BYTES = 1_000_000

EXPORT_COLUMNS = [
    "employee_code", "first_name", "last_name", "email", "status", "job_nature", "employment_type",
    "department", "designation", "branch", "date_of_joining", "date_of_leaving", "phone", "work_location",
]
IMPORT_COLUMNS = [
    "first_name", "last_name", "email", "role", "date_of_joining", "employment_type", "job_nature",
    "department", "designation", "branch", "phone", "gender", "date_of_birth", "work_location", "is_remote",
]
_SAMPLE_ROW = [
    "Ayesha", "Khan", "ayesha.khan@example.com", "Employee", "2026-01-15", "full_time", "probationary",
    "Engineering", "Software Engineer", "Head Office", "+92 300 1234567", "female", "1998-05-20", "Bahawalpur", "no",
]


def neutralize(value) -> str:
    """CSV/Excel formula injection: a cell starting with = + - @ (or tab/CR)
    is executed as a formula when the file is opened. Prefix a quote."""
    text = "" if value is None else str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def _csv(rows: list[list[str]]) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\r\n").writerows(rows)
    return buf.getvalue()


def import_template_csv() -> str:
    return _csv([IMPORT_COLUMNS, _SAMPLE_ROW])


async def export_csv(db: AsyncSession, tenant_id: uuid.UUID, service: EmployeeService, **filters) -> str:
    """Every employee matching the same filters as the list page (no paging)."""
    items, _ = await service.repo.search(page=1, page_size=100_000, **filters)
    names: dict = {}
    for model in (Department, Designation, Branch):
        names[model] = dict(
            (await db.execute(select(model.id, model.name).where(model.tenant_id == tenant_id))).all()
        )
    rows = [EXPORT_COLUMNS]
    for e in items:
        rows.append([
            neutralize(v) for v in (
                e.employee_code,
                e.user.first_name if e.user else "", e.user.last_name if e.user else "",
                e.user.email if e.user else "",
                e.employment_status.value, e.job_nature.value, e.employment_type.value,
                names[Department].get(e.department_id, ""),
                names[Designation].get(e.designation_id, ""),
                names[Branch].get(e.branch_id, ""),
                e.date_of_joining.isoformat() if e.date_of_joining else "",
                e.date_of_leaving.isoformat() if e.date_of_leaving else "",
                e.work_phone or "", e.work_location or "",
            )
        ])
    return _csv(rows)


def _truthy(v: str) -> bool:
    return v.strip().lower() in ("1", "true", "yes", "y")


async def _lookup(db, model, tenant_id) -> dict[str, uuid.UUID]:
    rows = (await db.execute(
        select(model.id, func.lower(model.name)).where(model.tenant_id == tenant_id, model.is_deleted == False)  # noqa: E712
    )).all()
    return {n: i for i, n in rows}


async def import_csv(
    db: AsyncSession, tenant_id: uuid.UUID, actor: User, raw: bytes, *, dry_run: bool,
) -> dict:
    """Validate (and unless dry_run, create) employees from a CSV.

    A bad row never blocks the good ones: each row runs in its own savepoint
    and gets its own error message. Nothing is created in dry_run mode."""
    if len(raw) > MAX_IMPORT_BYTES:
        raise ValidationError("CSV is too large (max 1 MB).")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValidationError("CSV must be UTF-8 encoded.")
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]
    missing = [c for c in ("first_name", "last_name", "email", "role", "date_of_joining") if c not in headers]
    if missing:
        raise ValidationError(f"Missing required column(s): {', '.join(missing)}. Download the template.")
    records = [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in reader]
    if not records:
        raise ValidationError("The CSV has no data rows.")
    if len(records) > MAX_IMPORT_ROWS:
        raise ValidationError(f"Too many rows ({len(records)}). Import at most {MAX_IMPORT_ROWS} at a time.")

    roles = {
        n: r for n, r in (
            (r.name.lower(), r) for r in (await db.execute(
                select(Role).where(Role.organization_id == tenant_id))).scalars().all()
        )
    }
    dept = await _lookup(db, Department, tenant_id)
    desig = await _lookup(db, Designation, tenant_id)
    branch = await _lookup(db, Branch, tenant_id)
    service = EmployeeService(db, tenant_id)
    seen_emails: set[str] = set()
    results, created, failed = [], 0, 0

    for line, rec in enumerate(records, start=2):  # row 1 is the header
        out = {"row": line, "email": rec.get("email", ""), "ok": False, "error": None}
        try:
            email = rec.get("email", "").lower()
            if email in seen_emails:
                raise ValidationError("Duplicate email in this file.")
            role = roles.get(rec.get("role", "").lower())
            if role is None:
                raise ValidationError(f"Unknown role '{rec.get('role', '')}'.")
            assert_can_assign_role(actor, role)
            payload: dict = {
                "first_name": rec.get("first_name"), "last_name": rec.get("last_name"), "email": email,
                "date_of_joining": rec.get("date_of_joining"), "role_id": role.id,
            }
            for key in ("employment_type", "job_nature", "gender", "phone", "work_location", "date_of_birth"):
                if rec.get(key):
                    payload[key] = rec[key]
            if rec.get("is_remote"):
                payload["is_remote"] = _truthy(rec["is_remote"])
            for key, table, label in (
                ("department", dept, "department"), ("designation", desig, "designation"), ("branch", branch, "branch"),
            ):
                if rec.get(key):
                    found = table.get(rec[key].lower())
                    if found is None:
                        raise ValidationError(f"Unknown {label} '{rec[key]}'.")
                    payload[f"{key}_id"] = found
            try:
                data = EmployeeCreateSchema(**payload)
            except PydanticValidationError as exc:
                first = exc.errors()[0]
                where = ".".join(str(x) for x in first["loc"])
                raise ValidationError(f"{where}: {first['msg']}")
            if await service.user_repo.email_exists(data.email):
                raise ValidationError("An account with this email already exists.")
            seen_emails.add(email)
            if not dry_run:
                async with db.begin_nested():
                    employee, temp_password = await service.create_employee(data, actor.id, actor=actor)
                    # create_employee already wrote the "created" timeline row; label it as an import.
                    await db.execute(
                        update(EmployeeStatusHistory)
                        .where(EmployeeStatusHistory.employee_id == employee.id,
                               EmployeeStatusHistory.source == "created")
                        .values(source="import")
                    )
                out["employee_code"] = employee.employee_code
                out["temporary_password"] = temp_password
            out["ok"] = True
            created += 1
        except EWMPException as exc:
            out["error"] = getattr(exc, "message", None) or str(exc)
            failed += 1
        results.append(out)

    return {"dry_run": dry_run, "total": len(records), "created": created, "failed": failed, "rows": results}
