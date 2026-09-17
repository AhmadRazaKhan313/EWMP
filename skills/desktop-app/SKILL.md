---
name: desktop-app
description: Structure and conventions of the EWMP Electron desktop app (desktop-app/) — the employee-facing client for check-in, leave, notifications, device consent. Use whenever editing or adding a screen, store, or main/renderer process code in the desktop app.
---

# EWMP Desktop App (desktop-app/)

Electron + React + TypeScript + React Query + Zustand + Tailwind. This is
the **employee-facing** client (as opposed to `frontend/`, the
admin/HR dashboard) — it's what a regular employee runs on their own
machine to check in/out, apply for leave, see notifications, and consent
to device monitoring.

## Process structure

```
src/main/        Electron main process: index.ts (app lifecycle, windows),
                  hardwareInfo.ts (CPU/RAM/disk/battery for heartbeats),
                  trayStatus.ts / trayIcons.ts (system tray state/icons).
src/preload/      contextBridge — the only way renderer talks to main.
src/shared/       Code shared between main and renderer, notably
                  api-client.ts (axios instance, auth/tenant headers,
                  401-refresh interceptor, AUTH_FAILURE_EVENT).
src/renderer/src/
  screens/        One file per top-level screen (see below).
  store/          Zustand: authStore.ts, deviceStore.ts, timerStore.ts.
  services/       API call wrappers per domain (leaveService.ts, ...).
  hooks/          useTraySync, useDeviceHeartbeat, useNotificationBadge.
  types/          Shared TS types (hrms.ts, auth.ts, ...).
  main.tsx        App entry — creates the single module-level QueryClient.
```

## App flow (`App.tsx` — read this before adding a new top-level screen)

Gated sequence, each stage fully replaces the rendered screen:
`ServerSetupScreen` (no server configured yet) → `LoginScreen`
(unauthenticated) → `ConsentNotice` (device status `needs_consent`) →
`AuthenticatedPlaceholder` (normal authenticated shell, hosts
Dashboard/Leave/Notifications/CheckIn).

- **Server URL is per-install, independent of the web admin.** Each
  employee's machine must be pointed at the same backend the admin site
  uses via `ServerSetupScreen` — there's no auto-detection. If desktop
  and admin ever show different data for what should be the same org,
  first check the configured server URL matches, before suspecting a
  backend bug.
- `authStore.logout()` clears auth state but does **not** clear the
  React Query cache (`main.tsx`'s `queryClient` is a single instance for
  the process lifetime) — see the cache gotcha in the root `CLAUDE.md`.

## Screens

- `ServerSetupScreen` — one-time backend URL entry + connectivity check.
- `LoginScreen` — email/password.
- `ConsentNotice` — device-monitoring consent gate.
- `DashboardScreen` / `AuthenticatedPlaceholder` — main shell, hosts
  `CheckInWidget`.
- `LeaveScreen` — list leave types (`GET /leave/types`, filtered to
  `is_active` client-side) and submit/view leave requests
  (`leaveService.ts`). Requires the backend `leave.apply` permission on
  the logged-in employee's role — a 403 here is a permissions issue, not
  a UI bug.
- `NotificationsScreen` — in-app notifications + badge count.

## Tray / device heartbeat

`useTraySync` keeps the OS tray icon/menu (`main/trayStatus.ts`,
`main/trayIcons.ts`) in sync with renderer state over the preload bridge.
`useDeviceHeartbeat` periodically reports device status — this is the
renderer-side counterpart to the standalone Python `agent/` (see
`skills/agent/SKILL.md`); they are two independent heartbeat sources
hitting the same `/devices/heartbeat`-style backend endpoints, not the
same code path — don't assume a fix in one applies to the other.

## Conventions

- New screens/services follow the existing per-domain file pattern
  (`services/<domain>Service.ts` wrapping `shared/api-client.ts`).
- Styling: same design-token system as the admin web app — see
  `skills/design-system/SKILL.md`. `desktop-app/tailwind.config.js` and
  its global CSS mirror `frontend`'s tokens; keep both in sync if you add
  one.
- Tests: Vitest, colocated in `__tests__/` next to the file under test —
  follow that placement for new screens/services/stores.
