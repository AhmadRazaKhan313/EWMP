import { create } from "zustand";
import apiClient from "@shared/api-client";
import type { BreakType } from "@shared/deviceTypes";
import { queryClient } from "../lib/queryClient";

export interface WorkSession {
  id: string;
  employee_id: string;
  started_at: string;
  ended_at: string | null;
  status: "active" | "on_break" | "ended";
  total_minutes: number | null;
  // Already returned by the backend (see work_sessions.py's _serialize)
  // specifically so a client can split "time since check-in" into a
  // working timer that pauses on break and a separate break timer —
  // the desktop app just wasn't reading them until now (bug: the main
  // timer kept counting straight through breaks instead of pausing).
  //
  // total_break_minutes is floor-divided server-side and therefore
  // LOSSY — a break under 60 seconds reports as 0. Kept here only for
  // completeness/back-compat; total_break_seconds (below) is exact and
  // is what deriveTimerFields() actually uses. See _break_totals()'s
  // backend docstring for the bug this was causing: a short break's
  // time silently got counted as WORKED time instead of break time.
  total_break_minutes: number;
  total_break_seconds: number;
  current_break_started_at: string | null;
}

export interface BreakRecordSummary {
  id: string;
  started_at: string;
  ended_at: string | null;
}

export const workSessionService = {
  getActive: async (): Promise<WorkSession | null> =>
    (await apiClient.get<WorkSession | null>("/work-sessions/me/active")).data,
  start: async (): Promise<WorkSession> =>
    (await apiClient.post<WorkSession>("/work-sessions/start")).data,
  end: async (id: string): Promise<WorkSession> =>
    (await apiClient.post<WorkSession>(`/work-sessions/${id}/end`)).data,
  // breakTypeId omitted (undefined) -> backend receives break_type_id: null,
  // i.e. the plain "quick pause" from Phase 4 — this endpoint's contract
  // hasn't changed, Phase 5 just adds an optional category on top of it.
  // Returns the full WorkSession (not a bare {status}) — the backend
  // already includes total_break_minutes/current_break_started_at on
  // this response specifically so the timer can re-derive worked-vs-break
  // seconds from server truth right away, no extra round trip.
  startBreak: async (id: string, breakTypeId?: string): Promise<WorkSession> =>
    (await apiClient.post<WorkSession>(`/work-sessions/${id}/break/start`, { break_type_id: breakTypeId ?? null })).data,
  endBreak: async (id: string): Promise<WorkSession> =>
    (await apiClient.post<WorkSession>(`/work-sessions/${id}/break/end`)).data,
  getBreakTypes: async (): Promise<BreakType[]> =>
    (await apiClient.get<{ items: BreakType[] }>("/work-sessions/break-types")).data.items,
  listBreaks: async (sessionId: string): Promise<BreakRecordSummary[]> =>
    (await apiClient.get<{ items: BreakRecordSummary[] }>(`/work-sessions/${sessionId}/breaks`)).data.items,
};

interface TimerState {
  status: "loading" | "idle" | "active" | "on_break" | "ended";
  sessionId: string | null;
  startedAt: number | null; // epoch ms of check-in — server truth
  // "Worked" seconds — time since check-in MINUS all break time (completed
  // breaks + the current one in progress). Pauses while on_break, resumes
  // the instant a break ends. This is what the big timer on screen shows.
  elapsedSeconds: number;
  // Seconds of the break currently in progress (0 when not on break) —
  // drives the separate break-timer display.
  breakSeconds: number;
  completedBreakSeconds: number; // sum of today's FINISHED breaks, from the server
  breakStartedAt: number | null; // epoch ms of the CURRENT break, or null
  error: string | null;
  breakTypes: BreakType[];
  todaysBreaks: BreakRecordSummary[];
  init: () => Promise<void>;
  checkIn: () => Promise<void>;
  checkOut: () => Promise<void>;
  startBreak: (breakTypeId?: string) => Promise<void>;
  endBreak: () => Promise<void>;
  loadBreakTypes: () => Promise<void>;
  refreshBreaks: () => Promise<void>;
  _tick: () => void;
}

function secondsSince(iso: string): number {
  return Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
}

/**
 * Turns any error from a check-in/check-out/break call into one clear,
 * specific sentence — the single place all four timer actions go through
 * for this, so "network issue" (an unhelpfully generic message a real
 * employee reported seeing) can't happen silently in three of the four
 * actions while only checkIn had decent handling.
 *
 * Three cases, checked in order:
 *
 * 1. No `response` on the error at all. This is a genuine connectivity
 *    failure — the request never got an answer (DNS, connection refused,
 *    a CORS preflight rejection, or a timeout). Axios's own `.message`
 *    for this is literally the string "Network Error", which is
 *    technically accurate but tells an employee nothing they can act on.
 *    Replaced with something that names what to actually check.
 *
 * 2. `response.data.error === "EMPLOYEE_PROFILE_NOT_LINKED"` — a specific,
 *    common, and fully actionable condition: the account can log in, but
 *    no Employee row has been linked to it yet (see backend/app/core/
 *    exceptions.py's EmployeeProfileNotLinkedError docstring — this is
 *    the single most likely reason a BRAND NEW employee's first check-in
 *    fails while everything else about their login looks fine, since it
 *    only takes one skipped step in a two-step onboarding flow). Checked
 *    by error CODE, not by matching message text, so it keeps working
 *    even if the backend's wording changes later.
 *
 * 3. Any other backend message, shown as-is — this already worked for
 *    checkIn (e.g. the 409 "today's session already ended" case) and now
 *    applies uniformly to all four actions.
 */
function describeTimerError(err: unknown, fallback: string): string {
  if (err && typeof err === "object" && "response" in err) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const response = (err as any).response;
    if (!response) {
      return "Can't reach the server. Check your internet connection and that the server address is still correct in Settings.";
    }
    if (response.data?.error === "EMPLOYEE_PROFILE_NOT_LINKED") {
      return "Your account isn't linked to an employee profile yet. Ask your HR admin to finish setting up your employee record, then try again.";
    }
    const message = response.data?.message ?? response.data?.detail;
    if (typeof message === "string" && message.length > 0) {
      return message;
    }
  }
  return err instanceof Error ? err.message : fallback;
}

/**
 * Tells TanStack Query "the server just changed" right after a
 * check-in/check-out/break action succeeds.
 *
 * BUG THIS FIXES: the Dashboard's Daily Reports card and today/week stat
 * tiles read from `getMyAttendance` and `getMyRecentSessions`, both
 * polled on a timer (2-minute `refetchInterval`s). Nothing previously
 * told those queries a check-in had just happened, so after checking in
 * again the new session's start time could take up to two minutes to
 * appear — it looked like the dashboard had silently dropped it rather
 * than just being stale. Invalidating by KEY PREFIX (["attendance"],
 * ["work-sessions"]) rather than exact keys means this doesn't need to
 * know about every month/date-range variant those screens query with —
 * TanStack matches any query whose key starts with the given array.
 */
function invalidateAfterTimerAction(): void {
  void queryClient.invalidateQueries({ queryKey: ["attendance"] });
  void queryClient.invalidateQueries({ queryKey: ["work-sessions"] });
}

// Single place that turns a server WorkSession into the four derived timer
// fields — used by init/checkIn/startBreak/endBreak alike so all four stay
// consistent with each other and with _tick()'s own re-derivation.
function deriveTimerFields(session: WorkSession): {
  completedBreakSeconds: number;
  breakStartedAt: number | null;
  elapsedSeconds: number;
  breakSeconds: number;
} {
  // Precise — see WorkSession's total_break_seconds doc comment above for
  // why NOT total_break_minutes * 60 (that's floor-divided and loses any
  // break under 60 seconds entirely).
  const completedBreakSeconds = session.total_break_seconds ?? 0;
  const breakStartedAt = session.current_break_started_at
    ? new Date(session.current_break_started_at).getTime()
    : null;
  const breakSeconds = session.current_break_started_at ? secondsSince(session.current_break_started_at) : 0;
  const secondsSinceCheckIn = secondsSince(session.started_at);
  const elapsedSeconds = Math.max(0, secondsSinceCheckIn - completedBreakSeconds - breakSeconds);
  return { completedBreakSeconds, breakStartedAt, elapsedSeconds, breakSeconds };
}

export const useTimerStore = create<TimerState>((set, get) => ({
  status: "loading",
  sessionId: null,
  startedAt: null,
  elapsedSeconds: 0,
  breakSeconds: 0,
  completedBreakSeconds: 0,
  breakStartedAt: null,
  error: null,
  breakTypes: [],
  todaysBreaks: [],

  // Re-derives from the server on every boot (Phase 4 DoD: timer survives
  // restart, never jumps/resets) — the server's started_at (and now also
  // total_break_minutes/current_break_started_at) is the single source of
  // truth, not anything cached locally.
  init: async (): Promise<void> => {
    try {
      const session = await workSessionService.getActive();
      if (session) {
        set({
          status: session.status === "on_break" ? "on_break" : "active",
          sessionId: session.id,
          startedAt: new Date(session.started_at).getTime(),
          error: null,
          ...deriveTimerFields(session),
        });
        void get().refreshBreaks();
      } else {
        set({
          status: "idle", sessionId: null, startedAt: null,
          elapsedSeconds: 0, breakSeconds: 0, completedBreakSeconds: 0, breakStartedAt: null,
          todaysBreaks: [],
        });
      }
    } catch {
      set({ status: "idle" });
    }
    void get().loadBreakTypes();
  },

  checkIn: async (): Promise<void> => {
    set({ error: null });
    try {
      const session = await workSessionService.start();
      set({
        status: session.status === "on_break" ? "on_break" : "active",
        sessionId: session.id,
        startedAt: new Date(session.started_at).getTime(),
        todaysBreaks: [],
        ...deriveTimerFields(session),
      });
      invalidateAfterTimerAction();
    } catch (err) {
      // Backend returns 409 once today's session is already ended — that
      // specific message (surfaced as-is by describeTimerError) tells the
      // employee exactly what to do instead (use Break), which is why
      // this doesn't just collapse everything to "Check-in failed".
      set({ error: describeTimerError(err, "Check-in failed") });
    }
  },

  checkOut: async (): Promise<void> => {
    const { sessionId } = get();
    if (!sessionId) return;
    set({ error: null });
    try {
      await workSessionService.end(sessionId);
      set({
        status: "idle", sessionId: null, startedAt: null,
        elapsedSeconds: 0, breakSeconds: 0, completedBreakSeconds: 0, breakStartedAt: null,
        todaysBreaks: [],
      });
      invalidateAfterTimerAction();
    } catch (err) {
      set({ error: describeTimerError(err, "Check-out failed") });
    }
  },

  // Pauses the SAME session (status -> on_break) rather than ending it, so
  // one day = one attendance record no matter how many breaks are taken.
  // breakTypeId is optional (Phase 5 picker) — omitted entirely, this is
  // still Phase 4's plain "quick pause", unchanged.
  startBreak: async (breakTypeId?: string): Promise<void> => {
    const { sessionId } = get();
    if (!sessionId) return;
    set({ error: null });
    try {
      const session = await workSessionService.startBreak(sessionId, breakTypeId);
      set({ status: "on_break", ...deriveTimerFields(session) });
      void get().refreshBreaks();
      invalidateAfterTimerAction();
    } catch (err) {
      set({ error: describeTimerError(err, "Could not start break") });
    }
  },

  endBreak: async (): Promise<void> => {
    const { sessionId } = get();
    if (!sessionId) return;
    set({ error: null });
    try {
      const session = await workSessionService.endBreak(sessionId);
      set({ status: "active", ...deriveTimerFields(session) });
      void get().refreshBreaks();
      invalidateAfterTimerAction();
    } catch (err) {
      set({ error: describeTimerError(err, "Could not resume from break") });
    }
  },

  // Fetched once per app session (org-wide, rarely changes) rather than
  // on every render — cheap to call defensively from init(), a no-op
  // network-wise if it 404s/fails on an older backend without this
  // endpoint yet (fails open to an empty list: the picker then just
  // isn't shown, same as an org with zero configured categories).
  loadBreakTypes: async (): Promise<void> => {
    try {
      const breakTypes = await workSessionService.getBreakTypes();
      set({ breakTypes });
    } catch {
      set({ breakTypes: [] });
    }
  },

  refreshBreaks: async (): Promise<void> => {
    const { sessionId } = get();
    if (!sessionId) return;
    try {
      const todaysBreaks = await workSessionService.listBreaks(sessionId);
      set({ todaysBreaks });
    } catch {
      // History list is a nicety, not load-bearing — leave stale data
      // rather than surfacing an error for a background refresh.
    }
  },

  // Re-derives BOTH the worked timer and the break timer from the same
  // three server-truth anchors every second: startedAt (check-in),
  // completedBreakSeconds (finished breaks so far), and breakStartedAt
  // (the current break, if any). Nothing here is a running local counter,
  // so a missed tick, a backgrounded app, or a break that spans a status
  // flip never drifts — it's always recomputed from "now minus anchors".
  _tick: (): void => {
    const { startedAt, status, completedBreakSeconds, breakStartedAt } = get();
    if (status !== "active" && status !== "on_break") return;
    if (!startedAt) return;

    const secondsSinceCheckIn = Math.floor((Date.now() - startedAt) / 1000);
    const breakSeconds = status === "on_break" && breakStartedAt
      ? Math.floor((Date.now() - breakStartedAt) / 1000)
      : 0;
    const elapsedSeconds = Math.max(0, secondsSinceCheckIn - completedBreakSeconds - breakSeconds);
    set({ elapsedSeconds, breakSeconds });
  },
}));

export function formatElapsed(totalSeconds: number): string {
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
}
