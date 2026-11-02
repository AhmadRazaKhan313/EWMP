import type { BreakInfo, BreakPhase } from "../services/breakLockService";

export const WARN_SECONDS = 5 * 60;

export interface BreakView {
  phase: BreakPhase;
  locked: boolean;
  secondsToStart: number;
  secondsToEnd: number;
}

/**
 * Works out the break phase from the window's absolute start/end instants, the
 * server-vs-PC clock offset and the PC's current clock. Recomputed every second
 * from the LAST answer the server gave, so a dropped connection never unlocks
 * the screen early or locks it late: the window just keeps counting.
 */
export function deriveBreakView(info: BreakInfo | undefined, offsetMs: number, nowMs: number): BreakView {
  const none: BreakView = { phase: "none", locked: false, secondsToStart: 0, secondsToEnd: 0 };
  if (!info || !info.has_break || !info.start || !info.end) return none;
  const now = nowMs + offsetMs;
  const start = Date.parse(info.start);
  const end = Date.parse(info.end);
  const secondsToStart = Math.max(0, Math.ceil((start - now) / 1000));
  const secondsToEnd = Math.max(0, Math.ceil((end - now) / 1000));
  let phase: BreakPhase;
  if (now >= end) phase = "over";
  else if (now >= start) phase = "active";
  else if (start - now <= WARN_SECONDS * 1000) phase = "warning";
  else phase = "upcoming";
  const unlocked = info.unlocked_by_admin === true && info.request?.status === "approved";
  return { phase, locked: phase === "active" && !unlocked, secondsToStart, secondsToEnd };
}

export function mmss(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}
