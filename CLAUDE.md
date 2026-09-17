# EWMP — Project Rules & Map (read this first)

EWMP (Enterprise Workforce Management Platform) is a multi-tenant SaaS with
four parts that all talk to ONE backend:

| Part          | Path            | Stack                                   |
|---------------|-----------------|------------------------------------------|
| Backend API   | `backend/`      | FastAPI + SQLAlchemy + Alembic + Celery   |
| Admin Web     | `frontend/`     | Next.js 15 (App Router) + React Query     |
| Desktop App   | `desktop-app/`  | Electron + React + React Query            |
| Device Agent  | `agent/`        | Standalone Python script (psutil/pystray) |

Don't re-read the whole repo every session. Read this file, then only the
`skills/*/SKILL.md` file(s) relevant to what you're touching:

- Touching API routes, models, permissions, migrations → `skills/backend-architecture/SKILL.md`
- Touching the admin dashboard (Next.js) → `skills/frontend-architecture/SKILL.md`
- Touching colors, components, layout, "make it look right" → `skills/design-system/SKILL.md`
- Touching the Electron desktop app (employee-facing) → `skills/desktop-app/SKILL.md`
- Touching the Python tray agent (device monitoring / lock / restart) → `skills/agent/SKILL.md`

Frontend and desktop-app deliberately duplicate some logic (separate
`api-client.ts`, separate component sets) — they are two independent
clients of the same backend, not a shared codebase. Don't assume a fix in
one applies to the other.

## The multi-tenant model — read this before touching ANY feature

Every business table (leave, attendance, employees, devices, …) has a
`tenant_id` = an Organization id. This is the single most important
concept in the codebase and the source of most confusing bugs.

1. **Tenant resolution** (`backend/app/permissions/dependencies.py`,
   `get_tenant_id`): for a normal user, tenant = `user.organization_id`,
   always. For a **platform_admin** only, an `X-Tenant-ID` header can
   override this. Both `frontend/` and `desktop-app/` API clients attach
   `X-Tenant-ID` automatically from locally stored `tenant_id` — but that
   header is silently ignored for non-platform-admin users.
2. **The seeded `platform-superadmin` account belongs to a separate
   bootstrap "Platform Operations" organization**, not to any customer
   org. If it's viewing a customer org's data, it MUST have used
   `Admin Setup → Switch` (`POST /admin/switch-organization/{org_id}`)
   first, which updates the stored tenant_id via `/auth/me`. If you're
   debugging "admin can't see X" and the account in question is the
   platform superadmin, check this first.
3. **New organizations start with ZERO pre-built roles.** Only the org
   **owner** bypasses permission checks. Every other employee needs an
   explicit Role (created via Roles Manager) that grants the specific
   permission for whatever they're trying to do (e.g. `leave.apply`,
   `devices.enroll`). "Regular employee can't do X" is very often a
   missing-permission issue, not a code bug — check `has_permission` /
   the role's permission list before assuming otherwise.
4. Always search for `tenant_id` filters when reading or writing a
   repository/service method — a query missing a tenant scope is a
   cross-tenant data leak.

## Known cross-client gotcha: React Query cache is not cleared on logout

Both `frontend/` and `desktop-app/` create a single module-level
`QueryClient` and never call `queryClient.clear()` on logout
(`store/authStore.ts` / `store/auth.store.ts`). If a screen stays mounted
across a logout→login transition (or two different accounts are used in
the same running instance), stale data from the previous account/tenant
can be shown until that specific query happens to refetch. Keep this in
mind when a bug report smells like "showing someone else's data" — check
whether the desktop/web app was ever switched between accounts without a
full restart before concluding it's a backend scoping bug.

## Conventions that apply everywhere

- Backend: layered `api/v1/<domain>/*.py` (routes) → `services/*.py`
  (business logic) → `repositories/*.py` (DB queries) → `models/*.py`
  (SQLAlchemy) → `schemas/*.py` (Pydantic). Don't put query logic
  directly in routes for anything beyond a trivial lookup.
- Both web and desktop API clients auto-attach `Authorization` +
  `X-Tenant-ID` headers and handle 401 refresh — never hand-roll auth
  headers in a new service file, extend the existing `api-client.ts`.
- Soft-delete is the norm (`is_deleted` flag), not hard deletes — new
  queries need an explicit `is_deleted == False` filter.
- Migrations: Alembic, under `backend/app/database/migrations/versions/`.
  Never hand-edit an already-applied migration; add a new one.

## When you start a task

1. Read this file + the one relevant `skills/*/SKILL.md`.
2. If the task is a bug report, ask (or check) which account/role and
   which of the four clients (web/desktop/agent/API) is involved before
   guessing — most confusing "bugs" in this codebase turn out to be
   tenant-context or permission-context, not logic errors.
3. Only open the actual source files for the specific route/screen/
   component you're changing — the skill files summarize structure and
   conventions so you don't need to survey the whole tree again.
