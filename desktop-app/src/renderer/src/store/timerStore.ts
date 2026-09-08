import { create } from "zustand";
import apiClient from "@shared/api-client";

export interface WorkSession {
  id: string;
  employee_id: string;
  started_at: string;
  ended_at: string | null;
  status: "active" | "on_break" | "ended";
  total_minutes: number | null;
}

export const workSessionService = {
  getActive: async (): Promise<WorkSession | null> =>
    (await apiClient.get<WorkSession | null>("/work-sessions/me/active")).data,
  start: async (): Promise<WorkSession> =>
    (await apiClient.post<WorkSession>("/work-sessions/start")).data,
  end: async (id: string): Promise<WorkSession> =>
    (await apiClient.post<WorkSession>(`/work-sessions/${id}/end`)).data,
  startBreak: async (id: string): Promise<{ status: string }> =>
    (await apiClient.post<{ status: string }>(`/work-sessions/${id}/break/start`, {})).data,
  endBreak: async (id: string): Promise<{ status: string }> =>
    (await apiClient.post<{ status: string }>(`/work-sessions/${id}/break/end`)).data,
};

interface TimerState {
  status: "loading" | "idle" | "active" | "on_break" | "ended";
  sessionId: string | null;
  startedAt: number | null; // epoch ms — server truth, timer re-derives elapsed from this, never a local counter
  elapsedSeconds: number;
  error: string | null;
  init: () => Promise<void>;
  checkIn: () => Promise<void>;
  checkOut: () => Promise<void>;
  startBreak: () => Promise<void>;
  endBreak: () => Promise<void>;
  _tick: () => void;
}

function secondsSince(iso: string): number {
  return Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
}

export const useTimerStore = create<TimerState>((set, get) => ({
  status: "loading",
  sessionId: null,
  startedAt: null,
  elapsedSeconds: 0,
  error: null,

  // Re-derives from the server on every boot (Phase 4 DoD: timer survives
  // restart, never jumps/resets) — the server's started_at is the single
  // source of truth, not anything cached locally.
  init: async (): Promise<void> => {
    try {
      const session = await workSessionService.getActive();
      if (session) {
        set({
          status: session.status === "on_break" ? "on_break" : "active",
          sessionId: session.id,
          startedAt: new Date(session.started_at).getTime(),
          elapsedSeconds: secondsSince(session.started_at),
          error: null,
        });
      } else {
        set({ status: "idle", sessionId: null, startedAt: null, elapsedSeconds: 0 });
      }
    } catch {
      set({ status: "idle" });
    }
  },

  checkIn: async (): Promise<void> => {
    set({ error: null });
    try {
      const session = await workSessionService.start();
      set({
        status: session.status === "on_break" ? "on_break" : "active",
        sessionId: session.id,
        startedAt: new Date(session.started_at).getTime(),
        elapsedSeconds: secondsSince(session.started_at),
      });
    } catch (err) {
      // Backend returns 409 once today's session is already ended — surface
      // that message as-is rather than the generic "Check-in failed", since
      // it tells the employee exactly what to do instead (use Break).
      const message =
        err && typeof err === "object" && "response" in err
          ? // eslint-disable-next-line @typescript-eslint/no-explicit-any
            ((err as any).response?.data?.message ?? (err as any).response?.data?.detail)
          : undefined;
      set({ error: message ?? (err instanceof Error ? err.message : "Check-in failed") });
    }
  },

  checkOut: async (): Promise<void> => {
    const { sessionId } = get();
    if (!sessionId) return;
    set({ error: null });
    try {
      await workSessionService.end(sessionId);
      set({ status: "idle", sessionId: null, startedAt: null, elapsedSeconds: 0 });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Check-out failed" });
    }
  },

  // Pauses the SAME session (status -> on_break) rather than ending it, so
  // one day = one attendance record no matter how many breaks are taken.
  startBreak: async (): Promise<void> => {
    const { sessionId } = get();
    if (!sessionId) return;
    set({ error: null });
    try {
      await workSessionService.startBreak(sessionId);
      set({ status: "on_break" });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Could not start break" });
    }
  },

  endBreak: async (): Promise<void> => {
    const { sessionId } = get();
    if (!sessionId) return;
    set({ error: null });
    try {
      await workSessionService.endBreak(sessionId);
      set({ status: "active" });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Could not resume from break" });
    }
  },

  _tick: (): void => {
    const { startedAt, status } = get();
    // Elapsed time keeps counting through a break — it reflects "time since
    // check-in", not "time actively working"; break duration is tracked
    // separately server-side via BreakRecord for payroll/reporting.
    if ((status === "active" || status === "on_break") && startedAt) {
      set({ elapsedSeconds: Math.floor((Date.now() - startedAt) / 1000) });
    }
  },
}));

export function formatElapsed(totalSeconds: number): string {
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
}
