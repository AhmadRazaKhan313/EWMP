/**
 * Shared formatters.
 *
 * These four functions were previously copy-pasted across
 * DashboardScreen, AttendanceScreen, PayslipsScreen, LeaveScreen and
 * NotificationsScreen with small inconsistencies (some showed "0h 0m"
 * where others showed "—", two different date formats side by side on the
 * same screen). One definition each, used everywhere.
 *
 * Locale is deliberately left to the OS (`undefined` as the locale arg)
 * rather than hardcoded — employees run this in several countries.
 */

/** "6h 41m". Under an hour drops the hour part entirely: "41m". */
export function formatHours(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return "—";
  const total = Math.max(0, Math.round(minutes));
  const h = Math.floor(total / 60);
  const m = total % 60;
  if (h === 0) return `${m}m`;
  return `${h}h ${m}m`;
}

/** "06:41:22" — the running clock. Always zero-padded and fixed width so
 * the digits do not shift on each tick. */
export function formatElapsed(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  return [Math.floor(s / 3600), Math.floor((s % 3600) / 60), s % 60]
    .map((n) => String(n).padStart(2, "0"))
    .join(":");
}

/** "09:03:32" from an ISO datetime — the Check In / Check Out figures. */
export function formatClockTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

/** "09:03" — the compact form, for dense rows. */
export function formatShortTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false });
}

/** "Wed, 16 Sep". */
export function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

/** "16 September 2026" — the dashboard header's date. */
export function formatLongDate(date: Date): string {
  return date.toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" });
}

/** "September 2026". */
export function formatMonthYear(date: Date): string {
  return date.toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

export function formatMoney(amount: string | number, currency: string): string {
  const n = typeof amount === "number" ? amount : parseFloat(amount);
  if (Number.isNaN(n)) return String(amount);
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(n);
  } catch {
    // Unknown/invalid currency code from the backend shouldn't blank the
    // whole payslip row — fall back to the plain number plus the code.
    return `${n.toFixed(2)} ${currency}`;
  }
}

/** "just now" / "12m ago" / "3h ago" / "2d ago". */
export function timeAgo(iso: string): string {
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return formatDate(iso);
}

/** ISO date (YYYY-MM-DD) in LOCAL time. `toISOString().slice(0,10)` is
 * wrong here — it converts to UTC first, so anyone east of UTC gets
 * yesterday's date after midnight local. That bug silently shifted leave
 * request start dates by a day. */
export function toIsoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function startOfMonth(d = new Date()): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

export function endOfMonth(d = new Date()): Date {
  return new Date(d.getFullYear(), d.getMonth() + 1, 0);
}

/** Counts working days in a month, excluding weekends and the supplied
 * holiday dates. `workDays` is the shift's own list (e.g.
 * ["mon","tue","wed","thu","fri"]) so orgs with Sunday–Thursday weeks are
 * handled correctly rather than assuming Sat/Sun. */
const DAY_KEYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];

export function countWorkingDays(
  from: Date,
  to: Date,
  workDays: string[] | null,
  holidayIsoDates: Set<string>,
): number {
  const allowed = new Set(
    (workDays && workDays.length > 0 ? workDays : ["mon", "tue", "wed", "thu", "fri"]).map((d) =>
      d.toLowerCase().slice(0, 3),
    ),
  );
  let count = 0;
  const cursor = new Date(from.getFullYear(), from.getMonth(), from.getDate());
  while (cursor <= to) {
    const dayKey = DAY_KEYS[cursor.getDay()] ?? "";
    if (allowed.has(dayKey) && !holidayIsoDates.has(toIsoDate(cursor))) {
      count += 1;
    }
    cursor.setDate(cursor.getDate() + 1);
  }
  return count;
}
