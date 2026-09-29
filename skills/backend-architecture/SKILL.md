---
name: backend-architecture
description: Conventions and structure of the EWMP FastAPI backend (backend/) — routes, services, repositories, models, permissions/tenant model, migrations. Use whenever editing or adding an API endpoint, model, permission, background job, or database migration in this project.
---

# EWMP Backend

FastAPI + SQLAlchemy + Alembic + Celery, entry point `backend/app/main.py`.

## Layering (follow this, don't skip layers)

```
api/v1/<domain>/<file>.py   Route handlers — parse request, call a service,
                             return a schema. No raw SQLAlchemy queries here
                             beyond trivial single-row lookups.
services/<file>.py          Business logic, validation, orchestration.
repositories/<file>.py      DB queries (SQLAlchemy). base.py has shared
                             CRUD helpers most repos extend.
models/<file>.py            SQLAlchemy models. Business tables inherit
                             TenantModel (adds tenant_id + soft-delete).
schemas/<file>.py           Pydantic request/response schemas.
```

Domains under `api/v1/`: `hrms/` (employees, leave, attendance, shifts,
teams, departments, designations), `devices/`, `billing/`, `ai/`,
`marketplace/`, `workflows/`, `integrations/`, `webhooks/`, `reports/`,
`auth/`.

## Multi-tenancy — mandatory on every business query

- Every `TenantModel` row has `tenant_id` = Organization id.
- Resolve the current tenant with the `get_tenant_id` dependency
  (`app/permissions/dependencies.py`), never by trusting a client-supplied
  org id directly. For normal users this is always
  `user.organization_id`. Only `platform_admin` users may override it via
  the `X-Tenant-ID` header.
- **Every new repository query must filter by `tenant_id`.** This is the
  #1 place cross-tenant leaks happen. When reviewing/writing a query,
  explicitly check for the filter.
- Soft delete: filter `is_deleted == False` explicitly; nothing is
  hard-deleted by default.

## Permissions

- `app/permissions/dependencies.py` — `has_permission("<perm>")` as a
  FastAPI dependency, e.g. `Depends(has_permission("leave.apply"))`.
- **Org owner bypasses all permission checks.** Every other user needs a
  Role (org-defined, via Roles Manager in the frontend) that grants the
  specific permission string.
- New organizations get **zero pre-built roles** — nothing is auto-seeded
  per-org. `app/database/seeds/default_roles.py` only seeds the
  `platform-superadmin` role for the bootstrap "Platform Operations" org
  created by `manage.py seed --superadmin`. Don't assume a fresh org has
  any usable roles until the owner creates them.
- Permission strings are `"<domain>.<action>"`, e.g. `leave.apply`,
  `leave.view` (broader — lets a user see others' requests, used to scope
  list endpoints), `devices.enroll`.

## Adding a new endpoint — checklist

1. Route in `api/v1/<domain>/<file>.py`, depends on `get_current_user`,
   `get_tenant_id`, and `has_permission(...)` as appropriate.
2. Business logic in a `services/` function — routes stay thin.
3. DB access in a `repositories/` function — always tenant-scoped.
4. Pydantic schemas in `schemas/` for request/response, don't return
   models directly.
5. If it's a new table/column: `alembic revision --autogenerate -m "..."`
   under `app/database/migrations/versions/`. Never edit an already-
   applied migration file — add a new one.
6. Add/extend tests under `backend/tests/` (pytest) — this repo has a lot
   of tenant-scoping and permission-scoping tests
   (e.g. `test_leave_self_scope.py`) — follow that pattern for new
   protected endpoints: assert cross-tenant and cross-permission
   isolation explicitly, not just the happy path.

## Background jobs

Celery workers live in `app/workers/`. Anything heartbeat/polling-driven
(e.g. device heartbeats, attendance sync) tends to live here rather than
inline in a request handler.

## Gotchas seen in this codebase

- `GET`-list endpoints for a domain often have **two different scopes**
  depending on permission: broad (`leave.view` → see everyone in the
  tenant) vs self-only (`leave.apply` only → forced `employee_id` filter
  to the caller). Check which permission the endpoint actually requires
  before assuming a "no data returned" bug is a query bug — it may be
  correctly scoped to "only your own."
- Type/reference-data endpoints (e.g. `GET /leave/types`) are commonly
  gated only by `get_current_user`, not a specific permission — don't
  assume every GET requires a listed permission; check the actual
  `Depends(...)` on the route.
