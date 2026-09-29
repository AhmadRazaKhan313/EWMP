---
name: frontend-architecture
description: Conventions and structure of the EWMP admin web app (frontend/) — Next.js App Router pages, services, store, auth/tenant handling. Use whenever editing or adding a dashboard page, admin-facing form, or frontend API call in this project.
---

# EWMP Admin Web (frontend/)

Next.js 15, App Router, React Query for server state, Zustand for client
state. This is the **admin/HR dashboard** — org owners, HR, managers,
platform admins. (Employees doing day-to-day things like applying for
leave mostly use the desktop app instead — see `skills/desktop-app`.)

## Structure

```
src/app/(auth)/...        Login, register, forgot/reset password
src/app/(dashboard)/...   One folder per feature area (employees, leave,
                           leave-types, attendance, shifts, teams,
                           departments, devices, payroll, billing,
                           recruitment, performance, reports, settings,
                           admin-setup, ai-assistant, marketplace,
                           workflow-builder, helpdesk, branches, ...)
src/components/atoms/     Small pure-presentation pieces (Badge, Skeleton,
                           StatusDot, ...) — index.tsx, no business logic,
                           no API calls. See skills/design-system.
src/components/molecules/ Composed reusable pieces (e.g. DataTable).
src/components/organisms/ Feature-sized composed components (sidebar,
                           topbar, drawers, RolesManager, ...).
src/services/             One file per API domain, wraps api-client.ts.
src/store/                Zustand stores (auth.store.ts, ...).
src/providers/            App-wide providers (QueryClientProvider, etc).
```

Each dashboard feature is typically: a `page.tsx` that fetches via a
`services/*.ts` function with React Query (`useQuery`/`useMutation`), plus
feature-local modal/drawer components colocated in the same folder.

## Auth / tenant context — read before touching any admin-facing data page

- `src/services/api-client.ts` auto-attaches `Authorization` and
  `X-Tenant-ID` headers on every request from values in `localStorage`
  (`TOKEN_KEYS`).
- `tenant_id` is set at login to `user.organization_id`, and refreshed
  whenever `/auth/me` is called.
- **Platform-admin org switching**: `app/(dashboard)/admin-setup/page.tsx`
  calls `POST /admin/switch-organization/{id}` then re-fetches
  `/auth/me`, which updates the stored `tenant_id`. If you're debugging
  "platform admin can't see an org's data," confirm this switch was
  actually done and the target org shows as current — the account's
  *own* organization is a separate bootstrap org, not any customer's.
- Regular (non-platform-admin) users' `X-Tenant-ID` header is ignored
  server-side — for them tenant is always their own org, so this isn't a
  concern outside platform-admin flows.

## React Query gotcha

The `QueryClient` is a single module-level instance
(created once, not reset). **Logout does not call `queryClient.clear()`.**
If you add a new screen, don't assume a fresh mount always means fresh
data if the app wasn't fully reloaded between two different logins during
testing — prefer explicit `queryClient.invalidateQueries()` after
mutations that affect data another screen also reads (already done in
most existing pages — follow that pattern for new mutations).

## Conventions

- Use the existing `services/<domain>.ts` pattern for new API calls —
  don't call `apiClient` directly from a page component.
- Permission-gated UI: check the current user's permissions (from the
  auth store / `/auth/me`) before rendering admin-only actions, in
  addition to the backend enforcing it — the backend is the real gate,
  but hiding actions the user can't perform avoids confusing 403s.
- Toasts for async action feedback (`toast.success` / `toast.error`) are
  the standard pattern for mutation results, not inline banners.
- For styling, see `skills/design-system/SKILL.md` — don't hardcode
  colors, use the CSS variable tokens.
