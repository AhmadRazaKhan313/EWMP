import apiClient from "@shared/api-client";

/**
 * Mirrors backend/app/api/v1/hrms/shifts.py's list_shifts() response.
 *
 * NOTE: `GET /shifts` is the one HRMS list endpoint with NO permission
 * gate — it depends on `get_current_user` only, not `require_permission`
 * (create/update/delete below it all require `attendance.view`). So a
 * plain employee can read the org's shift configuration, which is what
 * makes the dashboard's "Required Working Hours" figure possible at all.
 */
export interface ShiftItem {
  id: string;
  name: string;
  code: string;
  color: string;
  start_time: string; // "09:00:00"
  end_time: string; // "17:00:00"
  is_overnight: boolean;
  late_grace_minutes: number;
  break_duration_minutes: number;
  work_days: string[] | null; // ["mon","tue",...]
  weekly_hours: string; // decimal-as-string, same convention as payroll
  is_active: boolean;
}

export async function listShifts(): Promise<ShiftItem[]> {
  const { data } = await apiClient.get<{ items: ShiftItem[]; total: number }>("/shifts");
  return data.items.filter((s) => s.is_active);
}

/**
 * The org's default working pattern.
 *
 * KNOWN LIMITATION — read before relying on this: the backend has no
 * "my shift" endpoint. `POST /shifts/{id}/assign` sets an employee's
 * default shift, but nothing exposes it back to the employee, and
 * `GET /auth/me` does not include it either. So this picks the org's
 * first active shift rather than the caller's actual assigned one.
 *
 * For a single-shift org (the common case) that is exactly right. For an
 * org running multiple shifts it will be wrong for anyone not on the
 * first one, which is why every figure derived from it is labelled
 * "expected" in the UI rather than presented as authoritative, and why
 * overtime is still read from the server's own overtime_minutes rather
 * than computed from this.
 *
 * Fix when the backend can: add `shift` to GET /auth/me's response, then
 * replace this function's body with that field. Nothing else changes.
 */
export function pickDefaultShift(shifts: ShiftItem[] | undefined): ShiftItem | null {
  if (!shifts || shifts.length === 0) return null;
  return shifts[0] ?? null;
}

/** "09:00:00" → 540. Guarded rather than destructured: a malformed time
 * string from the backend should fall back gracefully, not produce NaN
 * that then renders as "NaNh" somewhere in the UI. */
function toMinutesOfDay(t: string): number | null {
  const [h, m] = t.split(":").map(Number);
  if (h === undefined || m === undefined || Number.isNaN(h) || Number.isNaN(m)) return null;
  return h * 60 + m;
}

/** The shift's raw span in minutes, start to end, WITH its break still
 * inside it — e.g. 09:00–18:00 is 540 minutes (9h) even though 60 of
 * those minutes are an unpaid break. Handles overnight shifts (22:00 →
 * 06:00) by adding a day. This is the number reminders are timed against
 * (see hooks/useShiftReminders.ts) because a "9-to-6 including a lunch
 * hour" shift is scheduled to end at 6, not at 5 — the break doesn't
 * push the end time out. */
export function spanMinutesForShift(shift: ShiftItem | null): number {
  if (!shift) return 9 * 60; // 8 paid hours + a 1h break, the common default
  const start = toMinutesOfDay(shift.start_time);
  const end = toMinutesOfDay(shift.end_time);
  if (start === null || end === null) return 9 * 60;
  let minutes = end - start;
  if (minutes <= 0 || shift.is_overnight) minutes += 24 * 60;
  return minutes;
}

/** Daily PAID hours implied by a shift: the span above minus its unpaid
 * break. This is what the dashboard's ring and stat band scale against —
 * overtime should trigger once the paid day is done, not once the whole
 * scheduled span (break included) has elapsed. */
export function dailyHoursForShift(shift: ShiftItem | null): number {
  const spanMinutes = spanMinutesForShift(shift);
  const paidMinutes = spanMinutes - (shift?.break_duration_minutes ?? 60);
  const hours = paidMinutes / 60;
  return hours > 0 && hours <= 24 ? hours : 8;
}
