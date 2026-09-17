import { useEffect } from "react";
import { getUnreadNotificationCount } from "../services/notificationsService";

/** Matches DashboardScreen's own unread-count poll interval (see its
 * `refetchInterval: 60_000`) — kept the same cadence so the tray badge
 * and the in-app pill never visibly disagree for long. */
const POLL_INTERVAL_MS = 60_000;

/**
 * Keeps the OS tray/dock badge in sync with the employee's unread
 * notification count for as long as the app is running and they're
 * signed in — see main/index.ts's TRAY_SET_BADGE_COUNT handler for what
 * happens with the number on the main-process side (native dock badge
 * on macOS/Linux, tray tooltip + menu row everywhere).
 *
 * Only polls while `enabled` (i.e. authenticated) — an unauthenticated
 * session has no /notifications to read, and apiClient would just 401.
 */
export function useNotificationBadge(enabled: boolean): void {
  useEffect(() => {
    if (!enabled) {
      void window.ewmp.tray.setBadgeCount(0);
      return;
    }

    let cancelled = false;

    async function poll(): Promise<void> {
      try {
        const count = await getUnreadNotificationCount();
        if (!cancelled) {
          void window.ewmp.tray.setBadgeCount(count);
        }
      } catch {
        // Best-effort — a failed poll (offline, token refresh in flight,
        // etc.) just leaves the badge showing its last-known count until
        // the next tick succeeds. Never surfaces as a user-facing error.
      }
    }

    void poll();
    const timer = setInterval(() => void poll(), POLL_INTERVAL_MS);

    return (): void => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [enabled]);
}
