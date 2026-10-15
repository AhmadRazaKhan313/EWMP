/**
 * The website's one view of "what is my attendance right now".
 *
 * The server's work session (GET /work-sessions/me/active) is the single source
 * of truth shared by the website, the desktop app and the desktop widget. Every
 * website component that shows or changes attendance reads it through here, so
 * they all use the same query, the same refresh rules and the same arithmetic --
 * and therefore always show the same state and the same numbers.
 */
import apiClient from "./api-client";

export const ACTIVE_SESSION_KEY = ["work-session", "active"] as const;

// How soon a change made in the desktop app / widget (or another device) shows
// up here. Cheap: one small indexed read per tab, only while the tab is visible.
export const ATTENDANCE_SYNC_INTERVAL_MS = 5_000;

/**
 * Query options every attendance reader uses. The app-wide defaults say "fresh for
 * a minute, never refetch on focus" -- right for most data, wrong here: coming
 * back to the tab (or the network returning) must show the CURRENT state, not
 * whatever was cached before the employee started a break in the widget.
 */
export const ATTENDANCE_QUERY_OPTIONS = {
  refetchInterval: ATTENDANCE_SYNC_INTERVAL_MS,
  refetchOnWindowFocus: true,
  refetchOnReconnect: true,
  staleTime: 0,
} as const;

export interface ActiveWorkSession {
  id: string;
  employee_id?: string;
  started_at: string;
  ended_at?: string | null;
  status: "active" | "on_break" | "ended";
  total_minutes?: number | null;
  total_break_minutes?: number;
  /** Finished breaks, exact. */
  total_break_seconds?: number;
  current_break_started_at?: string | null;
  /** The server's clock when it answered. */
  server_time?: string;
}

export interface ActiveSession extends ActiveWorkSession {
  /** server clock minus this device's clock, measured when the answer arrived. */
  clock_offset_ms: number;
}

export async function fetchActiveSession(): Promise<ActiveSession | null> {
  const { data } = await apiClient.get<ActiveWorkSession | null>("/work-sessions/me/active");
  if (!data) return null;
  const offset = data.server_time ? new Date(data.server_time).getTime() - Date.now() : 0;
  return { ...data, clock_offset_ms: Number.isFinite(offset) ? offset : 0 };
}

export interface SessionClock {
  isCheckedIn: boolean;
  isOnBreak: boolean;
  /** Time worked: since check-in, minus every break (the one in progress too). Pauses on break. */
  workedSeconds: number;
  /** All of today's break time: finished breaks + the one in progress. */
  breakSeconds: number;
}

const secondsBetween = (fromIso: string, toMs: number): number =>
  Math.max(0, Math.floor((toMs - new Date(fromIso).getTime()) / 1000));

/** All timer numbers, derived from the server's timestamps and the server's
 * clock (this device's clock plus the measured offset) -- never from a counter
 * that could drift or keep running after a break ended somewhere else. */
export function sessionClock(session: ActiveSession | null | undefined, clientNowMs: number = Date.now()): SessionClock {
  const isOnBreak = session?.status === "on_break";
  const isCheckedIn = !!session && (session.status === "active" || isOnBreak);
  if (!session || !isCheckedIn) return { isCheckedIn: false, isOnBreak: false, workedSeconds: 0, breakSeconds: 0 };

  const nowMs = clientNowMs + session.clock_offset_ms;
  const finished = session.total_break_seconds ?? (session.total_break_minutes ?? 0) * 60;
  const current = session.current_break_started_at ? secondsBetween(session.current_break_started_at, nowMs) : 0;
  return {
    isCheckedIn,
    isOnBreak,
    workedSeconds: Math.max(0, secondsBetween(session.started_at, nowMs) - finished - current),
    breakSeconds: finished + current,
  };
}
