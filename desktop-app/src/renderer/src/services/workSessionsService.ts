import apiClient from "@shared/api-client";
import type { WorkSessionItem } from "../types/hrms";

/** GET /work-sessions/me — used by the Dashboard to total up "this week's
 * hours". No dedicated aggregate endpoint exists for this yet on the
 * backend, so a recent page of sessions is fetched and summed client-side;
 * page_size=50 comfortably covers a week even with several
 * check-in/out cycles a day. */
export async function getMyRecentSessions(pageSize = 50): Promise<WorkSessionItem[]> {
  const { data } = await apiClient.get<{ items: WorkSessionItem[]; total: number }>("/work-sessions/me", {
    params: { page: 1, page_size: pageSize },
  });
  return data.items;
}

function startOfWeek(d: Date): Date {
  const date = new Date(d);
  const day = date.getDay(); // 0 = Sunday
  date.setHours(0, 0, 0, 0);
  date.setDate(date.getDate() - day);
  return date;
}

export function effectiveSessionMinutes(s: WorkSessionItem): number {
  // total_minutes is only populated by the backend when a session ends
  // (see work_sessions.py's end_session) — it stays null while a session
  // is still active/on_break. For those, estimate elapsed minutes from
  // started_at to now, minus any completed break time, so "today"/"this
  // week" totals don't silently exclude whatever the employee is
  // currently clocked into.
  if (s.total_minutes != null) return s.total_minutes;
  const elapsed = (Date.now() - new Date(s.started_at).getTime()) / 60000;
  return Math.max(0, Math.round(elapsed) - (s.total_break_minutes || 0));
}

/** The subset of a session list that started today (local midnight to
 * now), oldest first — so the Daily Reports card reads top-to-bottom as
 * "first thing this morning" → "most recent". Exported alongside
 * sumMinutesToday/sumMinutesThisWeek since it answers the same "what
 * happened today" question, just as a list instead of a total. */
export function sessionsToday(sessions: WorkSessionItem[]): WorkSessionItem[] {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return sessions
    .filter((s) => new Date(s.started_at) >= today)
    .sort((a, b) => new Date(a.started_at).getTime() - new Date(b.started_at).getTime());
}

/** Sums minutes for sessions started since the start of this week
 * (Sunday, local time). Active/on_break sessions are estimated live —
 * see effectiveSessionMinutes(). */
export function sumMinutesThisWeek(sessions: WorkSessionItem[]): number {
  const weekStart = startOfWeek(new Date());
  return sessions
    .filter((s) => new Date(s.started_at) >= weekStart)
    .reduce((total, s) => total + effectiveSessionMinutes(s), 0);
}

export function sumMinutesToday(sessions: WorkSessionItem[]): number {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return sessions
    .filter((s) => new Date(s.started_at) >= today)
    .reduce((total, s) => total + effectiveSessionMinutes(s), 0);
}
