---
name: agent
description: Structure and conventions of the EWMP standalone Python device agent (agent/) — the script installed on an employee's machine for heartbeats, remote lock/restart, and browsing-activity checks. Use whenever editing ewmp_agent.py, tray.py, the installer, or anything related to device enrollment/heartbeats.
---

# EWMP Desktop Agent (agent/)

A **standalone Python script**, not part of the Electron desktop app and
not built with the rest of the repo's JS tooling. It's what makes the
admin web's Devices page's Lock/Restart buttons actually do something on
a real machine, and what reports live CPU/RAM/disk/battery instead of
`null`.

```
agent/
  ewmp_agent.py     Main script: enrollment, heartbeat loop, executes
                     pending_actions (lock/restart) returned by backend.
  tray.py           System-tray icon (transparency indicator, see below).
  installer.iss     Inno Setup script — Windows installer.
  ewmp_agent.spec   PyInstaller spec — builds a single .exe.
  tests/            pytest tests (e.g. test_browsing_alerts.py).
  README.md         Full setup/deploy instructions — read this for the
                     enrollment token flow and OS-specific run methods
                     before changing enrollment or heartbeat behavior.
```

## Core flow

1. **Enroll once** with an org-wide enrollment token
   (`GET /devices/enrollment-token`, requires `devices.enroll`
   permission on the backend) → saves a per-device long-lived agent
   token to `agent_config.json` next to the script.
2. **Heartbeat loop**, every `HEARTBEAT_INTERVAL_SECONDS` (60s): reads
   live metrics via `psutil`, `POST /devices/heartbeat`. Backend updates
   the Device row, appends a `DeviceMetric` history row, recomputes a
   health score, and returns `pending_actions` — then clears its queue
   server-side, so an action fires exactly once.
3. Agent executes returned actions locally: **Lock** (OS-native — e.g.
   `LockWorkStation()` on Windows) and **Restart** (OS-native delayed
   restart, not instant, so the user isn't cut off mid-task).
4. Every `BROWSING_CHECK_EVERY_N_HEARTBEATS` heartbeats, checks active
   window/browsing activity against an `activity_watchlist` — the
   watchlist is **server-driven**: the backend returns the current list
   on every heartbeat's `activity_watchlist` field, and the hardcoded
   list at the top of `ewmp_agent.py` is only a fallback for the very
   first run before any heartbeat has completed. Don't treat the
   hardcoded list as the source of truth when changing watchlist
   behavior — change it server-side.

## Transparency is a deliberate design constraint — don't remove it

`tray.py`'s docstring is explicit about why: the agent runs as a
per-user startup entry (not a Windows Service) *specifically* so a tray
icon can always be visible to the logged-in employee — a Service runs in
Session 0 and can't show UI to the desktop session, which would silently
defeat the transparency goal. Likewise `ewmp_agent.spec` uses
`--windowed` (no console popup) but is explicit in its comments that
this is about not being annoying on boot, not about hiding the process —
nothing here is meant to evade Task Manager or antivirus visibility.
**Any change that makes the agent's presence less visible to the user it
runs on (removing the tray icon, running as a hidden service, etc.) goes
against this codebase's stated design intent — flag it rather than doing
it silently if asked.**

## Deployment

- Windows: PyInstaller (`ewmp_agent.spec`) → single `EWMPAgent.exe`, or
  Inno Setup (`installer.iss`) for a full installer. Runs via Task
  Scheduler at logon with `/rl highest` (needed for lock/restart).
- Linux: systemd unit (see README.md for the exact file) — remote
  restart needs a passwordless-sudo rule for `shutdown`, or restart
  requests silently fail (lock still works without it).
- macOS: same idea via `launchd`; same passwordless-sudo caveat for
  restart.

## Known/documented limitations (don't "fix" without checking README first)

- No installed-apps / running-processes / USB inventory — fields exist on
  the Device model and heartbeat payload, but this script doesn't
  populate them yet.
- No auto-update mechanism — a new agent version means redistributing
  the script/installer manually.
- The enrollment token is a shared, org-wide secret (like a Wi-Fi
  password), not per-device — anyone with it can enroll a device into
  the org. It's rotated by calling `/enrollment-token` again.

## When changing this file

- Keep `AGENT_VERSION` in sync with any behavior change that the backend
  or admin UI might want to key off of.
- New dependencies must be reflected in both the README's `pip install`
  line and `ewmp_agent.spec`'s `hiddenimports` if PyInstaller won't
  auto-detect them (common for platform-specific backends like
  `pystray._win32`, `win32gui`).
- Add tests under `agent/tests/` (pytest) alongside existing ones.
