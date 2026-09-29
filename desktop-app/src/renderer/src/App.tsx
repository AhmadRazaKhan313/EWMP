import { useEffect, useState } from "react";
import { useAuthStore, attachAuthFailureListener } from "./store/authStore";
import { useDeviceStore } from "./store/deviceStore";
import { useTimerStore } from "./store/timerStore";
import { hasServerConfigured } from "@shared/api-client";
import LoginScreen from "./screens/LoginScreen";
import ServerSetupScreen from "./screens/ServerSetupScreen";
import AuthenticatedPlaceholder from "./screens/AuthenticatedPlaceholder";
import ChangePasswordScreen from "./screens/ChangePasswordScreen";
import ConsentNotice from "./screens/ConsentNotice";
import WidgetScreen from "./screens/WidgetScreen";
import { useTraySync } from "./hooks/useTraySync";
import { useDeviceHeartbeat } from "./hooks/useDeviceHeartbeat";
import { useNotificationBadge } from "./hooks/useNotificationBadge";
import { useActivityTracking } from "./hooks/useActivityTracking";
import { useShiftReminders } from "./hooks/useShiftReminders";

// The main window and the floating desktop widget (see main/index.ts's
// createWidgetWindow) load the exact same renderer bundle — this flag,
// set once at module load from the window's own URL, is the only thing
// that tells the two apart. It's read here rather than per-render so a
// window's identity can never flip mid-session.
const IS_WIDGET_WINDOW = new URLSearchParams(window.location.search).get("widget") === "1";

/**
 * Phase 2 (Auth): first ensures a server URL is configured (each employee's
 * laptop needs to know where the backend actually is — it's never on the
 * same machine as their desktop app), then restores a stored session, then
 * renders login or the authenticated screen.
 *
 * Phase 4 item #1 (self-enrollment): once authenticated, also gates on
 * deviceStore — but ONLY for "needs_consent". "checking"/"enrolling"/
 * "needs_finish"/"enrolled" all fall through to AuthenticatedPlaceholder;
 * device enrollment is a fleet-management nicety, never a login-blocking
 * requirement (see deviceStore.ts's status docstring).
 *
 * Forced password change: a user whose password was set by someone else
 * (new employee / new org owner given a randomly generated temp
 * password) has `must_change_password: true` and is routed to
 * ChangePasswordScreen ahead of device consent — nothing else in the app
 * is reachable until they set their own password.
 */
export default function App(): JSX.Element {
  // Branched at the very top, before any hooks — the widget window has
  // none of the main window's concerns (tray sync, device heartbeat,
  // activity tracking, login gating UI), so it gets its own tiny
  // component tree entirely rather than threading a flag through
  // MainApp's hooks.
  if (IS_WIDGET_WINDOW) {
    return <WidgetScreen />;
  }
  return <MainApp />;
}

function MainApp(): JSX.Element {
  const status = useAuthStore((s) => s.status);
  const user = useAuthStore((s) => s.user);
  const restoreSession = useAuthStore((s) => s.restoreSession);
  const deviceStatus = useDeviceStore((s) => s.status);
  const initDevice = useDeviceStore((s) => s.init);
  const timerStatus = useTimerStore((s) => s.status);
  const [serverReady, setServerReady] = useState<boolean | null>(null);
  useTraySync();
  useDeviceHeartbeat(deviceStatus);
  useNotificationBadge(status === "authenticated");
  useActivityTracking(timerStatus);
  // Shift-start and shift-end-in-15-minutes reminders — see the hook's
  // own docs for why this lives here (main window only, runs in the
  // background) rather than in WidgetScreen too.
  useShiftReminders(status === "authenticated");

  useEffect(() => {
    attachAuthFailureListener();
    void hasServerConfigured().then((configured) => setServerReady(configured));
  }, []);

  useEffect(() => {
    if (serverReady) {
      void restoreSession();
    }
  }, [serverReady, restoreSession]);

  useEffect(() => {
    if (status === "authenticated") {
      void initDevice();
    }
  }, [status, initDevice]);

  if (serverReady === null) {
    return <StartingScreen />;
  }

  if (!serverReady) {
    return <ServerSetupScreen onConnected={() => setServerReady(true)} />;
  }

  if (status === "checking") {
    return <StartingScreen />;
  }

  if (status !== "authenticated") {
    return <LoginScreen />;
  }

  // Forced first-login password change (random/temp password) takes
  // priority over device consent/enrollment — nothing else should be
  // usable until the user has set their own password.
  if (user?.must_change_password) {
    return <ChangePasswordScreen />;
  }

  if (deviceStatus === "needs_consent") {
    return <ConsentNotice />;
  }

  return <AuthenticatedPlaceholder />;
}

function StartingScreen(): JSX.Element {
  return (
    <div
      className="flex h-screen w-screen items-center justify-center"
      style={{ background: "linear-gradient(160deg, hsl(var(--auth-ink)) 0%, hsl(var(--auth-ink-2)) 100%)" }}
    >
      <div className="flex flex-col items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-[hsl(var(--auth-ink-border))] bg-white/5 font-heading text-base font-semibold text-white">
          E
        </div>
        <p className="text-sm text-white/50">Starting…</p>
      </div>
    </div>
  );
}

