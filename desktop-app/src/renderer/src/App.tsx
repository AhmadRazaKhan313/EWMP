import { useEffect, useState } from "react";
import { useAuthStore, attachAuthFailureListener } from "./store/authStore";
import { useDeviceStore } from "./store/deviceStore";
import { hasServerConfigured } from "@shared/api-client";
import LoginScreen from "./screens/LoginScreen";
import ServerSetupScreen from "./screens/ServerSetupScreen";
import AuthenticatedPlaceholder from "./screens/AuthenticatedPlaceholder";
import ConsentNotice from "./screens/ConsentNotice";
import { useTraySync } from "./hooks/useTraySync";
import { useDeviceHeartbeat } from "./hooks/useDeviceHeartbeat";

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
 */
export default function App(): JSX.Element {
  const status = useAuthStore((s) => s.status);
  const restoreSession = useAuthStore((s) => s.restoreSession);
  const deviceStatus = useDeviceStore((s) => s.status);
  const initDevice = useDeviceStore((s) => s.init);
  const [serverReady, setServerReady] = useState<boolean | null>(null);
  useTraySync();
  useDeviceHeartbeat(deviceStatus);

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

  if (deviceStatus === "needs_consent") {
    return <ConsentNotice />;
  }

  return <AuthenticatedPlaceholder />;
}

function StartingScreen(): JSX.Element {
  return (
    <div className="flex h-screen w-screen items-center justify-center bg-[hsl(var(--background))] text-sm text-[hsl(var(--foreground-muted))]">
      Starting…
    </div>
  );
}

