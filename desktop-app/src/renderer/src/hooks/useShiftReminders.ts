import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { listShifts, pickDefaultShift, spanMinutesForShift } from "../services/shiftsService";
import { useTimerStore } from "../store/timerStore";
import { formatShortTime, toIsoDate } from "../lib/format";

/**
 * Two native desktop reminders, both driven by the employee's assigned
 * shift (see shiftsService.pickDefaultShift for the single/multi-shift
 * caveat — the same one applies here).
 *
 * 1. START reminder — the moment the shift's start time arrives on a
 *    working day, if the person is not checked in yet, they get a
 *    "time to clock in" notification. This only fires while the app is
 *    open and running (which is what "employee bhi online ho" means
 *    here — there's no server-side push for this, it's a local check
 *    against the wall clock).
 *
 * 2. END reminder — 15 minutes before the shift's scheduled finish,
 *    counted from the employee's actual check-in time across the
 *    shift's FULL span INCLUDING its break (spanMinutesForShift, not
 *    dailyHoursForShift) — a 09:00–18:00 shift with a 1-hour lunch is
 *    still scheduled to end at 18:00, so the reminder fires at 17:45
 *    regardless of how the break was used. This deliberately uses
 *    wall-clock time since check-in (Date.now() - startedAt), not the
 *    timer's pausing `elapsedSeconds` — that field stops advancing on a
 *    break, which would push the reminder later every time someone took
 *    one, defeating the point of a reminder tied to a schedule.
 *
 * Each reminder fires at most once per its own scope (once per calendar
 * day for the start reminder, once per check-in session for the end
 * reminder) via the refs below, and is delivered as a native OS
 * notification through the browser Notification API — Electron grants
 * this without a permission prompt for the app's own renderer, so no
 * IPC round trip to the main process is needed.
 *
 * Mount this ONCE, from App.tsx's MainApp, alongside the other
 * background hooks (useTraySync, useDeviceHeartbeat, ...) — not from
 * WidgetScreen too. Both windows belong to the same running app and the
 * main window keeps running in the background when "closed" (see
 * main/index.ts's close handler), so mounting it twice would fire every
 * reminder twice.
 *
 * `enabled` gates both the shift lookup and the interval — passed as
 * `status === "authenticated"` from MainApp so this does nothing (no
 * network call, no timer) before sign-in, same pattern as
 * useNotificationBadge.
 */
export function useShiftReminders(enabled: boolean): void {
  const shiftsQuery = useQuery({
    queryKey: ["shifts"],
    queryFn: listShifts,
    staleTime: 60 * 60 * 1000,
    enabled,
  });
  const shift = pickDefaultShift(shiftsQuery.data);
  const status = useTimerStore((s) => s.status);
  const startedAt = useTimerStore((s) => s.startedAt);

  const startFiredForDate = useRef<string | null>(null);
  // Keyed by the session's own startedAt timestamp rather than a plain
  // boolean, so a check-out/check-in cycle later the same day is treated
  // as a fresh session and can remind again.
  const endFiredForSession = useRef<number | null>(null);

  useEffect(() => {
    if (!enabled || !shift) return;
    const startMinuteOfDay = toMinutesOfDay(shift.start_time);
    if (startMinuteOfDay === null) return;

    const allowedDays = new Set(
      (shift.work_days && shift.work_days.length > 0 ? shift.work_days : ["mon", "tue", "wed", "thu", "fri"]).map(
        (d) => d.toLowerCase().slice(0, 3),
      ),
    );
    const spanMinutes = spanMinutesForShift(shift);

    // 30s resolution: tight enough that the start reminder's 2-minute
    // window (below) can't be missed by a slow tick, loose enough not to
    // matter for battery/CPU on a background renderer.
    const id = setInterval(() => {
      const now = new Date();
      const todayIso = toIsoDate(now);
      const dayKey = DAY_KEYS[now.getDay()] ?? "";
      const nowMinuteOfDay = now.getHours() * 60 + now.getMinutes();

      // ── Start reminder ────────────────────────────────────────────
      // A 2-minute window from the exact start time, not just the exact
      // minute, so a slightly-late tick or a machine that just woke from
      // sleep still catches it — the per-day ref guard means it still
      // only ever fires once even if several ticks land inside it.
      if (
        allowedDays.has(dayKey) &&
        nowMinuteOfDay >= startMinuteOfDay &&
        nowMinuteOfDay < startMinuteOfDay + 2 &&
        status === "idle" &&
        startFiredForDate.current !== todayIso
      ) {
        startFiredForDate.current = todayIso;
        notify(
          "Time to check in",
          `Your ${shift.name} shift starts now (${shift.start_time.slice(0, 5)}).`,
        );
      }

      // ── End reminder ─────────────────────────────────────────────
      if (
        (status === "active" || status === "on_break") &&
        startedAt &&
        endFiredForSession.current !== startedAt
      ) {
        const elapsedMinutesSinceCheckIn = (Date.now() - startedAt) / 60000;
        const reminderAtMinutes = spanMinutes - 15;
        // Upper bound guards against firing long after the shift should
        // have ended for someone who's been checked in for days — this
        // reminder means "wrap up soon", not "you're already very late".
        if (elapsedMinutesSinceCheckIn >= reminderAtMinutes && elapsedMinutesSinceCheckIn < spanMinutes + 10) {
          endFiredForSession.current = startedAt;
          const expectedEnd = new Date(startedAt + spanMinutes * 60_000);
          notify(
            "Shift ending soon",
            `15 minutes left on your ${shift.name} shift — expected finish around ${formatShortTime(expectedEnd.toISOString())}.`,
          );
        }
      }
    }, 30_000);

    return (): void => clearInterval(id);
  }, [enabled, shift, status, startedAt]);
}

const DAY_KEYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];

function toMinutesOfDay(t: string): number | null {
  const [h, m] = t.split(":").map(Number);
  if (h === undefined || m === undefined || Number.isNaN(h) || Number.isNaN(m)) return null;
  return h * 60 + m;
}

function notify(title: string, body: string): void {
  if (typeof Notification === "undefined") return;
  const fire = (): void => {
    try {
      // eslint-disable-next-line no-new -- fire-and-forget OS notification, nothing to hold a reference to
      new Notification(title, { body });
    } catch {
      // Some Linux desktop environments without a notification daemon
      // throw here rather than failing silently — a missed reminder is
      // not worth crashing anything over.
    }
  };
  if (Notification.permission === "granted") {
    fire();
  } else if (Notification.permission !== "denied") {
    void Notification.requestPermission().then((permission) => {
      if (permission === "granted") fire();
    });
  }
}
