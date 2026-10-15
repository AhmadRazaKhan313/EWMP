import { useEffect, useRef } from "react";

/**
 * Keeps this window's view of the attendance state equal to the server's.
 *
 * The server's work session is the one source of truth for the desktop app,
 * the widget and the website. This hook is how a window finds out it changed
 * somewhere else. It re-reads the server (`sync`):
 *
 *   - right away when ANOTHER window of this app changed the state (the main
 *     process relays a nudge over IPC -- instant, no polling delay);
 *   - every `intervalMs`, which is how a change made on the website or another
 *     device arrives;
 *   - when the window is focused or shown again, and when the network comes back
 *     (a PC that slept or lost Wi-Fi catches up at once instead of waiting).
 *
 * Only one read runs at a time (a slow server can't pile up requests), the
 * interval/listeners are all removed on unmount, and the IPC subscription is
 * removed by the function the preload hands back -- so remounting (React
 * StrictMode, switching screens) never leaves a duplicate listener.
 */
export const ATTENDANCE_SYNC_INTERVAL_MS = 5_000;

export function useAttendanceSync(
  sync: () => void | Promise<void>,
  options: { enabled?: boolean; intervalMs?: number } = {},
): void {
  const { enabled = true, intervalMs = ATTENDANCE_SYNC_INTERVAL_MS } = options;
  // Always call the latest `sync` without re-subscribing every render.
  const syncRef = useRef(sync);
  syncRef.current = sync;

  useEffect(() => {
    if (!enabled) return;

    let inFlight = false;
    let alive = true;
    const run = async (): Promise<void> => {
      if (inFlight || !alive) return;
      inFlight = true;
      try {
        await syncRef.current();
      } finally {
        inFlight = false;
      }
    };

    const interval = setInterval(() => void run(), intervalMs);
    const onWake = (): void => {
      if (document.visibilityState !== "hidden") void run();
    };
    window.addEventListener("focus", onWake);
    window.addEventListener("online", onWake);
    document.addEventListener("visibilitychange", onWake);
    const unsubscribe = window.ewmp?.attendance?.onChanged?.(() => void run());

    return (): void => {
      alive = false;
      clearInterval(interval);
      window.removeEventListener("focus", onWake);
      window.removeEventListener("online", onWake);
      document.removeEventListener("visibilitychange", onWake);
      unsubscribe?.();
    };
  }, [enabled, intervalMs]);
}
